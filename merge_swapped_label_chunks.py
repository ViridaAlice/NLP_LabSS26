#!/usr/bin/env python3
"""Merge resumable BAB label-swap result chunks and check completeness.

This script never modifies the source chunks or the original interactive results.
It writes one new merged JSON file. Use --force only to replace an older merged file.

Example:
    python3 merge_swapped_label_chunks.py \
      --inputs 'bab_swapped_results_chunk*.json' \
      --expected-source interactive_results_full.json \
      --expected-chunks 4 \
      --output bab_swapped_results_full.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


AUTO_JUDGE_FIELDS = (
    "judge_BAB_swapped_labels",
    "judge_BAB_label_swapped",
    "judge_BAB_swapped",
    "judge_BAB_relabelled",
    "judge_BAB_relabelled_as_ABA",
    "judge_swapped_labels",
    "judge_label_swapped",
    "judge_swapped",
    "swapped_judge",
    "judge",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge label-swap chunks and verify that every expected record was judged."
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="Chunk files or quoted glob patterns, e.g. 'bab_swapped_results_chunk*.json'.",
    )
    parser.add_argument("--output", required=True, help="New merged JSON output path.")
    parser.add_argument(
        "--expected-source",
        help=(
            "Original interactive_results_full.json. If supplied, its keys are used "
            "to detect missing and unexpected records."
        ),
    )
    parser.add_argument(
        "--expected-chunks",
        type=int,
        help="Expected number of chunk IDs, normally the SLURM array size (for example 4).",
    )
    parser.add_argument(
        "--judge-field",
        help=(
            "Dot path of the new judge object, e.g. judge_BAB_swapped_labels. "
            "If omitted, the script detects it."
        ),
    )
    parser.add_argument(
        "--key-fields",
        nargs="+",
        default=["stage", "pmid"],
        help="Fields forming a unique record key (default: stage pmid).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing merged output. Source chunks are never changed.",
    )
    return parser.parse_args()


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def records_from_document(document: Any, path: str) -> List[Dict[str, Any]]:
    if isinstance(document, dict) and isinstance(document.get("results"), list):
        records = document["results"]
    elif isinstance(document, list):
        records = document
    else:
        raise ValueError(f"{path}: expected a JSON object with a 'results' list, or a list")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"{path}: every result must be a JSON object")
    return records


def natural_key(path: str) -> List[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path)]


def expand_inputs(patterns: Sequence[str]) -> List[str]:
    paths: List[str] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(matches)
        elif os.path.isfile(pattern):
            paths.append(pattern)
        else:
            print(f"[WARN] No file matched: {pattern}", file=sys.stderr)
    return sorted(set(paths), key=natural_key)


def make_key(record: Dict[str, Any], fields: Sequence[str]) -> Tuple[str, ...]:
    values: List[str] = []
    for field in fields:
        if field not in record or record[field] is None:
            raise ValueError(f"record is missing key field {field!r}")
        values.append(str(record[field]))
    return tuple(values)


def key_as_object(key: Tuple[str, ...], fields: Sequence[str]) -> Dict[str, str]:
    return dict(zip(fields, key))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get_dot_path(record: Dict[str, Any], path: str) -> Any:
    current: Any = record
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return None
        current = current[component]
    return current


def looks_like_judge(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    prediction = value.get("prediction", value.get("answer"))
    if isinstance(prediction, bool):
        return True
    return str(prediction).strip().lower() in {"yes", "no", "true", "false"}


def infer_judge_field(record: Dict[str, Any]) -> Optional[str]:
    for field in AUTO_JUDGE_FIELDS:
        if looks_like_judge(get_dot_path(record, field)):
            return field

    candidates = []
    for key, value in record.items():
        lowered = key.lower()
        if (
            "judge" in lowered
            and any(token in lowered for token in ("swap", "label", "relabel"))
            and looks_like_judge(value)
        ):
            candidates.append(key)
    if len(candidates) == 1:
        return candidates[0]
    return None


def prediction_from_judge(judge: Any) -> Optional[str]:
    if not isinstance(judge, dict):
        return None
    value = judge.get("prediction", judge.get("answer"))
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip().lower()
    if text in {"yes", "true"}:
        return "Yes"
    if text in {"no", "false"}:
        return "No"
    return None


def extract_chunk_id(path: str) -> Optional[int]:
    name = Path(path).name
    matches = re.findall(r"chunk[_-]?(\d+)", name, flags=re.IGNORECASE)
    return int(matches[-1]) if matches else None


def atomic_write_json(path: str, document: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def percent(numerator: int, denominator: int) -> Optional[float]:
    return round(100.0 * numerator / denominator, 6) if denominator else None


def main() -> int:
    args = parse_args()

    if os.path.exists(args.output) and not args.force:
        print(
            f"ERROR: output already exists: {args.output}\n"
            "Choose a new path or pass --force to replace only that merged output.",
            file=sys.stderr,
        )
        return 1

    chunk_paths = expand_inputs(args.inputs)
    if not chunk_paths:
        print("ERROR: no input chunks found", file=sys.stderr)
        return 1

    print(f"[INFO] Found {len(chunk_paths)} input file(s):")
    for path in chunk_paths:
        print(f"  - {path}")

    observed_chunk_ids = sorted(
        chunk_id for chunk_id in (extract_chunk_id(path) for path in chunk_paths) if chunk_id is not None
    )
    duplicate_chunk_ids = sorted(
        chunk_id for chunk_id, count in Counter(observed_chunk_ids).items() if count > 1
    )
    unique_chunk_ids = sorted(set(observed_chunk_ids))
    missing_chunk_ids: List[int] = []
    if args.expected_chunks is not None:
        missing_chunk_ids = sorted(set(range(args.expected_chunks)) - set(unique_chunk_ids))

    merged_by_key: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    source_by_key: Dict[Tuple[str, ...], str] = {}
    exact_duplicates = 0
    conflicting_duplicates: List[Dict[str, Any]] = []
    unreadable_or_invalid: List[str] = []

    for path in chunk_paths:
        try:
            records = records_from_document(load_json(path), path)
        except Exception as exc:
            unreadable_or_invalid.append(f"{path}: {exc}")
            continue

        print(f"[LOAD] {path}: {len(records)} record(s)")
        for index, record in enumerate(records):
            try:
                key = make_key(record, args.key_fields)
            except ValueError as exc:
                unreadable_or_invalid.append(f"{path}, result {index}: {exc}")
                continue

            if key not in merged_by_key:
                merged_by_key[key] = record
                source_by_key[key] = path
            elif canonical_json(merged_by_key[key]) == canonical_json(record):
                exact_duplicates += 1
            else:
                conflicting_duplicates.append(
                    {
                        "key": key_as_object(key, args.key_fields),
                        "first_file": source_by_key[key],
                        "second_file": path,
                    }
                )

    if conflicting_duplicates:
        print("ERROR: conflicting duplicate records were found; no output was written.", file=sys.stderr)
        for conflict in conflicting_duplicates[:20]:
            print(f"  {conflict}", file=sys.stderr)
        return 1

    expected_by_key: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    expected_order: List[Tuple[str, ...]] = []
    if args.expected_source:
        expected_records = records_from_document(load_json(args.expected_source), args.expected_source)
        for record in expected_records:
            key = make_key(record, args.key_fields)
            if key in expected_by_key:
                raise ValueError(
                    f"Expected source has a duplicate key: {key_as_object(key, args.key_fields)}"
                )
            expected_by_key[key] = record
            expected_order.append(key)

    merged_keys = set(merged_by_key)
    expected_keys = set(expected_by_key)
    missing_keys = sorted(expected_keys - merged_keys)
    unexpected_keys = sorted(merged_keys - expected_keys) if expected_by_key else []

    if expected_order:
        ordered_keys = [key for key in expected_order if key in merged_by_key]
        ordered_keys.extend(sorted(merged_keys - set(ordered_keys)))
    else:
        ordered_keys = sorted(merged_keys)
    merged_records = [merged_by_key[key] for key in ordered_keys]

    detected_fields: Counter[str] = Counter()
    incomplete_judgments: List[Dict[str, str]] = []
    correct = 0
    accuracy_denominator = 0

    for key in ordered_keys:
        record = merged_by_key[key]
        field = args.judge_field or infer_judge_field(record)
        if field:
            detected_fields[field] += 1
        judge = get_dot_path(record, field) if field else None
        prediction = prediction_from_judge(judge)
        if prediction is None:
            incomplete_judgments.append(key_as_object(key, args.key_fields))
            continue

        ground_truth = record.get("ground_truth")
        if ground_truth is None and key in expected_by_key:
            ground_truth = expected_by_key[key].get("ground_truth")
        normalized_truth = prediction_from_judge({"prediction": ground_truth})
        if normalized_truth is not None:
            accuracy_denominator += 1
            correct += int(prediction == normalized_truth)

    all_chunks_present = not missing_chunk_ids and not duplicate_chunk_ids
    all_expected_records_present = not missing_keys if expected_by_key else None
    all_judgments_complete = not incomplete_judgments
    valid_inputs = not unreadable_or_invalid
    is_complete = (
        all_chunks_present
        and all_judgments_complete
        and valid_inputs
        and (all_expected_records_present is not False)
    )

    metadata = {
        "experiment": "BAB debate presented with A/B speaker labels swapped",
        "merged_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_files": chunk_paths,
        "input_file_count": len(chunk_paths),
        "expected_chunks": args.expected_chunks,
        "observed_chunk_ids": unique_chunk_ids,
        "missing_chunk_ids": missing_chunk_ids,
        "duplicate_chunk_ids": duplicate_chunk_ids,
        "key_fields": args.key_fields,
        "records_after_deduplication": len(merged_records),
        "exact_duplicate_records_ignored": exact_duplicates,
        "conflicting_duplicate_records": len(conflicting_duplicates),
        "expected_source": args.expected_source,
        "expected_records": len(expected_by_key) if expected_by_key else None,
        "missing_expected_records": len(missing_keys),
        "unexpected_records": len(unexpected_keys),
        "complete_judgments": len(merged_records) - len(incomplete_judgments),
        "incomplete_judgments": len(incomplete_judgments),
        "judge_fields_detected": dict(detected_fields),
        "accuracy_percent": percent(correct, accuracy_denominator),
        "accuracy_n": accuracy_denominator,
        "invalid_inputs_or_records": unreadable_or_invalid,
        "is_complete": is_complete,
        "missing_record_examples": [key_as_object(key, args.key_fields) for key in missing_keys[:100]],
        "unexpected_record_examples": [
            key_as_object(key, args.key_fields) for key in unexpected_keys[:100]
        ],
        "incomplete_judgment_examples": incomplete_judgments[:100],
    }

    atomic_write_json(args.output, {"metadata": metadata, "results": merged_records})

    print("\n==== MERGE / COMPLETENESS REPORT ====")
    print(f"Merged unique records:       {len(merged_records)}")
    if expected_by_key:
        print(f"Expected records:            {len(expected_by_key)}")
        print(f"Missing expected records:    {len(missing_keys)}")
        print(f"Unexpected records:          {len(unexpected_keys)}")
    print(f"Complete judge outputs:      {len(merged_records) - len(incomplete_judgments)}")
    print(f"Incomplete judge outputs:    {len(incomplete_judgments)}")
    print(f"Exact duplicates ignored:    {exact_duplicates}")
    print(f"Missing chunk IDs:           {missing_chunk_ids or 'none detected'}")
    print(f"Invalid inputs/records:      {len(unreadable_or_invalid)}")
    print(f"Detected judge fields:       {dict(detected_fields)}")
    if accuracy_denominator:
        print(f"Merged accuracy:             {100.0 * correct / accuracy_denominator:.3f}%")
    print(f"Output:                      {args.output}")
    print(f"FULLY COMPLETE:              {'YES' if is_complete else 'NO'}")

    return 0 if is_complete else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
