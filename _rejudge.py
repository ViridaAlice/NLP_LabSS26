"""
Re-judge with a LARGER judge model, RECYCLING existing debates (issue 3).

The debaters are NOT re-run. We read an existing statement / interactive results
file (old OR new format), reconstruct the exact judge input from the stored
transcript(s), and run a bigger judge model on it - recording the new decision
and its log-probability confidence (issue 4).

Supported input formats
-----------------------
NEW interactive:  record has debate_ABA/debate_BAB with .transcript
NEW statement:    record has essay_a/essay_b (+ side_a/side_b)
OLD interactive:  record has a_turn1/b_turn1/a_turn2 (+ pro_first)
OLD statement:    record has pro_argument/con_argument (+ pro_first)

Abstracts are looked up from the dataset by pmid (old files did not store them).
Crash-proof: chunking + atomic save + resume (issue 6).
"""
import os
import sys
import torch

import debate_common as dc

DATASET_PATH = "pubmed_xmlc_dataset.json"
DEFAULT_JUDGE = "./Qwen3.5-8B"   # larger judge; override with --judge_model


def _extra(p):
    p.add_argument("--input_file", required=True,
                   help="Existing statement/interactive results JSON to recycle.")
    p.add_argument("--output_file", default=None)
    p.add_argument("--judge_model", default=DEFAULT_JUDGE)


def reconstruct_turnsets(rec):
    """
    Return a dict {condition_name: turns_list} for a record, covering both
    orderings when possible so the larger judge is evaluated fairly too.
    """
    out = {}

    # ---- NEW interactive ----
    if "debate_ABA" in rec and "transcript" in rec["debate_ABA"]:
        out["ABA"] = rec["debate_ABA"]["transcript"]
        if "debate_BAB" in rec and "transcript" in rec["debate_BAB"]:
            out["BAB"] = rec["debate_BAB"]["transcript"]
        return out

    # ---- NEW statement ----
    if "essay_a" in rec and "essay_b" in rec:
        ea, eb = rec["essay_a"], rec["essay_b"]
        out["AB"] = [{"speaker": "Debater A", "role": "Statement", "text": ea},
                     {"speaker": "Debater B", "role": "Statement", "text": eb}]
        out["BA"] = [{"speaker": "Debater B", "role": "Statement", "text": eb},
                     {"speaker": "Debater A", "role": "Statement", "text": ea}]
        return out

    # ---- OLD interactive ----
    if "a_turn1" in rec and "b_turn1" in rec:
        pro_first = rec.get("pro_first", True)
        a1, b1, a2 = rec["a_turn1"], rec["b_turn1"], rec.get("a_turn2", "")
        # Original reading order fed to the judge was: A opening, B rebuttal, A closing.
        out["ABA_recycled"] = [
            {"speaker": "Debater A", "role": "Opening statement", "text": a1},
            {"speaker": "Debater B", "role": "Rebuttal", "text": b1},
            {"speaker": "Debater A", "role": "Closing rebuttal", "text": a2},
        ]
        return out

    # ---- OLD statement ----
    if "pro_argument" in rec and "con_argument" in rec:
        pro_first = rec.get("pro_first", True)
        pro, con = rec["pro_argument"], rec["con_argument"]
        first, second = ((pro, con) if pro_first else (con, pro))
        out["orig"] = [
            {"speaker": "Debater A", "role": "Statement", "text": first},
            {"speaker": "Debater B", "role": "Statement", "text": second},
        ]
        return out

    return out


def main():
    args = dc.parse_args(_extra)
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: no GPU!")

    with open(args.input_file, "r", encoding="utf-8") as f:
        src = json._default_decoder.decode(f.read()) if False else __import__("json").load(f)
    src_results = src.get("results", [])

    # Abstract lookup (old files lack abstracts)
    dataset, _ = dc.load_resources(DATASET_PATH, "NLM_Indexing_manual.txt")
    abstract_by_pmid = {a.get("pmid"): a.get("abstract", "") for a in dataset}

    # Determine output name
    if args.output_file:
        base_out = args.output_file
    else:
        stem = os.path.splitext(os.path.basename(args.input_file))[0]
        base_out = f"rejudge_{stem}"
    if args.total_chunks > 1:
        output_file = f"{base_out}_chunk{args.chunk_id}.json"
        src_results = dc.chunk_dataset(src_results, args.chunk_id, args.total_chunks)
    else:
        output_file = f"{base_out}.json"
    if not output_file.endswith(".json"):
        output_file += ".json"
    if args.test_mode:
        src_results = src_results[:5]
        output_file = "test_" + output_file

    results, done = dc.load_existing(output_file)

    print(f"Loading LARGER judge model {args.judge_model}...")
    jud_mod, jud_tok = dc.load_model(args.judge_model)

    for i, rec in enumerate(src_results):
        pmid = rec.get("pmid", "Unknown")
        stage = rec.get("stage", "Unknown")
        if (stage, pmid) in done:
            continue

        candidate_tag = rec.get("candidate_tag", "Unknown")
        ground_truth = rec.get("ground_truth", "Unknown")
        abstract = rec.get("abstract") or abstract_by_pmid.get(pmid, "")

        turnsets = reconstruct_turnsets(rec)
        if not turnsets:
            continue

        conditions = {}
        for cond, turns in turnsets.items():
            msgs = dc.build_judge_transcript_messages(abstract, candidate_tag, turns)
            jr = dc.run_judge(jud_mod, jud_tok, msgs, include_debater_probe=True)
            conditions[cond] = {
                "prediction": jr["answer"],
                "is_correct": jr["answer"] == ground_truth,
                "logprob_yes": jr["logprob_yes"], "logprob_no": jr["logprob_no"],
                "prob_belongs": jr["prob_belongs"],
                "logprob_debater_a": jr.get("logprob_debater_a"),
                "logprob_debater_b": jr.get("logprob_debater_b"),
                "prob_debater_a_right": jr.get("prob_debater_a_right"),
                "judge_attempts": jr["judge_attempts"],
                "judge_fallback_used": jr["judge_fallback_used"],
                "judge_output": jr["judge_output"],
            }

        preds = [c["prediction"] for c in conditions.values()]
        order_bias = len(set(preds)) > 1
        primary = conditions[list(conditions.keys())[0]]
        print(f"[{i+1}/{len(src_results)}] PMID {pmid} | GT {ground_truth} | "
              f"{ {k: v['prediction'] for k, v in conditions.items()} } | flip={order_bias}")

        results.append({
            "pmid": pmid, "stage": stage, "candidate_tag": candidate_tag,
            "ground_truth": ground_truth,
            "rejudge_model": args.judge_model,
            "conditions": conditions,
            "order_bias_detected": order_bias,
            "model_prediction": primary["prediction"],
            "is_correct": primary["is_correct"],
        })
        done.add((stage, pmid))

        total = len(results)
        acc = sum(1 for r in results if r["is_correct"]) / total * 100 if total else 0
        dc.save_results_atomically(output_file, {
            "metadata": {"rejudge_model": args.judge_model,
                         "source_file": args.input_file,
                         "overall_accuracy": acc, "n": total},
            "results": results,
        })

    print(f"\nREJUDGE chunk {args.chunk_id} COMPLETE ({args.input_file})\n")


if __name__ == "__main__":
    import json  # local import kept to mirror original style
    main()
