"""
Shared utilities for the AI-Debate MeSH-tagging experiments.

This module centralises everything the individual experiment scripts need so
that behaviour is *identical* across baseline / statement / interactive / rejudge:

  * Pydantic schemas (JudgeResponse, DebaterResponse)
  * robust_generate(): forces a schema-valid answer, re-rolling several times
                       (issue 1). A judge answer can additionally never be
                       "Unknown" because we fall back to the log-prob verdict.
  * judge_confidence(): computes the judge's confidence as LOG PROBABILITIES
                        in two independent phrasings (issue 4):
                          - "the tag belongs"  -> P(Yes) vs P(No)
                          - "Debater A is right" -> P(A) vs P(B)
  * run_judge(): generate + confidence + guaranteed-valid decision.
  * message builders (baseline / debater / judge) shared by every script and
    by the rejudge script so debates can be recycled verbatim.
  * atomic save + crash-recovery helpers (issue 6).
"""

import os
import re
import math
import json
import random
import tempfile
import argparse

import torch
from pydantic import BaseModel, Field, ValidationError
from transformers import AutoModelForCausalLM, AutoTokenizer

# Respect the cluster's CPU allocation for intra-op threading (issue 6).
try:
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
except Exception:
    pass

HF_TOKEN = os.environ.get("HF_TOKEN")


# ==============================================================================
# --- SCHEMAS ---
# ==============================================================================
class JudgeResponse(BaseModel):
    thinking: str = Field(description="Step-by-step reasoning.")
    answer: str = Field(description="Final decision, strictly 'Yes' or 'No'.")


class DebaterResponse(BaseModel):
    thinking: str = Field(description="Brief internal strategic reasoning.")
    argument: str = Field(description="The final argument, under 150 words.")


# ==============================================================================
# --- MODEL LOADING ---
# ==============================================================================
def load_model(model_id):
    kw = {"token": HF_TOKEN} if HF_TOKEN else {}
    tok = AutoTokenizer.from_pretrained(model_id, **kw)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    mod = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=torch.float16, device_map="cuda", **kw
    )
    mod.eval()
    return mod, tok


# ==============================================================================
# --- PARSING / GENERATION ---
# ==============================================================================
def extract_pydantic(response, schema_class):
    """Try to validate the first JSON object found in `response`."""
    json_text = re.sub(r"```json\s*", "", response, flags=re.IGNORECASE)
    json_text = re.sub(r"```\s*", "", json_text)
    start = json_text.find("{")
    end = json_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return schema_class.model_validate_json(json_text[start:end + 1])
        except ValidationError:
            pass
    return None


