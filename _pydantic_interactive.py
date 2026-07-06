"""
Interactive debate round.

Fairness redesign (issue 2):
  For every article we run TWO entirely separate debates with A's stance held
  fixed (A = PRO or A = CON, randomised per article):
     * ABA debate  -> A opens, B rebuts, A closes.  (A speaks first AND last)
     * BAB debate  -> B opens, A rebuts, B closes.  (B speaks first AND last)
  The judge is RESET and run independently on each transcript. This guarantees
  each debater gets the first/last slot exactly once, removing the systematic
  position advantage of the original single-ABA setup.

  We store the full history of both debates and flag whether the judge's
  decision changes between ABA and BAB (order / first-last bias).

Other changes:
  * issue 1: every debater turn and the judge answer are forced valid (re-rolls);
             the judge decision is never "Unknown".
  * issue 4: logprob_yes/no + prob_belongs AND logprob_debater_a/b +
             prob_debater_a_right for each debate.
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
BASE_OUTPUT_PATH = "pydantic_interactive_results"


def run_one_debate(deb_mod, deb_tok, abstract, assigned_tags, candidate_tag,
                   first_label, first_side, second_label, second_side):
    """Three-turn debate: first opens, second rebuts, first closes."""
    t1, _, _ = dc.robust_generate(
        dc.build_debater_messages(abstract, assigned_tags, candidate_tag, first_side,
                                  f"You are {first_label}. Write your opening statement."),
        deb_mod, deb_tok, dc.DebaterResponse, "argument", max_new_tokens=300)

    prev2 = (f"{first_label} opened with:\n\"{t1}\"\n"
             f"You are {second_label}. Rebut and critique the opponent.")
    t2, _, _ = dc.robust_generate(
        dc.build_debater_messages(abstract, assigned_tags, candidate_tag, second_side, prev2),
        deb_mod, deb_tok, dc.DebaterResponse, "argument", max_new_tokens=300)

    prev3 = (f"Your opening:\n\"{t1}\"\n{second_label} responded:\n\"{t2}\"\n"
             f"You are {first_label}. Write your final rebuttal.")
    t3, _, _ = dc.robust_generate(
        dc.build_debater_messages(abstract, assigned_tags, candidate_tag, first_side, prev3),
        deb_mod, deb_tok, dc.DebaterResponse, "argument", max_new_tokens=300)

    turns = [
        {"speaker": first_label, "role": "Opening statement", "text": t1},
        {"speaker": second_label, "role": "Rebuttal", "text": t2},
        {"speaker": first_label, "role": "Closing rebuttal", "text": t3},
    ]
    return turns


def judge_debate(jud_mod, jud_tok, abstract, candidate_tag, turns, ground_truth):
    msgs = dc.build_judge_transcript_messages(abstract, candidate_tag, turns)
    jr = dc.run_judge(jud_mod, jud_tok, msgs, include_debater_probe=True)
    return {
        "transcript": turns,
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

            a_is_pro = rng.random() < 0.5
            side_a = "PRO" if a_is_pro else "CON"
            side_b = "CON" if a_is_pro else "PRO"

            # ---- Two entirely separate debates ----
            turns_aba = run_one_debate(deb_mod, deb_tok, abstract, assigned_tags, candidate_tag,
                                       "Debater A", side_a, "Debater B", side_b)
            turns_bab = run_one_debate(deb_mod, deb_tok, abstract, assigned_tags, candidate_tag,
                                       "Debater B", side_b, "Debater A", side_a)

            # ---- Judge reset and run on each ----
            res_aba = judge_debate(jud_mod, jud_tok, abstract, candidate_tag, turns_aba, ground_truth)
            res_bab = judge_debate(jud_mod, jud_tok, abstract, candidate_tag, turns_bab, ground_truth)

            order_bias = res_aba["prediction"] != res_bab["prediction"]
            print(f"[{i+1}/{len(dataset)}] PMID {pmid} | GT {ground_truth} | "
                  f"ABA={res_aba['prediction']} BAB={res_bab['prediction']} | "
                  f"first/last flip={order_bias}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate_tag,
                "assigned_tags": assigned_tags, "abstract": abstract,
                "ground_truth": ground_truth,
                "a_is_pro": a_is_pro, "side_a": side_a, "side_b": side_b,
                "debate_ABA": res_aba, "debate_BAB": res_bab,
                "order_bias_detected": order_bias,
                "model_prediction": res_aba["prediction"],  # convenience (ABA)
                "is_correct": res_aba["is_correct"],
            })
            done.add((stage_name, pmid))

            total = len(results)
            acc_aba = sum(1 for r in results if r["debate_ABA"]["is_correct"]) / total * 100 if total else 0
            acc_bab = sum(1 for r in results if r["debate_BAB"]["is_correct"]) / total * 100 if total else 0
            flips = sum(1 for r in results if r.get("order_bias_detected"))
            dc.save_results_atomically(output_file, {
                "metadata": {"judge": JUDGE_MODEL_ID, "debater": DEBATER_MODEL_ID,
                             "accuracy_ABA": acc_aba, "accuracy_BAB": acc_bab,
                             "first_last_flips": flips, "n": total},
                "results": results,
            })

    print(f"\nINTERACTIVE chunk {args.chunk_id} COMPLETE\n")


if __name__ == "__main__":
    main()
