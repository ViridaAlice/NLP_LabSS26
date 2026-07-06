"""
Shared utilities for the AI-Debate XMLC experiments.

Backend: local Hugging Face Transformers models (no external API).
Because the models run locally, log-probabilities are read directly from the
model's forward pass via teacher forcing (see score_continuations / decision_confidence).

This module provides:
  * Strict Pydantic schemas for judge / debater outputs.
  * A re-roll generation loop that FORCES valid structured output.
  * A guaranteed logprob-argmax fallback for the judge (so 'Unknown' can never occur).
  * Log-probability based confidence for the judge's decision (two framings).
  * Crash-proof atomic checkpoint saving.
"""

import os
import re
import json
import math
import tempfile

import torch
from pydantic import BaseModel, Field, ValidationError

# ------------------------------------------------------------------ #
# Configuration constants
# ------------------------------------------------------------------ #
MAX_REROLLS = 6           # how many times we re-roll until output is valid


# ------------------------------------------------------------------ #
# Pydantic schemas
# ------------------------------------------------------------------ #
class JudgeResponse(BaseModel):
    thinking: str = Field(description="Step-by-step reasoning. Keep under 180 words.")
    answer: str = Field(description="Final decision, strictly 'Yes' or 'No'.")


class DebaterResponse(BaseModel):
    thinking: str = Field(description="Brief internal strategic reasoning.")
    argument: str = Field(description="Final argument for the judge, under 150 words.")


# ------------------------------------------------------------------ #
# Environment / threading setup (cluster friendly)
# ------------------------------------------------------------------ #
def setup_threads():
    """Respect the SLURM cpus-per-task allocation for CPU-side ops."""
    n = os.environ.get("OMP_NUM_THREADS") or os.environ.get("SLURM_CPUS_PER_TASK")
    if n:
        try:
            torch.set_num_threads(int(n))
        except Exception:
            pass


