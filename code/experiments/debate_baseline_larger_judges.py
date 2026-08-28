#!/usr/bin/env python3
"""
Re-run the robust no-debate baseline with a larger Qwen3.5 judge.

This script intentionally preserves the previous robust baseline experiment:
  * exact abstract source: pubmed_xmlc_dataset.json
  * exact stage/candidate/assigned-tags/ground-truth inputs: reused from the
    corresponding completed 0.8B baseline result file
  * exact judge prompt, generation helper, confidence helper, fallback, and
    per-record JSON schema from debate_baseline_judge.py

It is checkpointed after every record, validates existing checkpoints before
resuming, stops cleanly before the Slurm time limit, and merges complete chunks
into a full result file automatically.

Full outputs:
  results/baseline_nomanual_results_full_rejudge2B.json
  results/baseline_withmanual_results_full_rejudge2B.json
  results/baseline_nomanual_results_full_rejudge4B.json
  results/baseline_withmanual_results_full_rejudge4B.json
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any

import torch

import debate_utils as U


DATASET_PATH = "pubmed_xmlc_dataset.json"
MANUAL_PATH = "NLM_Indexing_manual.txt"

REQUIRED_REFERENCE_FIELDS = {
    "pmid",
    "stage",
    "candidate_tag",
    "assigned_tags",
    "ground_truth",
    "use_manual",
}

# Keep this identical to the robust 0.8B baseline record schema.
OUTPUT_FIELDS = {
    "pmid",
    "stage",
    "candidate_tag",
    "assigned_tags",
    "ground_truth",
    "use_manual",
    "prediction",
    "is_correct",
    "needed_fallback",
    "confidence",
    "judge_output",
}

STOP_REQUESTED = False


class ValidationError(RuntimeError):
    """Raised rather than silently using an incompatible checkpoint/input."""


def request_stop(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(
        f"\nReceived signal {signum}; finishing the current model call and "
        "stopping at the next safe checkpoint.",
        flush=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resumable 2B/4B rerun of the robust PubMed/MeSH baseline."
    )
    parser.add_argument("--judge-model", required=True,
                        help="Local model directory, e.g. ./Qwen3.5-2B")
    parser.add_argument("--model-label", required=True, choices=("2B", "4B"),
                        help="Label used only in output filenames.")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--with-manual", action="store_true")
    mode.add_argument("--no-manual", action="store_true")

    parser.add_argument("--reference-file", required=True,
                        help="Completed matching 0.8B baseline full-result JSON.")
    parser.add_argument("--dataset-path", default=DATASET_PATH)
    parser.add_argument("--manual-path", default=MANUAL_PATH)
    parser.add_argument("--checkpoint-dir", default="results/checkpoints_larger_baselines")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--chunk-id", type=int, default=0)
    parser.add_argument("--total-chunks", type=int, default=1)
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=55.0,
        help="Stop safely after this many minutes (Slurm limit should be longer).",
    )
    return parser.parse_args()


def build_judge_messages(
    abstract: str,
    assigned_tags: list[str],
    candidate_tag: str,
    manual_text: str,
    use_manual: bool,
) -> list[dict[str, str]]:
    """Exact prompt from debate_baseline_judge.py."""
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
        f"<indexing_manual>\n{manual_text}\n</indexing_manual>\n\n"
        if use_manual
        else ""
    )
    user_prompt = (
        f"{manual_block}"
        f"Abstract: {abstract}\n"
        f"Already Assigned Tags: {', '.join(assigned_tags)}\n"
        f"Candidate Tag: {candidate_tag}\n\n"
        f"Based on the abstract, does the candidate tag belong? Follow the JSON schema exactly."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ValidationError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {path}: {exc}") from exc


def extract_results(payload: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        records = payload["results"]
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValidationError(
            f"{path} must be a result list or an object containing a 'results' list."
        )
    if not all(isinstance(record, dict) for record in records):
        raise ValidationError(f"{path} contains a non-object result record.")
    return records


def record_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("stage", "")),
        str(record.get("pmid", "")),
        str(record.get("candidate_tag", "")),
        str(record.get("ground_truth", "")),
    )


def validate_reference(
    records: list[dict[str, Any]], use_manual: bool, path: Path
) -> None:
    if not records:
        raise ValidationError(f"Reference file has no records: {path}")

    seen: set[tuple[str, str, str, str]] = set()
    for index, record in enumerate(records):
        missing = REQUIRED_REFERENCE_FIELDS - set(record)
        if missing:
            raise ValidationError(
                f"Reference record {index} lacks fields: {sorted(missing)}"
            )
        if record["use_manual"] is not use_manual:
            raise ValidationError(
                f"Reference record {index} has use_manual={record['use_manual']!r}; "
                f"expected {use_manual!r}."
            )
        if record["ground_truth"] not in {"Yes", "No"}:
            raise ValidationError(
                f"Reference record {index} has invalid ground_truth: "
                f"{record['ground_truth']!r}"
            )
        if not isinstance(record["assigned_tags"], list) or not all(
            isinstance(tag, str) for tag in record["assigned_tags"]
        ):
            raise ValidationError(
                f"Reference record {index} has invalid assigned_tags."
            )
        key = record_key(record)
        if key in seen:
            raise ValidationError(f"Duplicate reference key at record {index}: {key}")
        seen.add(key)


def immutable_fields_match(
    result: dict[str, Any], reference: dict[str, Any]
) -> bool:
    return all(
        result.get(field) == reference.get(field)
        for field in REQUIRED_REFERENCE_FIELDS
    )


def validate_output_records(
    records: list[dict[str, Any]],
    expected_records: list[dict[str, Any]],
    source_name: str,
    require_complete: bool,
) -> list[dict[str, Any]]:
    expected_by_key = {record_key(record): record for record in expected_records}
    found: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for index, record in enumerate(records):
        if set(record) != OUTPUT_FIELDS:
            raise ValidationError(
                f"{source_name} record {index} has fields {sorted(record)}; "
                f"expected exactly {sorted(OUTPUT_FIELDS)}."
            )
        key = record_key(record)
        if key not in expected_by_key:
            raise ValidationError(
                f"{source_name} record {index} is not part of this input chunk: {key}"
            )
        if key in found:
            raise ValidationError(f"Duplicate checkpoint result in {source_name}: {key}")
        if not immutable_fields_match(record, expected_by_key[key]):
            raise ValidationError(
                f"Immutable input fields changed in {source_name} record {index}: {key}"
            )
        if record["prediction"] not in {"Yes", "No"}:
            raise ValidationError(
                f"Invalid prediction in {source_name} record {index}: "
                f"{record['prediction']!r}"
            )
        expected_correct = record["prediction"] == record["ground_truth"]
        if record["is_correct"] is not expected_correct:
            raise ValidationError(
                f"Incorrect is_correct value in {source_name} record {index}: {key}"
            )
        if not isinstance(record["needed_fallback"], bool):
            raise ValidationError(
                f"Invalid needed_fallback in {source_name} record {index}."
            )
        if not isinstance(record["confidence"], dict):
            raise ValidationError(f"Invalid confidence in {source_name} record {index}.")
        if not isinstance(record["judge_output"], str):
            raise ValidationError(f"Invalid judge_output in {source_name} record {index}.")
        found[key] = record

    if require_complete and len(found) != len(expected_records):
        raise ValidationError(
            f"{source_name} is incomplete: {len(found)}/{len(expected_records)} records."
        )

    # Always restore reference order, including after an interrupted run.
    return [
        found[record_key(reference)]
        for reference in expected_records
        if record_key(reference) in found
    ]


def chunk_bounds(total: int, chunk_id: int, total_chunks: int) -> tuple[int, int]:
    if total_chunks < 1:
        raise ValidationError("--total-chunks must be at least 1.")
    if not 0 <= chunk_id < total_chunks:
        raise ValidationError(
            f"--chunk-id must be in [0, {total_chunks - 1}], got {chunk_id}."
        )
    chunk_size = math.ceil(total / total_chunks)
    start = chunk_id * chunk_size
    end = min(start + chunk_size, total)
    return start, end


def result_payload(records: list[dict[str, Any]], use_manual: bool) -> dict[str, Any]:
    accuracy = (
        sum(1 for record in records if record["is_correct"]) / len(records) * 100.0
        if records
        else 0.0
    )
    # Preserve the exact top-level/metadata structure of the previous baseline.
    return {
        "metadata": {
            "overall_accuracy": accuracy,
            "use_manual": use_manual,
        },
        "results": records,
    }


def save_checkpoint(
    path: Path, records: list[dict[str, Any]], use_manual: bool
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    U.save_results_atomically(str(path), result_payload(records, use_manual))


def load_checkpoint(
    path: Path, expected_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = extract_results(read_json(path), path)
    return validate_output_records(
        records,
        expected_records,
        source_name=str(path),
        require_complete=False,
    )


def build_dataset_index(dataset_path: Path) -> dict[str, dict[str, Any]]:
    dataset = U.load_json(str(dataset_path))
    if not isinstance(dataset, list):
        raise ValidationError(f"Dataset is not a list: {dataset_path}")

    by_pmid: dict[str, dict[str, Any]] = {}
    for index, article in enumerate(dataset):
        if not isinstance(article, dict):
            raise ValidationError(f"Dataset record {index} is not an object.")
        pmid = str(article.get("pmid", ""))
        if not pmid:
            raise ValidationError(f"Dataset record {index} has no PMID.")
        if pmid in by_pmid:
            raise ValidationError(f"Duplicate PMID in dataset: {pmid}")
        if not isinstance(article.get("abstract", ""), str):
            raise ValidationError(f"PMID {pmid} has a non-string abstract.")
        by_pmid[pmid] = article
    return by_pmid


def paths_for_run(args: argparse.Namespace) -> tuple[str, Path, Path]:
    mode_name = "withmanual" if args.with_manual else "nomanual"
    base = f"baseline_{mode_name}_results"
    checkpoint = Path(args.checkpoint_dir) / (
        f"{base}_rejudge{args.model_label}_chunk{args.chunk_id}.json"
    )
    full_output = Path(args.output_dir) / (
        f"{base}_full_rejudge{args.model_label}.json"
    )
    return base, checkpoint, full_output


def complete_full_output_exists(
    full_output: Path,
    all_reference_records: list[dict[str, Any]],
) -> bool:
    if not full_output.exists():
        return False
    records = extract_results(read_json(full_output), full_output)
    validate_output_records(
        records,
        all_reference_records,
        source_name=str(full_output),
        require_complete=True,
    )
    return True


def merge_if_complete(
    args: argparse.Namespace,
    all_reference_records: list[dict[str, Any]],
    full_output: Path,
    use_manual: bool,
) -> bool:
    """Merge only after every chunk is complete; lock prevents merge races."""
    full_output.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(full_output) + ".merge.lock")

    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

        if complete_full_output_exists(full_output, all_reference_records):
            print(f"Validated complete full output: {full_output}", flush=True)
            return True

        mode_name = "withmanual" if use_manual else "nomanual"
        base = f"baseline_{mode_name}_results"
        merged: list[dict[str, Any]] = []

        for chunk_id in range(args.total_chunks):
            start, end = chunk_bounds(
                len(all_reference_records), chunk_id, args.total_chunks
            )
            expected = all_reference_records[start:end]
            chunk_path = Path(args.checkpoint_dir) / (
                f"{base}_rejudge{args.model_label}_chunk{chunk_id}.json"
            )
            if not chunk_path.exists():
                return False
            chunk_records = extract_results(read_json(chunk_path), chunk_path)
            try:
                ordered = validate_output_records(
                    chunk_records,
                    expected,
                    source_name=str(chunk_path),
                    require_complete=True,
                )
            except ValidationError as exc:
                # An ordinary partial checkpoint means only that another array task
                # still needs to be resumed. Other validation failures remain fatal.
                if " is incomplete:" in str(exc):
                    return False
                raise
            merged.extend(ordered)

        merged = validate_output_records(
            merged,
            all_reference_records,
            source_name="merged chunks",
            require_complete=True,
        )
        U.save_results_atomically(
            str(full_output), result_payload(merged, use_manual)
        )
        print(
            f"Created complete full output: {full_output} "
            f"({len(merged)} records)",
            flush=True,
        )
        return True


def main() -> int:
    args = parse_args()
    use_manual = bool(args.with_manual)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, request_stop)

    if args.max_runtime_minutes <= 0:
        raise ValidationError("--max-runtime-minutes must be positive.")

    U.setup_threads()
    seed = 42 + args.chunk_id
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    if not torch.cuda.is_available():
        raise RuntimeError("CRITICAL ERROR: No CUDA GPU is available.")

    model_path = Path(args.judge_model)
    if not model_path.exists():
        raise ValidationError(f"Judge model directory not found: {model_path}")

    reference_path = Path(args.reference_file)
    all_reference_records = extract_results(read_json(reference_path), reference_path)
    validate_reference(all_reference_records, use_manual, reference_path)

    _, checkpoint_path, full_output = paths_for_run(args)

    # A validated complete full output is never overwritten by an accidental rerun.
    if complete_full_output_exists(full_output, all_reference_records):
        print(f"Already complete; nothing to do: {full_output}", flush=True)
        return 0

    start_index, end_index = chunk_bounds(
        len(all_reference_records), args.chunk_id, args.total_chunks
    )
    chunk_reference = all_reference_records[start_index:end_index]
    if not chunk_reference:
        raise ValidationError(
            f"Chunk {args.chunk_id} is empty; reduce --total-chunks."
        )

    results = load_checkpoint(checkpoint_path, chunk_reference)
    done = {record_key(record) for record in results}

    print(
        "\n" + "=" * 72 + "\n"
        f"Model:       {args.judge_model}\n"
        f"Model label: {args.model_label}\n"
        f"Manual:      {use_manual}\n"
        f"Reference:   {reference_path}\n"
        f"Chunk:       {args.chunk_id}/{args.total_chunks - 1}\n"
        f"Input rows:  {start_index}:{end_index} ({len(chunk_reference)})\n"
        f"Resuming:    {len(results)}/{len(chunk_reference)} completed\n"
        f"Checkpoint:  {checkpoint_path}\n"
        f"Full output: {full_output}\n"
        + "=" * 72,
        flush=True,
    )

    if len(results) == len(chunk_reference):
        merge_if_complete(
            args, all_reference_records, full_output, use_manual
        )
        return 0

    dataset_by_pmid = build_dataset_index(Path(args.dataset_path))
    missing_pmids = sorted(
        {
            str(record["pmid"])
            for record in chunk_reference
            if str(record["pmid"]) not in dataset_by_pmid
        }
    )
    if missing_pmids:
        preview = ", ".join(missing_pmids[:10])
        raise ValidationError(
            f"{len(missing_pmids)} reference PMIDs are absent from the dataset: {preview}"
        )

    manual_text = (
        U.load_manual(args.manual_path) if use_manual else ""
    )

    # Runtime includes model loading, which protects against a slow cluster/model load.
    deadline = time.monotonic() + args.max_runtime_minutes * 60.0
    judge_model, judge_tokenizer = U.load_model(args.judge_model)

    for local_index, reference in enumerate(chunk_reference):
        key = record_key(reference)
        if key in done:
            continue
        if STOP_REQUESTED or time.monotonic() >= deadline:
            break

        pmid = str(reference["pmid"])
        article = dataset_by_pmid[pmid]
        abstract = article.get("abstract", "")
        assigned = list(reference["assigned_tags"])
        candidate = str(reference["candidate_tag"])
        ground_truth = str(reference["ground_truth"])
        stage_name = str(reference["stage"])

        messages = build_judge_messages(
            abstract,
            assigned,
            candidate,
            manual_text,
            use_manual,
        )
        answer, raw_output, needed_fallback = U.generate_judge_answer(
            messages,
            judge_model,
            judge_tokenizer,
            max_new_tokens=768,
        )
        confidence = U.decision_confidence(
            messages,
            judge_model,
            judge_tokenizer,
            include_debater=False,
        )
        if answer is None:
            answer = U.verdict_from_confidence(confidence)

        if answer not in {"Yes", "No"}:
            raise RuntimeError(
                f"Fallback failed to produce Yes/No for {key}: {answer!r}"
            )

        is_correct = answer == ground_truth
        record = {
            "pmid": reference["pmid"],
            "stage": stage_name,
            "candidate_tag": reference["candidate_tag"],
            "assigned_tags": assigned,
            "ground_truth": ground_truth,
            "use_manual": use_manual,
            "prediction": answer,
            "is_correct": is_correct,
            "needed_fallback": bool(needed_fallback),
            "confidence": confidence,
            "judge_output": raw_output,
        }
        if set(record) != OUTPUT_FIELDS:
            raise AssertionError("Internal error: output schema changed.")

        results.append(record)
        done.add(key)
        # Reorder and atomically checkpoint after every completed record.
        results = validate_output_records(
            results,
            chunk_reference,
            source_name="in-memory checkpoint",
            require_complete=False,
        )
        save_checkpoint(checkpoint_path, results, use_manual)

        probability = confidence.get("verdict_prob_belongs")
        probability_text = (
            f"{float(probability):.3f}" if probability is not None else "n/a"
        )
        print(
            f"[{local_index + 1}/{len(chunk_reference)}] "
            f"{stage_name} | {pmid} | tgt {ground_truth:3s} | pred {answer:3s} "
            f"| p(belongs)={probability_text} "
            f"-> {'OK' if is_correct else 'X'}"
            f"{' (fb)' if needed_fallback else ''}",
            flush=True,
        )

    # Ensure a valid checkpoint also exists if the run stopped before a new record.
    save_checkpoint(checkpoint_path, results, use_manual)

    if len(results) != len(chunk_reference):
        print(
            f"SAFE STOP: chunk {args.chunk_id} has "
            f"{len(results)}/{len(chunk_reference)} records. "
            "Submit the same sbatch file again to resume.",
            flush=True,
        )
        return 75

    print(
        f"Chunk {args.chunk_id} complete: {len(results)}/{len(chunk_reference)}",
        flush=True,
    )
    merged = merge_if_complete(
        args, all_reference_records, full_output, use_manual
    )
    if not merged:
        print("Other chunks are still incomplete; full merge deferred.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, RuntimeError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
