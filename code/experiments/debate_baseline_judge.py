"""
Baseline judge (no debate).

The judge sees the abstract, the already-assigned tags, a candidate tag, and
(optionally) the NLM indexing manual, then decides Yes/No.

Issue #1: valid output is FORCED (re-roll + guaranteed logprob fallback -> no 'Unknown').
Issue #4: judge-decision log-probabilities are stored (two framings).
Issue #5: pass --no_manual to run WITHOUT the MeSH guidelines for comparison.
Issue #6: crash-proof, resumable, chunkable.

Outputs:
  baseline_withmanual_results_*.json   (default)
  baseline_nomanual_results_*.json     (with --no_manual)
"""

import os
import sys
import random
import argparse

import torch

import debate_utils as U

JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
DATASET_PATH = "pubmed_xmlc_dataset.json"
MANUAL_PATH = "NLM_Indexing_manual.txt"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--test_mode", action="store_true")
    p.add_argument("--no_manual", action="store_true",
                   help="Run baseline WITHOUT the MeSH indexing manual (issue #5).")
    p.add_argument("--chunk_id", type=int, default=0)
    p.add_argument("--total_chunks", type=int, default=1)
    return p.parse_args()


def build_judge_messages(abstract, assigned_tags, candidate_tag, manual_text, use_manual):
    system_prompt = (
        "You are an expert judge for a medical indexing task. Decide whether a "
        "candidate Medical Subject Heading (MeSH) tag should be assigned to the article.\n"
        "CRITICAL INSTRUCTION: Output ONLY a valid JSON object. Put the 'thinking' key "
        "FIRST (keep it under 180 words) and the 'answer' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n"
        '{\n  "thinking": "Concise step-by-step analysis.",\n  "answer": "Yes" or "No"\n}'
    )
    manual_block = (
        f"Here is the NLM Indexing manual for your reference:\n"
        f"<indexing_manual>\n{manual_text}\n</indexing_manual>\n\n" if use_manual else ""
    )
    user_prompt = (
        f"{manual_block}"
        f"Abstract: {abstract}\n"
        f"Already Assigned Tags: {', '.join(assigned_tags)}\n"
        f"Candidate Tag: {candidate_tag}\n\n"
        f"Based on the abstract, does the candidate tag belong? Follow the JSON schema exactly."
    )
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]


def main():
    args = parse_args()
    U.setup_threads()
    random.seed(42 + args.chunk_id)
    rng = random.Random(42 + args.chunk_id)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: No GPU!")

    dataset = U.load_json(DATASET_PATH)
    use_manual = not args.no_manual
    manual_text = U.load_manual(MANUAL_PATH) if use_manual else ""

    base = "baseline_withmanual_results" if use_manual else "baseline_nomanual_results"
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
    jmod, jtok = U.load_model(JUDGE_MODEL_ID)

    for stage_name, ground_truth in U.STAGES:
        print("\n" + "=" * 60 + f"\n{stage_name} (manual={use_manual})\n" + "=" * 60)
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in done:
                continue
            candidate, assigned = U.select_tags(article, stage_name, ground_truth, rng)
            if candidate is None:
                continue
            abstract = article.get("abstract", "")

            msgs = build_judge_messages(abstract, assigned, candidate, manual_text, use_manual)
            ans, raw, need_fb = U.generate_judge_answer(msgs, jmod, jtok, max_new_tokens=768)
            conf = U.decision_confidence(msgs, jmod, jtok, include_debater=False)
            if ans is None:
                ans = U.verdict_from_confidence(conf)

            is_correct = (ans == ground_truth)
            print(f"[{i+1}/{len(dataset)}] {pmid} | tgt {ground_truth:3s} | pred {ans:3s} "
                  f"| p(belongs)={conf['verdict_prob_belongs']:.3f} "
                  f"-> {'OK' if is_correct else 'X'}{' (fb)' if need_fb else ''}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate,
                "assigned_tags": assigned, "ground_truth": ground_truth,
                "use_manual": use_manual,
                "prediction": ans, "is_correct": is_correct,
                "needed_fallback": need_fb,
                "confidence": conf, "judge_output": raw,
            })
            done.add((stage_name, pmid))
            total = len(results)
            acc = sum(1 for r in results if r["is_correct"]) / total * 100
            U.save_results_atomically(output_file, {
                "metadata": {"overall_accuracy": acc, "use_manual": use_manual},
                "results": results,
            })

    print("\n==== BASELINE COMPLETE ====\n")


if __name__ == "__main__":
    main()