def robust_generate(messages, model, tokenizer, schema_class, field,
                    max_new_tokens=350, base_temp=0.3, max_retries=6):
    """
    Generate until a *schema-valid* value for `field` is produced (issue 1).

    We re-roll up to `max_retries` times, escalating temperature a little each
    time to break out of degenerate loops. Return value:
        (value, raw_text, n_attempts)

    * field == "answer":  returns 'Yes'/'No', or 'Unknown' if every roll failed
                          (the caller then decides via log-probs, so the final
                          stored decision is still never 'Unknown').
    * field == "argument": always returns usable text (falls back to the
                          cleaned raw output) so a debater never produces
                          'Unknown'.
    """
    raw = ""
    for attempt in range(max_retries):
        temp = min(base_temp + 0.1 * attempt, 1.0)
        text_in = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        enc = tokenizer([text_in], return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(
                **enc, max_new_tokens=max_new_tokens, temperature=temp,
                do_sample=True, top_p=0.95, pad_token_id=tokenizer.eos_token_id,
            )
        raw = tokenizer.batch_decode(
            [out[0][enc.input_ids.shape[1]:]], skip_special_tokens=True
        )[0].strip()

        parsed = extract_pydantic(raw, schema_class)
        if parsed is not None:
            val = getattr(parsed, field).strip()
            if field == "answer":
                if val.capitalize() in ("Yes", "No"):
                    return val.capitalize(), raw, attempt + 1
            elif val:
                return val, raw, attempt + 1

    # ---- Fallbacks (still trying hard not to lose the roll) ----
    m = re.findall(rf'"{field}"\s*:\s*"(.*?)"', raw, re.IGNORECASE | re.DOTALL)
    if field == "answer":
        if m and m[-1].strip().capitalize() in ("Yes", "No"):
            return m[-1].strip().capitalize(), raw, max_retries
        return "Unknown", raw, max_retries
    # argument: never return Unknown -> clean the raw text
    if m and m[-1].strip():
        return m[-1].strip(), raw, max_retries
    cleaned = re.sub(r'[{}"]', " ", raw).strip()
    return (cleaned[:1500] if cleaned else "No argument produced."), raw, max_retries


# ==============================================================================
# --- LOG-PROBABILITY CONFIDENCE (issue 4) ---
# ==============================================================================
def _probe_logprobs(model, tokenizer, messages, nudge, candidates):
    """
    Force the judge to commit to a single-token verdict and read off the
    log probability the model assigns to each candidate answer.

    Returns (logprobs_dict, normalised_probs_dict).
    """
    probe = list(messages) + [{"role": "user", "content": nudge}]
    base = tokenizer.apply_chat_template(probe, tokenize=False, add_generation_prompt=True)
    base_ids = tokenizer(base, return_tensors="pt").input_ids.to(model.device)

    logprobs = {}
    for key, txt in candidates.items():
        cand = tokenizer(txt, return_tensors="pt", add_special_tokens=False).input_ids.to(model.device)
        full = torch.cat([base_ids, cand], dim=1)
        with torch.no_grad():
            logits = model(full).logits
        logp = torch.log_softmax(logits.float(), dim=-1)
        total = 0.0
        for i in range(cand.shape[1]):
            pos = base_ids.shape[1] + i - 1            # logits at pos predict next token
            tok = full[0, base_ids.shape[1] + i]
            total += logp[0, pos, tok].item()
        logprobs[key] = total

    mx = max(logprobs.values())
    exps = {k: math.exp(v - mx) for k, v in logprobs.items()}
    z = sum(exps.values())
    probs = {k: exps[k] / z for k in logprobs}
    return logprobs, probs


BELONGS_NUDGE = (
    "Based strictly on everything above, give your final verdict as exactly one "
    "word: 'Yes' if the candidate tag belongs to the article, or 'No' if it does not."
)
DEBATER_NUDGE = (
    "Based strictly on everything above, which debater argued more correctly? "
    "Answer with exactly one letter: 'A' or 'B'."
)


def judge_confidence(model, tokenizer, messages, include_debater_probe=True):
    """
    Two independent phrasings of the same binary decision (issue 4):

      1. 'the tag belongs'  -> logprob_yes / logprob_no / prob_belongs
      2. 'Debater A is right' -> logprob_debater_a / logprob_debater_b /
                                 prob_debater_a_right   (debate scripts only)
    """
    lp_b, p_b = _probe_logprobs(model, tokenizer, messages, BELONGS_NUDGE,
                                {"Yes": "Yes", "No": "No"})
    conf = {
        "logprob_yes": lp_b["Yes"],
        "logprob_no": lp_b["No"],
        "prob_belongs": p_b["Yes"],
    }
    if include_debater_probe:
        lp_d, p_d = _probe_logprobs(model, tokenizer, messages, DEBATER_NUDGE,
                                    {"A": "A", "B": "B"})
        conf.update({
            "logprob_debater_a": lp_d["A"],
            "logprob_debater_b": lp_d["B"],
            "prob_debater_a_right": p_d["A"],
        })
    return conf


def run_judge(model, tokenizer, messages, include_debater_probe=True):
    """Confidence + guaranteed-valid Yes/No decision (never 'Unknown')."""
    conf = judge_confidence(model, tokenizer, messages, include_debater_probe)
    ans, raw, tries = robust_generate(
        messages, model, tokenizer, JudgeResponse, "answer", max_new_tokens=512
    )
    fallback = False
    if ans not in ("Yes", "No"):
        ans = "Yes" if conf["prob_belongs"] >= 0.5 else "No"
        fallback = True
    result = {
        "answer": ans,
        "judge_output": raw,
        "judge_attempts": tries,
        "judge_fallback_used": fallback,
    }
    result.update(conf)
    return result


# ==============================================================================
# --- MESSAGE BUILDERS (shared so rejudge reproduces prompts exactly) ---
# ==============================================================================
_JUDGE_SCHEMA_BLOCK = (
    "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
    "Your JSON MUST contain the 'thinking' key FIRST and the 'answer' key AT THE VERY END.\n\n"
    "REQUIRED JSON SCHEMA:\n"
    '{\n  "thinking": "Step-by-step analysis.",\n  "answer": "Yes" or "No"\n}'
)

_DEBATER_SCHEMA_BLOCK = (
    "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
    "Your JSON MUST contain the 'thinking' key FIRST and the 'argument' key AT THE VERY END.\n\n"
    "REQUIRED JSON SCHEMA:\n"
    '{\n  "thinking": "Brief strategic reasoning.",\n  "argument": "Your concise argument (under 150 words)."\n}'
)


def build_baseline_messages(abstract, assigned_tags, candidate_tag, manual_text, include_manual=True):
    system = (
        "You are an expert judge for a medical indexing task. Determine whether a candidate "
        "Medical Subject Heading (MeSH) tag should be assigned to a biomedical article.\n"
        + _JUDGE_SCHEMA_BLOCK
    )
    manual_block = f"<indexing_manual>\n{manual_text}\n</indexing_manual>\n\n" if (include_manual and manual_text) else ""
    user = (
        f"{manual_block}"
        f"Abstract: {abstract}\n"
        f"Already Assigned Tags: {', '.join(assigned_tags)}\n"
        f"Candidate Tag: {candidate_tag}\n\n"
        "Based on the abstract, does the candidate tag belong? Follow the REQUIRED JSON SCHEMA exactly."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_debater_messages(abstract, assigned_tags, candidate_tag, side, previous_turns=""):
    system = (
        f"You are an expert medical debater. Persuade the judge that the tag "
        f"{'BELONGS' if side == 'PRO' else 'DOES NOT BELONG'}.\n"
        "CRITICAL RULE: NEVER concede. Always confidently defend your assigned position and "
        "critique your opponent's hidden reasoning mistakes.\n"
        + _DEBATER_SCHEMA_BLOCK
    )
    user = (
        f"Abstract:\n{abstract}\n\n"
        f"Assigned Tags: {', '.join(assigned_tags)}\n"
        f"Candidate Tag: {candidate_tag}\n\n"
        f"{previous_turns}\n\nWrite your argument."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_judge_transcript_messages(abstract, candidate_tag, turns, manual_text="", include_manual=False):
    """
    Generic judge prompt over an ordered `turns` list. Each turn is a dict:
        {"speaker": "Debater A", "role": "Opening statement", "text": "..."}
    Used by both the statement and interactive experiments and by rejudge.
    """
    system = (
        "You are an impartial expert judge in a medical debate. Decide whether the candidate "
        "tag belongs to the abstract, weighing the debaters' arguments.\n"
        + _JUDGE_SCHEMA_BLOCK
    )
    parts = []
    if include_manual and manual_text:
        parts.append(f"<indexing_manual>\n{manual_text}\n</indexing_manual>")
    parts.append(f"Abstract:\n{abstract}")
    parts.append(f"Candidate Tag: {candidate_tag}")
    for t in turns:
        parts.append(f"{t['speaker']} ({t['role']}):\n{t['text']}")
    parts.append("Does the candidate tag belong? Follow the REQUIRED JSON SCHEMA exactly.")
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(parts)}]


# ==============================================================================
# --- IO / RESUME / CHUNKING (issue 6) ---
# ==============================================================================
def parse_args(extra=None):
    p = argparse.ArgumentParser()
    p.add_argument("--test_mode", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--chunk_id", type=int, default=0)
    p.add_argument("--total_chunks", type=int, default=1)
    if extra:
        extra(p)
    return p.parse_args()


def load_resources(dataset_path, manual_path):
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    try:
        with open(manual_path, "r", encoding="utf-8") as f:
            manual_text = f.read()
    except FileNotFoundError:
        manual_text = ""
    return dataset, manual_text


def chunk_dataset(dataset, chunk_id, total_chunks):
    if total_chunks <= 1:
        return dataset
    size = (len(dataset) + total_chunks - 1) // total_chunks
    start = chunk_id * size
    end = min(start + size, len(dataset))
    return dataset[start:end]


def load_existing(output_file):
    """Return (results_list, completed_key_set) for crash recovery."""
    results, done = [], set()
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            results = data.get("results", [])
            for r in results:
                done.add((r.get("stage"), r.get("pmid")))
            print(f"[RESUME] {len(results)} records found in {output_file}. Continuing.")
        except json.JSONDecodeError:
            print(f"[WARN] {output_file} corrupted; restarting this chunk.")
    return results, done


def save_results_atomically(file_path, data):
    dir_name = os.path.dirname(file_path) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
    try:
        os.replace(temp_name, file_path)
    except Exception:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def pick_case(article, stage_name, ground_truth, rng):
    """Return (candidate_tag, assigned_tags) for a given stage."""
    correct = article.get("mesh_tags", [])
    if ground_truth == "Yes":
        candidate = rng.choice(correct)
        assigned = [t for t in correct if t != candidate]
    elif stage_name == "Round 2: Unrelated Tag":
        candidate = article.get("unrelated_negative_test_tag",
                                article.get("negative_test_tag", "Unknown"))
        assigned = correct
    else:
        candidate = article.get("similar_negative_test_tag", "Unknown")
        assigned = correct
    return candidate, assigned


STAGES = [
    ("Round 1: True Tag", "Yes"),
    ("Round 2: Unrelated Tag", "No"),
    ("Round 3: Similar Tag", "No"),
]
