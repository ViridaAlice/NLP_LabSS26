"""
Baseline judge (no debate). The judge sees the abstract, the assigned tags and a
candidate tag and decides Yes/No.

Changes vs. the original:
  * issue 1: schema-valid answer is forced with re-rolls; a log-prob fallback
             guarantees the stored decision is never "Unknown".
  * issue 4: stores logprob_yes / logprob_no / prob_belongs (judge confidence).
  * issue 5: --no_manual flag runs the SAME baseline WITHOUT the MeSH guidelines
             so the two can be compared directly. Output file name reflects it.
  * issue 6: chunking + atomic save + resume for crash-proof cluster runs.
"""
import sys
import random
import torch

import debate_common as dc

MODEL_ID = "./Qwen3.5-0.8B"
DATASET_PATH = "pubmed_xmlc_dataset.json"
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "pydantic_baseline_results"


def _extra(p):
    p.add_argument("--no_manual", action="store_true",
                   help="Run baseline WITHOUT the MeSH indexing manual (issue 5).")


def main():
    args = dc.parse_args(_extra)
    random.seed(42 + args.chunk_id)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: no GPU!")

    include_manual = not args.no_manual
    tag = "nomanual" if args.no_manual else "manual"

    dataset, manual_text = dc.load_resources(DATASET_PATH, MANUAL_PATH)
    dataset = dc.chunk_dataset(dataset, args.chunk_id, args.total_chunks)

    if args.total_chunks > 1:
        output_file = f"{BASE_OUTPUT_PATH}_{tag}_chunk{args.chunk_id}.json"
    else:
        output_file = f"{BASE_OUTPUT_PATH}_{tag}_full.json"
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file

    results, done = dc.load_existing(output_file)

    print(f"Loading judge model {MODEL_ID} (manual={'ON' if include_manual else 'OFF'})...")
    model, tok = dc.load_model(MODEL_ID)

    for stage_name, ground_truth in dc.STAGES:
        print("\n" + "=" * 60 + f"\n{stage_name.upper()}\n" + "=" * 60)
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in done:
                continue
            if not article.get("mesh_tags"):
                continue

            rng = random.Random(hash((pmid, stage_name)) & 0xFFFFFFFF)
            candidate_tag, assigned_tags = dc.pick_case(article, stage_name, ground_truth, rng)
            abstract = article.get("abstract", "")

            messages = dc.build_baseline_messages(
                abstract, assigned_tags, candidate_tag, manual_text, include_manual=include_manual
            )
            jr = dc.run_judge(model, tok, messages, include_debater_probe=False)
            is_correct = (jr["answer"] == ground_truth)
            print(f"[{i+1}/{len(dataset)}] PMID {pmid} | Target {ground_truth:3s} | "
                  f"Pred {jr['answer']:3s} | P(belongs)={jr['prob_belongs']:.3f} -> "
                  f"{'OK' if is_correct else 'X'}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate_tag,
                "assigned_tags": assigned_tags, "abstract": abstract,
                "ground_truth": ground_truth, "manual_used": include_manual,
                "model_prediction": jr["answer"], "is_correct": is_correct,
                "logprob_yes": jr["logprob_yes"], "logprob_no": jr["logprob_no"],
                "prob_belongs": jr["prob_belongs"],
                "judge_attempts": jr["judge_attempts"],
                "judge_fallback_used": jr["judge_fallback_used"],
                "full_model_output": jr["judge_output"],
            })
            done.add((stage_name, pmid))

            total = len(results)
            acc = sum(1 for r in results if r["is_correct"]) / total * 100 if total else 0
            dc.save_results_atomically(output_file, {
                "metadata": {"model": MODEL_ID, "manual_used": include_manual,
                             "overall_accuracy": acc},
                "results": results,
            })

    print(f"\nBASELINE ({tag}) chunk {args.chunk_id} COMPLETE\n")


if __name__ == "__main__":
    main()
