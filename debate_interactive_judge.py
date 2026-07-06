"""
Interactive 3-turn debate, judged FAIRLY in both speaking orders.

Issue #2:
  * Pro/Con is fixed to A/B once per article and stays fixed.
  * Two full, INDEPENDENT debates are generated & judged separately:
        ABA : A opens  -> B rebuts -> A closes    (judge reset)
        BAB : B opens  -> A rebuts -> B closes    (judge reset)
  * We record whether the judge decision flips with speaking order (order_flip)
    and store the FULL history of both debates for later analysis.
Issue #1: forced-valid outputs everywhere (+ logprob fallback -> no 'Unknown').
Issue #4: judge-decision log-probabilities stored for both debates.
Issue #6: crash-proof, resumable, chunkable.

Output: interactive_results_*.json
Stores abstract + transcripts so the judge can be re-run later (issue #3).
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


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--test_mode", action="store_true")
    p.add_argument("--chunk_id", type=int, default=0)
    p.add_argument("--total_chunks", type=int, default=1)
    return p.parse_args()


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


def main():
    args = parse_args()
    U.setup_threads()
    rng = random.Random(42 + args.chunk_id)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: No GPU!")

    dataset = U.load_json(DATASET_PATH)
    manual_text = U.load_manual(MANUAL_PATH)

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

    results, done = U.load_checkpoint(output_file)
    dmod, dtok = U.load_model(DEBATER_MODEL_ID)
    jmod, jtok = U.load_model(JUDGE_MODEL_ID)

    for stage_name, ground_truth in U.STAGES:
        print("\n" + "=" * 60 + f"\n{stage_name}\n" + "=" * 60)
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in done:
                continue
            candidate, assigned = U.select_tags(article, stage_name, ground_truth, rng)
            if candidate is None:
                continue
            abstract = article.get("abstract", "")

            # Fix Pro/Con to A/B once; stays fixed for BOTH orderings.
            a_is_pro = rng.choice([True, False])
            a_side = "PRO" if a_is_pro else "CON"
            b_side = "CON" if a_is_pro else "PRO"

            # ---- ABA debate: A opens, B rebuts, A closes ----
            a_open, b_rebut, a_close = run_three_turn(
                abstract, candidate, "A", "B", a_side, b_side, dmod, dtok)
            aba_turns = [("A", "opening", a_open),
                         ("B", "rebuttal", b_rebut),
                         ("A", "closing", a_close)]
            judge_aba = judge_one(abstract, candidate, aba_turns, ground_truth, jmod, jtok)

            # ---- BAB debate (judge reset): B opens, A rebuts, B closes ----
            b_open, a_rebut, b_close = run_three_turn(
                abstract, candidate, "B", "A", b_side, a_side, dmod, dtok)
            bab_turns = [("B", "opening", b_open),
                         ("A", "rebuttal", a_rebut),
                         ("B", "closing", b_close)]
            judge_bab = judge_one(abstract, candidate, bab_turns, ground_truth, jmod, jtok)

            order_flip = judge_aba["prediction"] != judge_bab["prediction"]
            print(f"[{i+1}/{len(dataset)}] {pmid} | tgt {ground_truth:3s} | "
                  f"ABA={judge_aba['prediction']:3s} BAB={judge_bab['prediction']:3s} "
                  f"| flip={order_flip}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate,
                "assigned_tags": assigned, "ground_truth": ground_truth,
                "abstract": abstract,
                "a_is_pro": a_is_pro, "a_side": a_side, "b_side": b_side,
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
                             "order_flip_rate": flips},
                "results": results,
            })

    print("\n==== INTERACTIVE COMPLETE ====\n")


if __name__ == "__main__":
    main()
