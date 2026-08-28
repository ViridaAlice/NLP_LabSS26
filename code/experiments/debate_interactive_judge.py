"""
Interactive 3-turn debate, judged FAIRLY in both speaking orders.

FAST / REUSE VARIANT
--------------------
This version avoids regenerating the expensive ABA debate. Instead it:

  * ABA order:
        - REUSES the AI-debater turns verbatim from a prior results file
          (a_turn1 -> A opening, b_turn1 -> B rebuttal, a_turn2 -> A closing).
        - REGENERATES the judge verdict fresh on those reused turns.
  * BAB order:
        - FULLY REGENERATES the debate (B opens -> A rebuts -> B closes).
        - REGENERATES the judge verdict fresh.

Role casting is taken from the prior file's "pro_first":
        pro_first == True  -> A argues PRO   (a_is_pro = True)
        pro_first == False -> A argues CON   (a_is_pro = False)
A KEEPS its side in BAB. So if A is PRO, BAB is:
        B(CON) opens -> A(PRO) rebuts -> B(CON) closes.

If a (stage, pmid) is not present in the prior file, the ABA debate is
generated from scratch as a fallback (so no record is silently dropped).

Issue #1: forced-valid outputs everywhere (+ logprob fallback -> no 'Unknown').
Issue #4: judge-decision log-probabilities stored for both debates.
Issue #6: crash-proof, resumable, chunkable. Nothing already written to the
          output chunk files is overwritten or deleted; the run continues where
          it left off via U.load_checkpoint + atomic saves.

Output: interactive_results_*.json  (same names/schema as the original script)
"""

import os
import sys
import random
import argparse

import torch

import debate_utils as U

JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
DEBATER_MODEL_ID = "./Qwen3.5-2B"
DATASET_PATH = "pubmed_xmlc_dataset.json"
MANUAL_PATH = "NLM_Indexing_manual.txt"
PRIOR_RESULTS_DEFAULT = "pydantic_interactive_results_full.json"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--test_mode", action="store_true")
    p.add_argument("--chunk_id", type=int, default=0)
    p.add_argument("--total_chunks", type=int, default=1)
    p.add_argument("--prior_results", type=str, default=PRIOR_RESULTS_DEFAULT,
                   help="Prior interactive results file supplying the ABA debater turns.")
    return p.parse_args()


# ------------------------------------------------------------------ #
# Prompt builders (identical to the original script)
# ------------------------------------------------------------------ #
def debater_system(side):
    return (
        f"You are an expert medical debater. Persuade the judge that the tag "
        f"{'BELONGS' if side == 'PRO' else 'DOES NOT BELONG'}.\n"
        "CRITICAL RULE: NEVER concede. Defend your position and critique your opponent.\n"
        "CRITICAL INSTRUCTION: Output ONLY a valid JSON object with 'thinking' FIRST "
        "and 'argument' (under 150 words) AT THE END.\n\n"
        'REQUIRED JSON SCHEMA:\n{\n  "thinking": "Brief strategy.",\n  "argument": "Your argument."\n}'
    )


def debater_messages(abstract, candidate_tag, side, task):
    user = f"Abstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\n{task}"
    return [{"role": "system", "content": debater_system(side)},
            {"role": "user", "content": user}]


def judge_messages(abstract, candidate_tag, ordered_turns):
    """ordered_turns: list of (speaker_label, role_label, text) in speaking order."""
    system_prompt = (
        "You are an impartial expert judge in a medical debate evaluating whether a "
        "candidate tag belongs to an abstract. You do NOT know which debater argues "
        "for or against; judge only on argument quality and the abstract.\n"
        "CRITICAL INSTRUCTION: Output ONLY a valid JSON object with 'thinking' FIRST "
        "(under 180 words) and 'answer' AT THE END.\n\n"
        'REQUIRED JSON SCHEMA:\n{\n  "thinking": "...",\n  "answer": "Yes" or "No"\n}'
    )
    transcript = "\n\n".join(
        f"Debater {spk} ({role}): {txt}" for spk, role, txt in ordered_turns
    )
    user = (f"Abstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\n"
            f"{transcript}\n\nDoes the tag belong?")
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user}]


