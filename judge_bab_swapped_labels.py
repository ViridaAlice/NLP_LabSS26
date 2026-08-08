#!/usr/bin/env python3
"""
Re-judge the already-generated BAB debates after swapping only speaker labels.

Source transcript (already present in interactive_results_full.json):
    B: b_opening -> A: a_rebuttal -> B: b_closing

Transcript shown to the new judge:
    A: b_opening -> B: a_rebuttal -> A: b_closing

No debater text is generated or modified. Only the judge is run again.
The source file is read-only, and all outputs use a new filename prefix.

The script checkpoints atomically after every judged record. Re-running the same
command resumes from the first unfinished record. Chunk outputs are merged into
one full file automatically once every chunk is complete.
"""

import argparse
import fcntl
import os
import signal
import sys
import time
from typing import Any, Dict, List, Sequence, Tuple

import torch

import debate_utils as U


JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
INPUT_RESULTS_DEFAULT = "interactive_results_full.json"
OUTPUT_PREFIX_DEFAULT = "interactive_results_BAB_swapped_labels"

STOP_REQUESTED = False


def request_stop(signum, _frame):
    """Ask the main loop to stop safely after the current record is saved."""
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"\n[SIGNAL] Received signal {signum}; stopping after the current checkpoint.",
          flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Judge reused BAB content after swapping displayed A/B labels."
    )
    parser.add_argument("--input_results", default=INPUT_RESULTS_DEFAULT)
    parser.add_argument("--output_prefix", default=OUTPUT_PREFIX_DEFAULT)
    parser.add_argument("--chunk_id", type=int, default=0)
    parser.add_argument("--total_chunks", type=int, default=1)
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument(
        "--max_runtime_minutes",
        type=float,
        default=0.0,
        help="Stop cleanly before the Slurm limit. Zero disables this guard.",
    )
    parser.add_argument(
        "--max_retries",
        type=int,
        default=1,
        help="Retries for a failed judge call before exiting without marking it done.",
    )
    parser.add_argument(
        "--merge_when_complete",
        action="store_true",
        help="Create <prefix>_full.json once all chunk files are complete.",
    )
    return parser.parse_args()


def normalize_prefix(prefix: str) -> str:
    return prefix[:-5] if prefix.endswith(".json") else prefix


def output_path(prefix: str, chunk_id: int, total_chunks: int,
                test_mode: bool = False) -> str:
    if total_chunks > 1:
        path = f"{prefix}_chunk{chunk_id}.json"
    else:
        path = f"{prefix}_full.json"
    if test_mode:
        directory, name = os.path.split(path)
        path = os.path.join(directory, "test_" + name)
    return path


