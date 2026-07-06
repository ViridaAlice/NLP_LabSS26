"""
Statement round: each debater writes ONE essay for its assigned stance, then the
judge decides.

Changes vs. the original:
  * issue 1: essays and the judge answer are forced to be valid (re-rolls);
             the judge decision is never "Unknown".
  * issue 2 (fairness): the two essays are generated ONCE, then the judge is run
             TWICE on entirely separate contexts - order AB and order BA - with
             the stance of A held fixed. We record whether the decision flips
             (order/position bias) plus the full history.
  * issue 4: logprob_yes/no + prob_belongs AND logprob_debater_a/b +
             prob_debater_a_right for BOTH orderings.
  * issue 6: chunking + atomic save + resume.
"""
import sys
import random
import torch

import debate_common as dc

JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
DEBATER_MODEL_ID = "./Qwen3.5-2B"
DATASET_PATH = "pubmed_xmlc_dataset.json"
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "pydantic_statement_results"


def judge_both_orders(jud_mod, jud_tok, abstract, candidate_tag,
                      essay_a, side_a, essay_b, side_b, ground_truth):
    """Run the (reset) judge on order AB and, separately, on order BA."""
    turns_ab = [
        {"speaker": "Debater A", "role": "Statement", "text": essay_a},
        {"speaker": "Debater B", "role": "Statement", "text": essay_b},
    ]
    turns_ba = [
        {"speaker": "Debater A", "role": "Statement", "text": essay_b},  # spoken 2nd is A? no
        {"speaker": "Debater B", "role": "Statement", "text": essay_a},
    ]
    # NOTE on labelling: A keeps its stance/text; only READING ORDER changes.
    # Order AB -> A speaks first. Order BA -> B speaks first. To keep the A/B
    # identity stable we relabel by position: first speaker is always shown
    # first. We therefore build turns explicitly per order below.
    turns_ab = [
        {"speaker": "Debater A", "role": "Statement", "text": essay_a},
        {"speaker": "Debater B", "role": "Statement", "text": essay_b},
    ]
    turns_ba = [
        {"speaker": "Debater B", "role": "Statement", "text": essay_b},
        {"speaker": "Debater A", "role": "Statement", "text": essay_a},
    ]

    out = {}
    for order_name, turns in (("AB", turns_ab), ("BA", turns_ba)):
        msgs = dc.build_judge_transcript_messages(abstract, candidate_tag, turns)
        jr = dc.run_judge(jud_mod, jud_tok, msgs, include_debater_probe=True)
        out[order_name] = {
            "prediction": jr["answer"],
            "is_correct": jr["answer"] == ground_truth,
            "logprob_yes": jr["logprob_yes"], "logprob_no": jr["logprob_no"],
            "prob_belongs": jr["prob_belongs"],
            "logprob_debater_a": jr["logprob_debater_a"],
            "logprob_debater_b": jr["logprob_debater_b"],
            "prob_debater_a_right": jr["prob_debater_a_right"],
            "judge_attempts": jr["judge_attempts"],
            "judge_fallback_used": jr["judge_fallback_used"],
            "judge_output": jr["judge_output"],
        }
    return out


def main():
    args = dc.parse_args()
    random.seed(42 + args.chunk_id)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: no GPU!")

    dataset, manual_text = dc.load_resources(DATASET_PATH, MANUAL_PATH)
    dataset = dc.chunk_dataset(dataset, args.chunk_id, args.total_chunks)
    output_file = (f"{BASE_OUTPUT_PATH}_chunk{args.chunk_id}.json"
                   if args.total_chunks > 1 else f"{BASE_OUTPUT_PATH}_full.json")
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file

    results, done = dc.load_existing(output_file)

    print(f"Loading debater model {DEBATER_MODEL_ID}...")
    deb_mod, deb_tok = dc.load_model(DEBATER_MODEL_ID)
    print(f"Loading judge model {JUDGE_MODEL_ID}...")
    jud_mod, jud_tok = dc.load_model(JUDGE_MODEL_ID)

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

            # A's stance fixed for this article (both orders), randomised per article.
            a_is_pro = rng.random() < 0.5
            side_a = "PRO" if a_is_pro else "CON"
            side_b = "CON" if a_is_pro else "PRO"

            essay_a, _, _ = dc.robust_generate(
                dc.build_debater_messages(abstract, assigned_tags, candidate_tag, side_a,
                                          "You are Debater A. Write your statement."),
                deb_mod, deb_tok, dc.DebaterResponse, "argument", max_new_tokens=300)
            essay_b, _, _ = dc.robust_generate(
                dc.build_debater_messages(abstract, assigned_tags, candidate_tag, side_b,
                                          "You are Debater B. Write your statement."),
                deb_mod, deb_tok, dc.DebaterResponse, "argument", max_new_tokens=300)

            judged = judge_both_orders(jud_mod, jud_tok, abstract, candidate_tag,
                                       essay_a, side_a, essay_b, side_b, ground_truth)

            order_bias = judged["AB"]["prediction"] != judged["BA"]["prediction"]
            print(f"[{i+1}/{len(dataset)}] PMID {pmid} | GT {ground_truth} | "
                  f"AB={judged['AB']['prediction']} BA={judged['BA']['prediction']} | "
                  f"order_flip={order_bias}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate_tag,
                "assigned_tags": assigned_tags, "abstract": abstract,
                "ground_truth": ground_truth,
                "a_is_pro": a_is_pro, "side_a": side_a, "side_b": side_b,
                "essay_a": essay_a, "essay_b": essay_b,
                "order_AB": judged["AB"], "order_BA": judged["BA"],
                "order_bias_detected": order_bias,
                # convenience top-level fields (AB order) for quick eval
                "model_prediction": judged["AB"]["prediction"],
                "is_correct": judged["AB"]["is_correct"],
            })
            done.add((stage_name, pmid))

            total = len(results)
            acc = sum(1 for r in results if r["is_correct"]) / total * 100 if total else 0
            flips = sum(1 for r in results if r.get("order_bias_detected"))
            dc.save_results_atomically(output_file, {
                "metadata": {"judge": JUDGE_MODEL_ID, "debater": DEBATER_MODEL_ID,
                             "overall_accuracy_AB": acc,
                             "order_flips": flips, "n": total},
                "results": results,
            })

    print(f"\nSTATEMENT chunk {args.chunk_id} COMPLETE\n")


if __name__ == "__main__":
    main()