def run_three_turn(abstract, candidate, first, second, first_side, second_side, dmod, dtok):
    """first opens, second rebuts, first closes. Returns (open, rebut, close)."""
    t_open, _ = U.generate_argument(
        debater_messages(abstract, candidate, first_side,
                         f"You are Debater {first}. Write your opening statement."),
        dmod, dtok, max_new_tokens=300)
    t_rebut, _ = U.generate_argument(
        debater_messages(abstract, candidate, second_side,
                         f"Debater {first} stated:\n\"{t_open}\"\n"
                         f"You are Debater {second}. Rebut and critique."),
        dmod, dtok, max_new_tokens=300)
    t_close, _ = U.generate_argument(
        debater_messages(abstract, candidate, first_side,
                         f"Your opening: \"{t_open}\"\nDebater {second} responded: "
                         f"\"{t_rebut}\"\nYou are Debater {first}. Write your final rebuttal."),
        dmod, dtok, max_new_tokens=300)
    return t_open, t_rebut, t_close


def judge_one(abstract, candidate, ordered_turns, ground_truth, jmod, jtok):
    msgs = judge_messages(abstract, candidate, ordered_turns)
    ans, raw, need_fb = U.generate_judge_answer(msgs, jmod, jtok, max_new_tokens=768)
    conf = U.decision_confidence(msgs, jmod, jtok, include_debater=True)
    if ans is None:
        ans = U.verdict_from_confidence(conf)
    return {
        "prediction": ans,
        "is_correct": ans == ground_truth,
        "needed_fallback": need_fb,
        "confidence": conf,
        "judge_output": raw,
    }


# ------------------------------------------------------------------ #
# Prior-results lookup
# ------------------------------------------------------------------ #
def build_prior_lookup(prior_path):
    """Return {(stage, pmid): record} from the prior interactive results file."""
    lookup = {}
    if not os.path.exists(prior_path):
        print(f"[WARN] prior results '{prior_path}' not found; ABA will be regenerated.")
        return lookup
    prior = U.load_json(prior_path)
    for r in prior.get("results", []):
        key = (r.get("stage"), str(r.get("pmid")))
        lookup[key] = r
    print(f"[PRIOR] loaded {len(lookup)} ABA records from {prior_path}")
    return lookup


def reuse_aba_turns(prior_rec):
    """Map prior ABA fields -> (a_open, b_rebut, a_close). Returns None if incomplete."""
    a_open = prior_rec.get("a_turn1")
    b_rebut = prior_rec.get("b_turn1")
    a_close = prior_rec.get("a_turn2")
    if a_open and b_rebut and a_close:
        return a_open, b_rebut, a_close
    return None