# ------------------------------------------------------------------ #
# Resource loading
# ------------------------------------------------------------------ #
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_manual(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# ------------------------------------------------------------------ #
# Crash-proof atomic save
# ------------------------------------------------------------------ #
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
        raise


def load_checkpoint(output_file, key_fields=("stage", "pmid")):
    """Return (results_list, completed_set). Resumes from a previous partial run."""
    results, done = [], set()
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            results = saved.get("results", [])
            for r in results:
                done.add(tuple(r.get(k) for k in key_fields))
            print(f"[RESUME] {output_file}: fast-forwarding {len(results)} records.")
        except json.JSONDecodeError:
            print(f"[WARN] {output_file} was corrupted; starting fresh.")
    return results, done


# ------------------------------------------------------------------ #
# Robust JSON parsing (handles fences + truncation)
# ------------------------------------------------------------------ #
def parse_structured(response, schema_class, field):
    """Return the requested field's value or None."""
    txt = re.sub(r"```json\s*", "", response, flags=re.IGNORECASE)
    txt = re.sub(r"```\s*", "", txt)
    start = txt.find("{")
    end = txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = schema_class.model_validate_json(txt[start:end + 1])
            return getattr(obj, field).strip()
        except ValidationError:
            pass
    # Regex fallback: survives truncated JSON where the closing brace is missing.
    m = re.findall(rf'"{field}"\s*:\s*"(.*?)"', txt, re.IGNORECASE | re.DOTALL)
    if m:
        return m[-1].strip()
    return None


# ------------------------------------------------------------------ #
# Core HF generation
# ------------------------------------------------------------------ #
@torch.no_grad()
def hf_generate(messages, model, tokenizer, max_new_tokens, temperature):
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    enc = tokenizer([text], return_tensors="pt").to(model.device)
    out = model.generate(
        **enc,
        max_new_tokens=max_new_tokens,
        temperature=max(temperature, 1e-4),
        do_sample=True,
        pad_token_id=tokenizer.eos_token_id,
    )
    resp = tokenizer.batch_decode(
        [out[0][enc.input_ids.shape[1]:]], skip_special_tokens=True
    )[0].strip()
    return resp


def generate_argument(messages, model, tokenizer, max_new_tokens=320,
                      base_temp=0.3, rerolls=MAX_REROLLS):
    """Re-roll until a non-empty argument is produced (debaters never go 'Unknown')."""
    raw = ""
    for attempt in range(rerolls):
        temp = min(base_temp + 0.1 * attempt, 1.0)
        raw = hf_generate(messages, model, tokenizer, max_new_tokens, temp)
        arg = parse_structured(raw, DebaterResponse, "argument")
        if arg and len(arg.strip()) > 0:
            return arg.strip(), raw
    # Fallback: use whatever text was produced.
    return (raw.strip() or "(no argument produced)"), raw


def generate_judge_answer(messages, model, tokenizer, max_new_tokens=768,
                          base_temp=0.2, rerolls=MAX_REROLLS):
    """
    Re-roll until the judge produces a valid 'Yes'/'No'.
    Returns (answer_or_None, raw_text, needed_fallback_bool).
    If all re-rolls fail, answer is None -> caller uses the logprob argmax.
    """
    raw = ""
    for attempt in range(rerolls):
        temp = min(base_temp + 0.1 * attempt, 1.0)
        raw = hf_generate(messages, model, tokenizer, max_new_tokens, temp)
        ans = parse_structured(raw, JudgeResponse, "answer")
        if ans and ans.strip().capitalize() in ("Yes", "No"):
            return ans.strip().capitalize(), raw, False
    return None, raw, True


# ------------------------------------------------------------------ #
# Log-probability scoring (confidence)
# ------------------------------------------------------------------ #
def _augment_last_user(messages, instruction):
    msgs = [dict(m) for m in messages]
    msgs[-1] = dict(msgs[-1])
    msgs[-1]["content"] = msgs[-1]["content"] + "\n\n" + instruction
    return msgs


@torch.no_grad()
def score_continuations(context_messages, continuations, model, tokenizer):
    """
    Teacher-force each candidate continuation string after the prompt and
    return the summed token log-probability for each label.
    """
    base_text = tokenizer.apply_chat_template(
        context_messages, tokenize=False, add_generation_prompt=True
    )
    base_ids = tokenizer(base_text, return_tensors="pt").input_ids.to(model.device)
    scores = {}
    for label, cont in continuations.items():
        cont_ids = tokenizer(cont, add_special_tokens=False,
                             return_tensors="pt").input_ids.to(model.device)
        full = torch.cat([base_ids, cont_ids], dim=1)
        logits = model(full).logits
        logprobs = torch.log_softmax(logits.float(), dim=-1)
        total = 0.0
        p = base_ids.shape[1]
        for j in range(cont_ids.shape[1]):
            total += logprobs[0, p + j - 1, full[0, p + j]].item()
        scores[label] = total
    return scores


def _to_probs(scores):
    m = max(scores.values())
    exps = {k: math.exp(v - m) for k, v in scores.items()}
    z = sum(exps.values())
    return {k: exps[k] / z for k in exps}


def decision_confidence(judge_messages, model, tokenizer, include_debater=False):
    """
    Compute the judge's decision confidence via TWO framings of the binary choice:
      1) 'the tag belongs'  -> Yes / No
      2) boolean            -> true / false
    For debate scripts a third framing 'Debater A is right' -> A / B is added.
    Returns a dict with raw logprobs and normalised probabilities for each framing.
    """
    out = {}

    v = score_continuations(
        _augment_last_user(
            judge_messages,
            "Respond with exactly one word, either Yes or No, indicating whether "
            "the candidate tag belongs to the abstract.",
        ),
        {"Yes": " Yes", "No": " No"}, model, tokenizer,
    )
    out["verdict_logprob"] = v
    out["verdict_prob_belongs"] = _to_probs(v)["Yes"]

    b = score_continuations(
        _augment_last_user(
            judge_messages,
            "Respond with exactly one word, either true or false: the candidate "
            "tag belongs to the abstract.",
        ),
        {"true": " true", "false": " false"}, model, tokenizer,
    )
    out["boolean_logprob"] = b
    out["boolean_prob_true"] = _to_probs(b)["true"]

    if include_debater:
        d = score_continuations(
            _augment_last_user(
                judge_messages,
                "Respond with exactly one letter, either A or B, indicating which "
                "debater is correct.",
            ),
            {"A": " A", "B": " B"}, model, tokenizer,
        )
        out["debater_logprob"] = d
        out["debater_prob_A_right"] = _to_probs(d)["A"]

    return out


def verdict_from_confidence(confidence):
    """Guaranteed Yes/No from the logprob framing (used as the no-Unknown fallback)."""
    return "Yes" if confidence.get("verdict_prob_belongs", 0.5) >= 0.5 else "No"


# ------------------------------------------------------------------ #
# Model loading helper
# ------------------------------------------------------------------ #
def load_model(model_id):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    token = os.environ.get("HF_TOKEN")
    kw = {"token": token} if token else {}
    print(f"Loading model {model_id} ...")
    tok = AutoTokenizer.from_pretrained(model_id, **kw)
    mod = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=torch.float16, device_map="cuda", **kw
    )
    mod.eval()
    return mod, tok


# ------------------------------------------------------------------ #
# Candidate-tag selection (shared across scripts)
# ------------------------------------------------------------------ #
def select_tags(article, stage_name, ground_truth, rng):
    correct_tags = article.get("mesh_tags", [])
    if not correct_tags:
        return None, None
    if ground_truth == "Yes":
        candidate = rng.choice(correct_tags)
        assigned = [t for t in correct_tags if t != candidate]
    elif stage_name == "Round 2: Unrelated Tag":
        candidate = article.get("unrelated_negative_test_tag",
                                article.get("negative_test_tag", "Unknown"))
        assigned = correct_tags
    else:
        candidate = article.get("similar_negative_test_tag", "Unknown")
        assigned = correct_tags
    return candidate, assigned


STAGES = [
    ("Round 1: True Tag", "Yes"),
    ("Round 2: Unrelated Tag", "No"),
    ("Round 3: Similar Tag", "No"),
]
