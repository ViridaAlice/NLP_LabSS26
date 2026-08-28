"""
Statement round: two debaters each write ONE stance-assigned essay, then the
judge decides. No back-and-forth.

Issue #1: forced-valid output for debaters and judge (+ logprob fallback).
Issue #4: judge-decision log-probabilities stored (Yes/No, true/false, A/B).
Issue #6: crash-proof, resumable, chunkable.

Output: statement_results_*.json
Stores abstract + both arguments so the judge can be re-run later (issue #3).
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


def debater_messages(abstract, candidate_tag, side):
    system_prompt = (
        f"You are an expert medical debater. Persuade the judge that the tag "
        f"{'BELONGS' if side == 'PRO' else 'DOES NOT BELONG'}.\n"
        "CRITICAL RULE: NEVER concede. Always confidently defend your position.\n"
        "CRITICAL INSTRUCTION: Output ONLY a valid JSON object with 'thinking' FIRST "
        "and 'argument' (under 150 words) AT THE END.\n\n"
        'REQUIRED JSON SCHEMA:\n{\n  "thinking": "Brief strategy.",\n  "argument": "Your argument."\n}'
    )
    user_prompt = f"Abstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\nWrite your argument."
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]


def judge_messages(abstract, candidate_tag, arg_a, arg_b):
    system_prompt = (
        "You are an impartial expert judge in a medical debate. Evaluate the abstract, "
        "candidate tag, and the two arguments, then decide whether the tag belongs.\n"
        "CRITICAL INSTRUCTION: Output ONLY a valid JSON object with 'thinking' FIRST "
        "(under 180 words) and 'answer' AT THE END.\n\n"
        'REQUIRED JSON SCHEMA:\n{\n  "thinking": "...",\n  "answer": "Yes" or "No"\n}'
    )
    user_prompt = (
        f"Abstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\n"
        f"Debater A: {arg_a}\n\nDebater B: {arg_b}\n\nDoes the tag belong?"
    )
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]


def main():
    args = parse_args()
    U.setup_threads()
    rng = random.Random(42 + args.chunk_id)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: No GPU!")

    dataset = U.load_json(DATASET_PATH)
    manual_text = U.load_manual(MANUAL_PATH)

    base = "statement_results"
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

            pro_arg, _ = U.generate_argument(
                debater_messages(abstract, candidate, "PRO"), dmod, dtok, max_new_tokens=300)
            con_arg, _ = U.generate_argument(
                debater_messages(abstract, candidate, "CON"), dmod, dtok, max_new_tokens=300)

            pro_is_a = rng.choice([True, False])
            arg_a, arg_b = (pro_arg, con_arg) if pro_is_a else (con_arg, pro_arg)

            msgs = judge_messages(abstract, candidate, arg_a, arg_b)
            ans, raw, need_fb = U.generate_judge_answer(msgs, jmod, jtok, max_new_tokens=768)
            conf = U.decision_confidence(msgs, jmod, jtok, include_debater=True)
            if ans is None:
                ans = U.verdict_from_confidence(conf)

            is_correct = (ans == ground_truth)
            print(f"[{i+1}/{len(dataset)}] {pmid} | tgt {ground_truth:3s} | pred {ans:3s} "
                  f"| p(belongs)={conf['verdict_prob_belongs']:.3f} "
                  f"-> {'OK' if is_correct else 'X'}{' (fb)' if need_fb else ''}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate,
                "assigned_tags": assigned, "ground_truth": ground_truth,
                "abstract": abstract,
                "pro_is_a": pro_is_a,
                "pro_argument": pro_arg, "con_argument": con_arg,
                "arg_a": arg_a, "arg_b": arg_b,
                "prediction": ans, "is_correct": is_correct,
                "needed_fallback": need_fb,
                "confidence": conf, "judge_output": raw,
            })
            done.add((stage_name, pmid))
            total = len(results)
            acc = sum(1 for r in results if r["is_correct"]) / total * 100
            U.save_results_atomically(output_file, {
                "metadata": {"overall_accuracy": acc}, "results": results})

    print("\n==== STATEMENT COMPLETE ====\n")


if __name__ == "__main__":
    main()