def main():
    args = parse_args()
    U.setup_threads()
    rng = random.Random(42 + args.chunk_id)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: No GPU!")

    dataset = U.load_json(DATASET_PATH)
    manual_text = U.load_manual(MANUAL_PATH)
    prior_lookup = build_prior_lookup(args.prior_results)

    base = "interactive_results"
    if args.total_chunks > 1:
        cs = (len(dataset) + args.total_chunks - 1) // args.total_chunks
        s, e = args.chunk_id * cs, min((args.chunk_id + 1) * cs, len(dataset))
        dataset = dataset[s:e]
        output_file = f"{base}_chunk{args.chunk_id}.json"
    else:
        output_file = f"{base}_full.json"
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file

    # Resume: fast-forward past everything already written; never overwrite it.
    results, done = U.load_checkpoint(output_file)
    dmod, dtok = U.load_model(DEBATER_MODEL_ID)
    jmod, jtok = U.load_model(JUDGE_MODEL_ID)

    reused_ct = 0
    regen_aba_ct = 0

    for stage_name, ground_truth in U.STAGES:
        print("\n" + "=" * 60 + f"\n{stage_name}\n" + "=" * 60)
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in done:
                continue

            prior_rec = prior_lookup.get((stage_name, str(pmid)))

            # --- Determine candidate tag, ground truth, and role casting ---
            if prior_rec is not None:
                # Reuse the exact conditions the prior debate was run under.
                candidate = prior_rec.get("candidate_tag")
                gt = prior_rec.get("ground_truth", ground_truth)
                a_is_pro = bool(prior_rec.get("pro_first", True))
                assigned = prior_rec.get("assigned_tags")
            else:
                candidate, assigned = U.select_tags(article, stage_name, ground_truth, rng)
                gt = ground_truth
                a_is_pro = rng.choice([True, False])

            if candidate is None:
                continue

            abstract = article.get("abstract", "")
            if not abstract and prior_rec is not None:
                abstract = prior_rec.get("abstract", "")

            a_side = "PRO" if a_is_pro else "CON"
            b_side = "CON" if a_is_pro else "PRO"

            # ---- ABA debate: reuse debater turns if available, else regenerate ----
            reused = reuse_aba_turns(prior_rec) if prior_rec is not None else None
            if reused is not None:
                a_open, b_rebut, a_close = reused
                aba_source = "reused"
                reused_ct += 1
            else:
                a_open, b_rebut, a_close = run_three_turn(
                    abstract, candidate, "A", "B", a_side, b_side, dmod, dtok)
                aba_source = "regenerated"
                regen_aba_ct += 1

            aba_turns = [("A", "opening", a_open),
                         ("B", "rebuttal", b_rebut),
                         ("A", "closing", a_close)]
            # Judge verdict is ALWAYS regenerated fresh for ABA.
            judge_aba = judge_one(abstract, candidate, aba_turns, gt, jmod, jtok)

            # ---- BAB debate (fully regenerated): B opens, A rebuts, B closes ----
            # A keeps its side; only the speaking order changes.
            b_open, a_rebut, b_close = run_three_turn(
                abstract, candidate, "B", "A", b_side, a_side, dmod, dtok)
            bab_turns = [("B", "opening", b_open),
                         ("A", "rebuttal", a_rebut),
                         ("B", "closing", b_close)]
            judge_bab = judge_one(abstract, candidate, bab_turns, gt, jmod, jtok)

            order_flip = judge_aba["prediction"] != judge_bab["prediction"]
            print(f"[{i+1}/{len(dataset)}] {pmid} | tgt {gt:3s} | ABA({aba_source})="
                  f"{judge_aba['prediction']:3s} BAB={judge_bab['prediction']:3s} "
                  f"| flip={order_flip}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate,
                "assigned_tags": assigned, "ground_truth": gt,
                "abstract": abstract,
                "a_is_pro": a_is_pro, "a_side": a_side, "b_side": b_side,
                "aba_source": aba_source,
                "debate_ABA": {"order": "ABA", "a_opening": a_open,
                               "b_rebuttal": b_rebut, "a_closing": a_close},
                "debate_BAB": {"order": "BAB", "b_opening": b_open,
                               "a_rebuttal": a_rebut, "b_closing": b_close},
                "judge_ABA": judge_aba,
                "judge_BAB": judge_bab,
                "order_flip": order_flip,
            })
            done.add((stage_name, pmid))
            total = len(results)
            acc_aba = sum(1 for r in results if r["judge_ABA"]["is_correct"]) / total * 100
            acc_bab = sum(1 for r in results if r["judge_BAB"]["is_correct"]) / total * 100
            flips = sum(1 for r in results if r["order_flip"]) / total * 100
            U.save_results_atomically(output_file, {
                "metadata": {"accuracy_ABA": acc_aba, "accuracy_BAB": acc_bab,
                             "order_flip_rate": flips,
                             "aba_reused": reused_ct, "aba_regenerated": regen_aba_ct},
                "results": results,
            })

    print("\n==== INTERACTIVE COMPLETE ====")
    print(f"ABA reused: {reused_ct} | ABA regenerated (fallback): {regen_aba_ct}\n")


if __name__ == "__main__":
    main()
