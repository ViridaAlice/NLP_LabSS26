"""
Re-judge RECYCLED debates with a LARGER judge (issue #3).

Reads an existing results file produced by the statement or interactive script
and RE-RUNS ONLY THE JUDGE with Qwen3.5-2B (same size as the debaters).
The debaters are NOT re-run -- their stored arguments/transcripts are reused.

Usage:
  python debate_rejudge_large.py --mode interactive --source interactive_results_full.json
  python debate_rejudge_large.py --mode statement  --source statement_results_full.json

Output: <source-stem>_rejudge2B.json
Crash-proof & resumable (issue #6). Log-probs stored (issue #4).
"""

import os
import sys
import argparse

import torch

import debate_utils as U
import debate_statement_judge as ST
import debate_interactive_judge as IN

LARGE_JUDGE_MODEL_ID = "./Qwen3.5-2B"   # larger judge (issue #3)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["statement", "interactive"], required=True)
    p.add_argument("--source", required=True, help="Existing results JSON to recycle.")
    p.add_argument("--test_mode", action="store_true")
    return p.parse_args()


def judge_record_statement(rec, jmod, jtok):
    msgs = ST.judge_messages(rec["abstract"], rec["candidate_tag"],
                             rec["arg_a"], rec["arg_b"])
    ans, raw, need_fb = U.generate_judge_answer(msgs, jmod, jtok, max_new_tokens=768)
    conf = U.decision_confidence(msgs, jmod, jtok, include_debater=True)
    if ans is None:
        ans = U.verdict_from_confidence(conf)
    out = dict(rec)
    out["prediction"] = ans
    out["is_correct"] = ans == rec["ground_truth"]
    out["needed_fallback"] = need_fb
    out["confidence"] = conf
    out["judge_output"] = raw
    out["judge_model"] = LARGE_JUDGE_MODEL_ID
    return out


def judge_record_interactive(rec, jmod, jtok):
    aba = rec["debate_ABA"]
    bab = rec["debate_BAB"]
    aba_turns = [("A", "opening", aba["a_opening"]),
                 ("B", "rebuttal", aba["b_rebuttal"]),
                 ("A", "closing", aba["a_closing"])]
    bab_turns = [("B", "opening", bab["b_opening"]),
                 ("A", "rebuttal", bab["a_rebuttal"]),
                 ("B", "closing", bab["b_closing"])]
    j_aba = IN.judge_one(rec["abstract"], rec["candidate_tag"], aba_turns,
                         rec["ground_truth"], jmod, jtok)
    j_bab = IN.judge_one(rec["abstract"], rec["candidate_tag"], bab_turns,
                         rec["ground_truth"], jmod, jtok)
    out = dict(rec)
    out["judge_ABA"] = j_aba
    out["judge_BAB"] = j_bab
    out["order_flip"] = j_aba["prediction"] != j_bab["prediction"]
    out["judge_model"] = LARGE_JUDGE_MODEL_ID
    return out


def main():
    args = parse_args()
    U.setup_threads()
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: No GPU!")

    src = U.load_json(args.source)
    src_records = src.get("results", [])
    if args.test_mode:
        src_records = src_records[:5]

    stem = os.path.splitext(os.path.basename(args.source))[0]
    output_file = f"{stem}_rejudge2B.json"
    results, done = U.load_checkpoint(output_file)

    jmod, jtok = U.load_model(LARGE_JUDGE_MODEL_ID)

    for i, rec in enumerate(src_records):
        key = (rec.get("stage"), rec.get("pmid"))
        if key in done:
            continue
        if args.mode == "statement":
            new = judge_record_statement(rec, jmod, jtok)
            print(f"[{i+1}/{len(src_records)}] {rec.get('pmid')} | "
                  f"pred {new['prediction']} | {'OK' if new['is_correct'] else 'X'}")
        else:
            new = judge_record_interactive(rec, jmod, jtok)
            print(f"[{i+1}/{len(src_records)}] {rec.get('pmid')} | "
                  f"ABA={new['judge_ABA']['prediction']} "
                  f"BAB={new['judge_BAB']['prediction']} flip={new['order_flip']}")
        results.append(new)
        done.add(key)

        U.save_results_atomically(output_file, {
            "metadata": {"judge_model": LARGE_JUDGE_MODEL_ID,
                         "source_file": args.source, "mode": args.mode},
            "results": results,
        })

    print("\n==== REJUDGE (2B) COMPLETE ====\n")


if __name__ == "__main__":
    main()
