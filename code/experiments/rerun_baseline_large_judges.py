#!/usr/bin/env python3
"""
Rejudge the two robust baseline conditions with a larger Qwen judge.

The previous full baseline result file is the authoritative input manifest:
PMID, stage, candidate tag, assigned tags, and ground truth are copied from it.
Only the abstract is looked up in pubmed_xmlc_dataset.json. This avoids selecting
new random candidates after a restart and makes every comparison exactly paired.

The result records retain the field set and field order of the previous robust
baseline files. Model/source provenance is stored in top-level metadata and in
the output filename, not as an extra per-record field.

A checkpoint is written atomically after every completed record. Existing output
is validated before resume; incompatible checkpoints are never overwritten.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import random
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import torch

import debate_utils as U
from debate_baseline_judge import build_judge_messages

EXIT_GRACEFUL_REQUEUE = 75
STOP_REQUESTED = False

REQUIRED_REFERENCE_FIELDS = (
    "pmid",
    "stage",
    "candidate_tag",
    "assigned_tags",
    "ground_truth",
    "use_manual",
)

# This is deliberately identical to the previous robust baseline record schema.
RESULT_FIELDS = (
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
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resumably rejudge an existing robust baseline manifest."
    )
    parser.add_argument("--model-id", required=True,
                        help="Local model directory, e.g. ./Qwen3.5-2B")
    parser.add_argument("--model-label", required=True,
                        help="Short provenance label, e.g. Qwen3.5-2B")
    parser.add_argument("--reference-file", required=True,
                        help="Previous full baseline JSON used as the input manifest")
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--dataset-path", default="pubmed_xmlc_dataset.json")
    parser.add_argument("--manual-path", default="NLM_Indexing_manual.txt")

    manual_group = parser.add_mutually_exclusive_group(required=True)
    manual_group.add_argument("--with-manual", action="store_true")
    manual_group.add_argument("--no-manual", action="store_true")

    parser.add_argument("--max-new-tokens", type=int, default=768,
                        help="Keep at 768 to match the previous robust baseline")
    parser.add_argument("--retries", type=int, default=3,
                        help="Attempts for one record before stopping safely")
    parser.add_argument("--retry-wait", type=float, default=5.0)
    return parser.parse_args()


def request_stop(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(
        f"\nReceived signal {signum}; stopping after the current model call. "
        "The last finished record is already checkpointed.",
        flush=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("stage", "")),
        str(record.get("pmid", "")),
        str(record.get("candidate_tag", "")),
        str(record.get("ground_truth", "")),
    )


def load_json_strict(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Cannot read valid JSON from {path}: {exc}") from exc


def extract_results(payload: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError(f"{path} must contain a top-level 'results' list")
    if not all(isinstance(item, dict) for item in payload["results"]):
        raise RuntimeError(f"{path} contains a non-object result record")
    return payload["results"]


def validate_reference(
    records: list[dict[str, Any]], expected_manual: bool, path: Path
) -> None:
    if not records:
        raise RuntimeError(f"Reference file has no records: {path}")

    seen: set[tuple[str, str, str, str]] = set()
    for index, record in enumerate(records):
        missing = [field for field in REQUIRED_REFERENCE_FIELDS if field not in record]
        if missing:
            raise RuntimeError(
                f"Reference record {index} lacks fields: {', '.join(missing)}"
            )
        if not isinstance(record["assigned_tags"], list):
            raise RuntimeError(f"Reference record {index}: assigned_tags is not a list")
        if record["ground_truth"] not in {"Yes", "No"}:
            raise RuntimeError(f"Reference record {index}: invalid ground_truth")
        if bool(record["use_manual"]) != expected_manual:
            raise RuntimeError(
                f"Reference/manual mismatch at record {index}: "
                f"expected use_manual={expected_manual}"
            )
        key = canonical_key(record)
        if key in seen:
            raise RuntimeError(f"Duplicate exact reference key at record {index}: {key}")
        seen.add(key)


def build_abstract_index(dataset: Any) -> dict[str, str]:
    if not isinstance(dataset, list):
        raise RuntimeError("Dataset must be a top-level JSON list")

    index: dict[str, str] = {}
    for row_number, article in enumerate(dataset):
        if not isinstance(article, dict):
            raise RuntimeError(f"Dataset row {row_number} is not an object")
        pmid = str(article.get("pmid", ""))
        if not pmid:
            raise RuntimeError(f"Dataset row {row_number} has no PMID")
        abstract = article.get("abstract", "")
        if not isinstance(abstract, str):
            raise RuntimeError(f"Dataset row {row_number} has a non-string abstract")
        if pmid in index and index[pmid] != abstract:
            raise RuntimeError(f"Dataset has conflicting duplicate PMID {pmid}")
        index[pmid] = abstract
    return index


def small_model_manifest(model_path: Path) -> str:
    """Fingerprint small model configuration files without hashing weight shards."""
    names = (
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    )
    entries: list[str] = []
    for name in names:
        candidate = model_path / name
        if candidate.is_file():
            entries.append(f"{name}:{sha256_file(candidate)}")
    return sha256_text("\n".join(entries))


def fixed_metadata(
    args: argparse.Namespace,
    use_manual: bool,
    reference_path: Path,
    dataset_path: Path,
    manual_path: Path,
    prompt_hash: str,
) -> dict[str, Any]:
    model_path = Path(args.model_id).expanduser().resolve()
    return {
        "use_manual": use_manual,
        "judge_model": args.model_label,
        "judge_model_id": args.model_id,
        "judge_model_path": str(model_path),
        "model_config_manifest_sha256": small_model_manifest(model_path),
        "reference_file": str(reference_path),
        "reference_sha256": sha256_file(reference_path),
        "dataset_file": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "manual_sha256": sha256_file(manual_path) if use_manual else None,
        "prompt_function_sha256": prompt_hash,
        "max_new_tokens": args.max_new_tokens,
        "inference_kind": "baseline_large_judge_exact_manifest_rejudge",
    }


def validate_checkpoint(
    payload: Any,
    output_path: Path,
    expected_fixed_metadata: dict[str, Any],
    reference_by_key: dict[tuple[str, str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"Checkpoint {output_path} is not a JSON object")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError(f"Checkpoint {output_path} has no metadata object")

    for field, expected in expected_fixed_metadata.items():
        if metadata.get(field) != expected:
            raise RuntimeError(
                f"Refusing incompatible checkpoint {output_path}: metadata field "
                f"{field!r} is {metadata.get(field)!r}, expected {expected!r}"
            )

    records = extract_results(payload, output_path)
    seen: set[tuple[str, str, str, str]] = set()
    for index, record in enumerate(records):
        if tuple(record.keys()) != RESULT_FIELDS:
            raise RuntimeError(
                f"Checkpoint record {index} has a different schema/order. "
                f"Found {tuple(record.keys())}, expected {RESULT_FIELDS}"
            )
        key = canonical_key(record)
        if key in seen:
            raise RuntimeError(f"Duplicate checkpoint key at record {index}: {key}")
        seen.add(key)
        source = reference_by_key.get(key)
        if source is None:
            raise RuntimeError(f"Checkpoint record {index} is absent from the reference")
        for field in ("pmid", "stage", "candidate_tag", "assigned_tags",
                      "ground_truth", "use_manual"):
            if record[field] != source[field]:
                raise RuntimeError(
                    f"Checkpoint record {index} changed source field {field!r}"
                )
        if record["prediction"] not in {"Yes", "No"}:
            raise RuntimeError(f"Checkpoint record {index} has invalid prediction")
        expected_correct = record["prediction"] == record["ground_truth"]
        if record["is_correct"] is not expected_correct:
            raise RuntimeError(f"Checkpoint record {index} has invalid is_correct")
    return records


def save_checkpoint(
    output_path: Path,
    records: list[dict[str, Any]],
    fixed: dict[str, Any],
    expected_count: int,
) -> None:
    correct = sum(1 for record in records if record["is_correct"])
    accuracy = (100.0 * correct / len(records)) if records else 0.0
    metadata = {
        "overall_accuracy": accuracy,
        **fixed,
        "completed_records": len(records),
        "expected_records": expected_count,
        "complete": len(records) == expected_count,
    }
    U.save_results_atomically(
        str(output_path),
        {"metadata": metadata, "results": records},
    )


def run_one_record(
    source: dict[str, Any],
    abstract: str,
    manual_text: str,
    use_manual: bool,
    model: Any,
    tokenizer: Any,
    max_new_tokens: int,
) -> dict[str, Any]:
    messages = build_judge_messages(
        abstract,
        source["assigned_tags"],
        source["candidate_tag"],
        manual_text,
        use_manual,
    )

    # These calls and parameters match debate_baseline_judge.py.
    answer, raw_output, needed_fallback = U.generate_judge_answer(
        messages, model, tokenizer, max_new_tokens=max_new_tokens
    )
    confidence = U.decision_confidence(
        messages, model, tokenizer, include_debater=False
    )
    if answer is None:
        answer = U.verdict_from_confidence(confidence)
    if answer not in {"Yes", "No"}:
        raise RuntimeError(f"No valid Yes/No verdict after fallback: {answer!r}")

    return {
        "pmid": source["pmid"],
        "stage": source["stage"],
        "candidate_tag": source["candidate_tag"],
        "assigned_tags": copy.deepcopy(source["assigned_tags"]),
        "ground_truth": source["ground_truth"],
        "use_manual": use_manual,
        "prediction": answer,
        "is_correct": answer == source["ground_truth"],
        "needed_fallback": needed_fallback,
        "confidence": confidence,
        "judge_output": raw_output,
    }


def main() -> int:
    args = parse_args()
    use_manual = bool(args.with_manual)

    signal.signal(signal.SIGUSR1, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    if not torch.cuda.is_available():
        raise RuntimeError("No CUDA GPU is available")
    if args.retries < 1:
        raise RuntimeError("--retries must be at least 1")

    reference_path = Path(args.reference_file).expanduser().resolve()
    output_path = Path(args.output_file).expanduser().resolve()
    dataset_path = Path(args.dataset_path).expanduser().resolve()
    manual_path = Path(args.manual_path).expanduser().resolve()
    model_path = Path(args.model_id).expanduser().resolve()

    for required in (reference_path, dataset_path, model_path):
        if not required.exists():
            raise FileNotFoundError(required)
    if use_manual and not manual_path.is_file():
        raise FileNotFoundError(manual_path)
    if reference_path == output_path:
        raise RuntimeError("Reference and output paths must differ")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prevent two jobs from writing the same checkpoint concurrently.
    lock_path = Path(str(output_path) + ".lock")
    lock_handle = lock_path.open("a+", encoding="utf-8")
    print(f"Waiting for checkpoint lock: {lock_path}", flush=True)
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

    reference_payload = load_json_strict(reference_path)
    reference_records = extract_results(reference_payload, reference_path)
    validate_reference(reference_records, use_manual, reference_path)
    reference_by_key = {canonical_key(record): record for record in reference_records}

    dataset = load_json_strict(dataset_path)
    abstract_by_pmid = build_abstract_index(dataset)
    missing_pmids = sorted({
        str(record["pmid"])
        for record in reference_records
        if str(record["pmid"]) not in abstract_by_pmid
    })
    if missing_pmids:
        preview = ", ".join(missing_pmids[:10])
        raise RuntimeError(
            f"{len(missing_pmids)} reference PMIDs are absent from the dataset: {preview}"
        )

    import inspect
    prompt_hash = sha256_text(inspect.getsource(build_judge_messages))
    fixed = fixed_metadata(
        args, use_manual, reference_path, dataset_path, manual_path, prompt_hash
    )

    if output_path.exists():
        existing_payload = load_json_strict(output_path)
        results = validate_checkpoint(
            existing_payload, output_path, fixed, reference_by_key
        )
    else:
        results = []
        save_checkpoint(output_path, results, fixed, len(reference_records))

    done = {canonical_key(record) for record in results}
    remaining = [record for record in reference_records if canonical_key(record) not in done]

    print(
        f"Model={args.model_label} manual={use_manual} "
        f"completed={len(results)}/{len(reference_records)} "
        f"remaining={len(remaining)}",
        flush=True,
    )

    if not remaining:
        save_checkpoint(output_path, results, fixed, len(reference_records))
        print("Output is already complete and valid.", flush=True)
        return 0
    if STOP_REQUESTED:
        return EXIT_GRACEFUL_REQUEUE

    U.setup_threads()
    random.seed(42)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    manual_text = U.load_manual(str(manual_path)) if use_manual else ""

    model, tokenizer = U.load_model(args.model_id)

    for source in reference_records:
        key = canonical_key(source)
        if key in done:
            continue
        if STOP_REQUESTED:
            save_checkpoint(output_path, results, fixed, len(reference_records))
            return EXIT_GRACEFUL_REQUEUE

        pmid = str(source["pmid"])
        new_record: dict[str, Any] | None = None

        for attempt in range(1, args.retries + 1):
            try:
                new_record = run_one_record(
                    source=source,
                    abstract=abstract_by_pmid[pmid],
                    manual_text=manual_text,
                    use_manual=use_manual,
                    model=model,
                    tokenizer=tokenizer,
                    max_new_tokens=args.max_new_tokens,
                )
                break
            except Exception:
                print(
                    f"Record failed (attempt {attempt}/{args.retries}) for {key}:\n"
                    f"{traceback.format_exc()}",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                if STOP_REQUESTED:
                    save_checkpoint(output_path, results, fixed, len(reference_records))
                    return EXIT_GRACEFUL_REQUEUE
                if attempt < args.retries:
                    time.sleep(args.retry_wait * attempt)

        if new_record is None:
            save_checkpoint(output_path, results, fixed, len(reference_records))
            raise RuntimeError(
                f"Record {key} failed {args.retries} times; checkpoint preserved"
            )

        results.append(new_record)
        done.add(key)
        save_checkpoint(output_path, results, fixed, len(reference_records))

        probability = new_record.get("confidence", {}).get(
            "verdict_prob_belongs", float("nan")
        )
        status = "OK" if new_record["is_correct"] else "X"
        fallback = " (fb)" if new_record["needed_fallback"] else ""
        print(
            f"[{len(results)}/{len(reference_records)}] {pmid} | "
            f"{source['stage']} | tgt {source['ground_truth']} | "
            f"pred {new_record['prediction']} | p(belongs)={probability:.3f} "
            f"-> {status}{fallback}",
            flush=True,
        )

    save_checkpoint(output_path, results, fixed, len(reference_records))
    print(f"COMPLETE: {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