def judge_messages(abstract: str, candidate_tag: str,
                   ordered_turns: Sequence[Tuple[str, str, str]]):
    """Build the same judge prompt used by debate_interactive_judge.py."""
    system_prompt = (
        "You are an impartial expert judge in a medical debate evaluating whether a "
        "candidate tag belongs to an abstract. You do NOT know which debater argues "
        "for or against; judge only on argument quality and the abstract.\n"
        "CRITICAL INSTRUCTION: Output ONLY a valid JSON object with 'thinking' FIRST "
        "(under 180 words) and 'answer' AT THE END.\n\n"
        "REQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"...\",\n  \"answer\": \"Yes\" or \"No\"\n}"
    )
    transcript = "\n\n".join(
        f"Debater {speaker} ({turn_role}): {text}"
        for speaker, turn_role, text in ordered_turns
    )
    user_prompt = (
        f"Abstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\n"
        f"{transcript}\n\nDoes the tag belong?"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def judge_one(abstract: str, candidate: str,
              ordered_turns: Sequence[Tuple[str, str, str]],
              ground_truth: str, judge_model, judge_tokenizer) -> Dict[str, Any]:
    messages = judge_messages(abstract, candidate, ordered_turns)
    answer, raw, needed_fallback = U.generate_judge_answer(
        messages, judge_model, judge_tokenizer, max_new_tokens=768
    )
    confidence = U.decision_confidence(
        messages, judge_model, judge_tokenizer, include_debater=True
    )
    if answer is None:
        answer = U.verdict_from_confidence(confidence)
    return {
        "prediction": answer,
        "is_correct": answer == ground_truth,
        "needed_fallback": needed_fallback,
        "confidence": confidence,
        "judge_output": raw,
    }


def judge_with_retries(*args, max_retries: int, **kwargs) -> Dict[str, Any]:
    """Retry transient failures without ever marking a failed record complete."""
    attempts = max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return judge_one(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            print(f"[ERROR] Judge attempt {attempt}/{attempts} failed: {exc}",
                  file=sys.stderr, flush=True)
            if attempt >= attempts:
                raise
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            time.sleep(5)
    raise RuntimeError("Unreachable retry state")


def record_key(record: Dict[str, Any]) -> Tuple[str, str]:
    return str(record.get("stage")), str(record.get("pmid"))


def load_checkpoint(path: str) -> Tuple[List[Dict[str, Any]], set, Dict[str, Any]]:
    if not os.path.exists(path):
        return [], set(), {}
    payload = U.load_json(path)
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise ValueError(f"Checkpoint {path} has no valid 'results' list.")
    done = {record_key(record) for record in results}
    print(f"[RESUME] Loaded {len(results)} completed records from {path}")
    return results, done, payload.get("metadata", {})


def validate_checkpoint(metadata: Dict[str, Any], input_path: str,
                        source_count: int, chunk_id: int,
                        total_chunks: int) -> None:
    if not metadata:
        return
    expected_source = os.path.abspath(input_path)
    recorded_source = metadata.get("source_results")
    if recorded_source and os.path.abspath(recorded_source) != expected_source:
        raise ValueError(
            "Refusing to resume: checkpoint was created from a different source file."
        )
    checks = {
        "source_total_records": source_count,
        "chunk_id": chunk_id,
        "total_chunks": total_chunks,
    }
    for field, expected in checks.items():
        actual = metadata.get(field)
        if actual is not None and actual != expected:
            raise ValueError(
                f"Refusing to resume: checkpoint {field}={actual!r}, "
                f"but this run expects {expected!r}."
            )


def percent(numerator: int, denominator: int) -> float:
    return (100.0 * numerator / denominator) if denominator else 0.0


def build_metadata(results: List[Dict[str, Any]], input_path: str,
                   source_count: int, chunk_id: int, total_chunks: int,
                   chunk_start: int, chunk_end: int,
                   expected_chunk_records: int) -> Dict[str, Any]:
    completed = len(results)
    correct = sum(
        1 for record in results
        if record.get("judge_BAB_swapped_labels", {}).get("is_correct") is True
    )
    comparable = [
        record for record in results
        if record.get("judge_BAB", {}).get("prediction") in {"Yes", "No"}
        and record.get("judge_BAB_swapped_labels", {}).get("prediction") in {"Yes", "No"}
    ]
    flips = sum(
        1 for record in comparable
        if record["judge_BAB"]["prediction"]
        != record["judge_BAB_swapped_labels"]["prediction"]
    )
    return {
        "experiment": "BAB content presented with A/B speaker labels swapped",
        "source_results": os.path.abspath(input_path),
        "judge_model": JUDGE_MODEL_ID,
        "debater_generation_performed": False,
        "source_debate_reused": "debate_BAB",
        "presentation": "A: original B opening; B: original A rebuttal; A: original B closing",
        "source_total_records": source_count,
        "chunk_id": chunk_id,
        "total_chunks": total_chunks,
        "chunk_source_start": chunk_start,
        "chunk_source_end_exclusive": chunk_end,
        "expected_chunk_records": expected_chunk_records,
        "completed_records": completed,
        "complete": completed == expected_chunk_records,
        "accuracy_BAB_swapped_labels": percent(correct, completed),
        "prediction_flip_rate_vs_original_BAB": percent(flips, len(comparable)),
        "comparable_with_original_BAB": len(comparable),
    }


def require_bab_turns(record: Dict[str, Any]) -> Tuple[str, str, str]:
    debate = record.get("debate_BAB")
    if not isinstance(debate, dict):
        raise ValueError("Missing 'debate_BAB' object")
    fields = ("b_opening", "a_rebuttal", "b_closing")
    values = tuple(debate.get(field) for field in fields)
    missing = [field for field, value in zip(fields, values) if not value]
    if missing:
        raise ValueError(f"Incomplete debate_BAB; missing {', '.join(missing)}")
    return values  # type: ignore[return-value]


def make_output_record(source_record: Dict[str, Any], source_index: int,
                       new_judgment: Dict[str, Any], b_opening: str,
                       a_rebuttal: str, b_closing: str) -> Dict[str, Any]:
    """Keep the source record intact and add clearly named experimental fields."""
    output_record = dict(source_record)
    original_prediction = source_record.get("judge_BAB", {}).get("prediction")

    output_record["_source_record_index"] = source_index
    output_record["presented_label_mapping"] = {
        "A": "original Debater B",
        "B": "original Debater A",
    }
    output_record["presented_a_side"] = source_record.get("b_side")
    output_record["presented_b_side"] = source_record.get("a_side")
    output_record["presented_a_is_pro"] = source_record.get("b_side") == "PRO"
    output_record["debate_BAB_swapped_labels"] = {
        "source_order": "BAB",
        "presented_order": "ABA",
        "content_changed": False,
        "a_opening": b_opening,
        "b_rebuttal": a_rebuttal,
        "a_closing": b_closing,
    }
    output_record["judge_BAB_swapped_labels"] = new_judgment
    output_record["label_swap_flip_vs_original_BAB"] = (
        original_prediction in {"Yes", "No"}
        and new_judgment.get("prediction") in {"Yes", "No"}
        and original_prediction != new_judgment.get("prediction")
    )
    return output_record


def attempt_merge(prefix: str, input_path: str, total_chunks: int,
                  expected_total: int) -> None:
    """Merge all complete chunks once, guarded by a non-blocking file lock."""
    if total_chunks <= 1:
        return

    lock_path = f"{prefix}_merge.lock"
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[MERGE] Another task is checking/merging the chunks.")
            return

        chunk_payloads = []
        chunk_paths = [
            output_path(prefix, chunk_id, total_chunks)
            for chunk_id in range(total_chunks)
        ]
        for chunk_id, path in enumerate(chunk_paths):
            if not os.path.exists(path):
                print(f"[MERGE] Waiting for {path}")
                return
            payload = U.load_json(path)
            metadata = payload.get("metadata", {})
            if not metadata.get("complete"):
                print(f"[MERGE] Waiting for incomplete chunk {chunk_id}")
                return
            if metadata.get("chunk_id") != chunk_id or metadata.get("total_chunks") != total_chunks:
                raise ValueError(f"Chunk metadata mismatch in {path}")
            chunk_payloads.append(payload)

        merged_results = [
            record
            for payload in chunk_payloads
            for record in payload.get("results", [])
        ]
        merged_results.sort(key=lambda record: record.get("_source_record_index", -1))

        indices = [record.get("_source_record_index") for record in merged_results]
        if len(merged_results) != expected_total or indices != list(range(expected_total)):
            raise ValueError(
                "Refusing to merge: chunk records do not exactly cover the source file."
            )

        metadata = build_metadata(
            merged_results,
            input_path=input_path,
            source_count=expected_total,
            chunk_id=0,
            total_chunks=1,
            chunk_start=0,
            chunk_end=expected_total,
            expected_chunk_records=expected_total,
        )
        metadata.update({
            "merged_from": [os.path.basename(path) for path in chunk_paths],
            "merged_records": len(merged_results),
            "complete": True,
        })
        merged_path = f"{prefix}_full.json"
        if os.path.abspath(merged_path) == os.path.abspath(input_path):
            raise ValueError("Merged output path would overwrite the source file.")
        U.save_results_atomically(
            merged_path, {"metadata": metadata, "results": merged_results}
        )
        print(f"[MERGE] Wrote complete merged output: {merged_path}")


def main():
    global STOP_REQUESTED
    args = parse_args()
    prefix = normalize_prefix(args.output_prefix)

    if args.total_chunks < 1:
        sys.exit("--total_chunks must be at least 1")
    if not 0 <= args.chunk_id < args.total_chunks:
        sys.exit("--chunk_id must satisfy 0 <= chunk_id < total_chunks")
    if args.test_mode and args.merge_when_complete:
        sys.exit("Do not combine --test_mode with --merge_when_complete")
    if not os.path.exists(args.input_results):
        sys.exit(f"Input results file not found: {args.input_results}")
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: No GPU available")

    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, request_stop)

    U.setup_threads()
    started_at = time.monotonic()

    source_payload = U.load_json(args.input_results)
    source_records = source_payload.get("results")
    if not isinstance(source_records, list):
        sys.exit("Input JSON has no valid top-level 'results' list")
    source_count = len(source_records)

    chunk_size = (source_count + args.total_chunks - 1) // args.total_chunks
    chunk_start = args.chunk_id * chunk_size
    chunk_end = min((args.chunk_id + 1) * chunk_size, source_count)
    indexed_chunk = list(enumerate(source_records[chunk_start:chunk_end], start=chunk_start))
    if args.test_mode:
        indexed_chunk = indexed_chunk[:5]
        chunk_end = chunk_start + len(indexed_chunk)

    out_path = output_path(prefix, args.chunk_id, args.total_chunks, args.test_mode)
    if os.path.abspath(out_path) == os.path.abspath(args.input_results):
        sys.exit("Refusing to overwrite the source results file")

    expected_chunk_records = len(indexed_chunk)
    results, done, old_metadata = load_checkpoint(out_path)
    validate_checkpoint(
        old_metadata, args.input_results, source_count,
        args.chunk_id, args.total_chunks
    )
    if len(results) > expected_chunk_records:
        sys.exit("Checkpoint contains more records than this chunk should contain")

    print(f"[SOURCE] {args.input_results}: {source_count} records")
    print(f"[CHUNK] {args.chunk_id}/{args.total_chunks - 1}: source indices "
          f"{chunk_start}:{chunk_end}, {expected_chunk_records} records")
    print(f"[OUTPUT] {out_path}")
    print("[MODE] Reusing BAB text verbatim; generating judge output only.")

    judge_model, judge_tokenizer = U.load_model(JUDGE_MODEL_ID)

    for local_number, (source_index, source_record) in enumerate(indexed_chunk, start=1):
        key = record_key(source_record)
        if key in done:
            continue

        if STOP_REQUESTED:
            print("[STOP] Safe stop requested before next record.")
            break
        if args.max_runtime_minutes > 0:
            elapsed_minutes = (time.monotonic() - started_at) / 60.0
            if elapsed_minutes >= args.max_runtime_minutes:
                print(f"[STOP] Runtime guard reached at {elapsed_minutes:.1f} minutes. "
                      "Re-submit the same job to resume.")
                break

        pmid = source_record.get("pmid")
        stage = source_record.get("stage")
        candidate = source_record.get("candidate_tag")
        abstract = source_record.get("abstract", "")
        ground_truth = source_record.get("ground_truth")

        if not stage or pmid is None or not candidate or not abstract:
            raise ValueError(
                f"Source record index {source_index} lacks stage, pmid, candidate_tag, or abstract"
            )
        if ground_truth not in {"Yes", "No"}:
            raise ValueError(
                f"Source record index {source_index} has invalid ground_truth={ground_truth!r}"
            )

        try:
            b_opening, a_rebuttal, b_closing = require_bab_turns(source_record)
        except ValueError as exc:
            raise ValueError(
                f"Cannot reuse BAB debate for source index {source_index}, "
                f"stage={stage!r}, pmid={pmid!r}: {exc}"
            ) from exc

        # Only labels change. The three text strings remain byte-for-byte identical.
        presented_turns = [
            ("A", "opening", b_opening),
            ("B", "rebuttal", a_rebuttal),
            ("A", "closing", b_closing),
        ]
        new_judgment = judge_with_retries(
            abstract,
            candidate,
            presented_turns,
            ground_truth,
            judge_model,
            judge_tokenizer,
            max_retries=args.max_retries,
        )
        output_record = make_output_record(
            source_record,
            source_index,
            new_judgment,
            b_opening,
            a_rebuttal,
            b_closing,
        )
        results.append(output_record)
        done.add(key)

        metadata = build_metadata(
            results,
            input_path=args.input_results,
            source_count=source_count,
            chunk_id=args.chunk_id,
            total_chunks=args.total_chunks,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            expected_chunk_records=expected_chunk_records,
        )
        U.save_results_atomically(
            out_path, {"metadata": metadata, "results": results}
        )

        old_prediction = source_record.get("judge_BAB", {}).get("prediction", "N/A")
        new_prediction = new_judgment.get("prediction", "N/A")
        print(
            f"[{local_number}/{expected_chunk_records}] index={source_index} "
            f"pmid={pmid} | original BAB={old_prediction} | "
            f"swapped labels={new_prediction} | "
            f"flip={old_prediction != new_prediction}",
            flush=True,
        )

    # Refresh metadata even when this was an already-complete resumed chunk.
    final_metadata = build_metadata(
        results,
        input_path=args.input_results,
        source_count=source_count,
        chunk_id=args.chunk_id,
        total_chunks=args.total_chunks,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        expected_chunk_records=expected_chunk_records,
    )
    U.save_results_atomically(
        out_path, {"metadata": final_metadata, "results": results}
    )

    if final_metadata["complete"]:
        print(f"[COMPLETE] Chunk {args.chunk_id} finished: {len(results)} records.")
    else:
        print(f"[PARTIAL] Chunk {args.chunk_id}: {len(results)}/"
              f"{expected_chunk_records}. Re-submit to resume.")

    if args.merge_when_complete and final_metadata["complete"]:
        attempt_merge(prefix, args.input_results, args.total_chunks, source_count)


if __name__ == "__main__":
    main()
