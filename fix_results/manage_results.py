#!/usr/bin/env python3
"""Audit, submit, resume, and merge the requested result repairs.

Python 3.6 compatible. Run from anywhere inside the project checkout.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
RESULTS = os.path.join(ROOT, "results")
CHUNKS = os.path.join(ROOT, "Chunks")
DATASET = os.path.join(ROOT, "pubmed_xmlc_dataset.json")

STAGES = [
    ("Round 1: True Tag", "Yes"),
    ("Round 2: Unrelated Tag", "No"),
    ("Round 3: Similar Tag", "No"),
]

RUNS = {
    "interactive_rejudge2b": {
        "final": "interactive_results_full_rejudge2B.json",
        "source": "interactive_results_full.json",
        "kind": "interactive_rejudge2b",
        "chunks": 30,
        "job": "fix_int2b",
        "sbatch": "sbatch/rejudge_interactive_2b.sh",
    },
    "statement_rejudge2b": {
        "final": "statement_results_full_rejudge2B.json",
        "source": "statement_results_full.json",
        "kind": "statement_rejudge2b",
        "chunks": 24,
        "job": "fix_stmt2b",
        "sbatch": "sbatch/rejudge_statement_2b.sh",
    },
    "pydantic_baseline": {
        "final": "pydantic_baseline_results_full.json",
        "kind": "pydantic_baseline",
        "chunks": 1,
        "job": "fix_pybase",
        "sbatch": "sbatch/repair_pydantic_baseline.sh",
    },
    "pydantic_statement": {
        "final": "pydantic_statement_results_full.json",
        "kind": "pydantic_statement",
        "chunks": 24,
        "job": "fix_pystmt",
        "sbatch": "sbatch/repair_pydantic_statement.sh",
    },
}

AUDIT_FILES = [
    ("baseline_nomanual_results_full.json", ["prediction"]),
    ("baseline_withmanual_results_full.json", ["prediction"]),
    ("interactive_results_BAB_swapped_full.json", ["judge_ABA.prediction", "judge_BAB.prediction", "judge_BAB_swapped_labels.prediction"]),
    ("interactive_results_BAB_swapped_labels_full.json", ["judge_ABA.prediction", "judge_BAB.prediction", "judge_BAB_swapped_labels.prediction"]),
    ("interactive_results_full.json", ["judge_ABA.prediction", "judge_BAB.prediction"]),
    ("interactive_results_full_rejudge2B.json", ["judge_ABA.prediction", "judge_BAB.prediction"]),
    ("pydantic_baseline_results_full.json", ["model_prediction"]),
    ("pydantic_statement_results_full.json", ["model_prediction"]),
    ("statement_results_full.json", ["prediction"]),
    ("statement_results_full_rejudge2B.json", ["prediction"]),
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path, payload):
    directory = os.path.dirname(path) or "."
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        tmp = handle.name
    try:
        os.replace(tmp, path)
    except AttributeError:
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)


def records_from(path):
    if not os.path.exists(path):
        return [], {}
    try:
        payload = load_json(path)
    except (ValueError, OSError) as exc:
        print("WARNING: cannot read {}: {}".format(path, exc))
        return [], {}
    records = payload.get("results", [])
    return records if isinstance(records, list) else [], payload.get("metadata", {})


def key(record):
    return (str(record.get("stage")), str(record.get("pmid")))


def nested(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def valid_for_kind(record, kind):
    if kind == "interactive_rejudge2b":
        return (nested(record, "judge_ABA.prediction") in ("Yes", "No") and
                nested(record, "judge_BAB.prediction") in ("Yes", "No"))
    if kind == "statement_rejudge2b":
        return record.get("prediction") in ("Yes", "No")
    return record.get("model_prediction") in ("Yes", "No")


def expected_records(config):
    if config.get("source"):
        source_path = os.path.join(RESULTS, config["source"])
        source_records, _ = records_from(source_path)
        return source_records

    if not os.path.exists(DATASET):
        raise RuntimeError("Dataset not found: {}".format(DATASET))
    dataset = load_json(DATASET)
    expected = []
    for stage, ground_truth in STAGES:
        for article in dataset:
            if not article.get("mesh_tags"):
                continue
            expected.append({
                "stage": stage,
                "pmid": article.get("pmid"),
                "ground_truth": ground_truth,
            })
    return expected


def combined_map(run_name, config):
    final_path = os.path.join(RESULTS, config["final"])
    base_records, base_meta = records_from(final_path)
    combined = {}
    for record in base_records:
        combined[key(record)] = record

    chunk_dir = os.path.join(CHUNKS, run_name)
    chunk_paths = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json")))
    for path in chunk_paths:
        records, _ = records_from(path)
        for record in records:
            k = key(record)
            if valid_for_kind(record, config["kind"]):
                combined[k] = record
            elif k not in combined:
                combined[k] = record
    return combined, base_meta, chunk_paths


def run_state(run_name, config):
    expected = expected_records(config)
    expected_keys = [key(record) for record in expected]
    if len(expected_keys) != len(set(expected_keys)):
        raise RuntimeError("Expected key set for {} contains duplicates".format(run_name))

    combined, metadata, chunk_paths = combined_map(run_name, config)
    valid = 0
    missing = 0
    invalid = 0
    missing_by_chunk = dict((i, 0) for i in range(config["chunks"]))

    for index, wanted_key in enumerate(expected_keys):
        record = combined.get(wanted_key)
        if record is None:
            missing += 1
            missing_by_chunk[index % config["chunks"]] += 1
        elif not valid_for_kind(record, config["kind"]):
            invalid += 1
            missing_by_chunk[index % config["chunks"]] += 1
        else:
            valid += 1

    unexpected = len(set(combined.keys()) - set(expected_keys))
    incomplete_chunks = [cid for cid, count in sorted(missing_by_chunk.items()) if count]
    return {
        "expected": expected,
        "expected_keys": expected_keys,
        "combined": combined,
        "old_metadata": metadata,
        "chunk_paths": chunk_paths,
        "valid": valid,
        "missing": missing,
        "invalid": invalid,
        "unexpected": unexpected,
        "incomplete_chunks": incomplete_chunks,
        "complete": valid == len(expected_keys) and missing == 0 and invalid == 0,
    }


def merge_if_complete(run_name, config, state):
    if not state["complete"]:
        return False
    ordered = [state["combined"][wanted] for wanted in state["expected_keys"]]
    if len(ordered) != 3000:
        raise RuntimeError("Refusing to merge {} records for {}; expected exactly 3000".format(len(ordered), run_name))
    if len(set(key(record) for record in ordered)) != 3000:
        raise RuntimeError("Refusing to merge duplicate identities for {}".format(run_name))
    if any(not valid_for_kind(record, config["kind"]) for record in ordered):
        raise RuntimeError("Refusing to merge invalid predictions for {}".format(run_name))

    metadata = dict(state["old_metadata"] or {})
    metadata.update({
        "complete": True,
        "merged_records": 3000,
        "unknown_predictions": 0,
        "repair_manager": "fix_results/manage_results.py",
        "repair_chunks": [os.path.relpath(path, ROOT) for path in state["chunk_paths"]],
    })
    if config["kind"] == "statement_rejudge2b":
        metadata["overall_accuracy"] = 100.0 * sum(1 for r in ordered if r.get("is_correct") is True) / 3000.0
    elif config["kind"] == "interactive_rejudge2b":
        metadata["accuracy_ABA"] = 100.0 * sum(1 for r in ordered if nested(r, "judge_ABA.is_correct") is True) / 3000.0
        metadata["accuracy_BAB"] = 100.0 * sum(1 for r in ordered if nested(r, "judge_BAB.is_correct") is True) / 3000.0
    else:
        metadata["overall_accuracy"] = 100.0 * sum(1 for r in ordered if r.get("is_correct") is True) / 3000.0

    target = os.path.join(RESULTS, config["final"])
    atomic_json(target, {"metadata": metadata, "results": ordered})
    print("MERGED: {} -> 3000 valid records".format(config["final"]))
    return True


def array_spec(ids):
    if not ids:
        return ""
    ids = sorted(set(ids))
    groups = []
    start = previous = ids[0]
    for value in ids[1:]:
        if value == previous + 1:
            previous = value
            continue
        groups.append(str(start) if start == previous else "{}-{}".format(start, previous))
        start = previous = value
    groups.append(str(start) if start == previous else "{}-{}".format(start, previous))
    return ",".join(groups)


def job_active(job_name):
    try:
        output = subprocess.check_output(
            ["squeue", "-h", "-n", job_name, "-o", "%i"],
            cwd=ROOT,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        return bool(output.strip())
    except (OSError, subprocess.CalledProcessError):
        return False


def submit_run(run_name, config, state):
    ids = state["incomplete_chunks"]
    if not ids:
        return False
    if job_active(config["job"]):
        print("ACTIVE: {} already has a queued/running job; not submitting duplicates".format(config["job"]))
        return False
    script = os.path.join(HERE, config["sbatch"])
    command = ["sbatch", "--array={}".format(array_spec(ids)), script]
    print("SUBMIT: {}".format(" ".join(command)))
    subprocess.check_call(command, cwd=ROOT)
    return True


def audit_requested():
    print("\nRequested-file audit")
    print("{:<55} {:>7} {:>9}  {}".format("File", "Records", "Missing", "Invalid by outcome path"))
    for filename, paths in AUDIT_FILES:
        records, _ = records_from(os.path.join(RESULTS, filename))
        unique = {}
        for record in records:
            unique[key(record)] = record
        invalid_parts = []
        for path in paths:
            count = sum(1 for record in unique.values() if nested(record, path) not in ("Yes", "No"))
            invalid_parts.append("{}={}".format(path, count))
        print("{:<55} {:>7} {:>9}  {}".format(
            filename, len(unique), max(0, 3000 - len(unique)), "; ".join(invalid_parts)))


def one_pass(do_submit):
    if not os.path.isdir(CHUNKS):
        os.makedirs(CHUNKS)
    logs = os.path.join(CHUNKS, "logs")
    if not os.path.isdir(logs):
        os.makedirs(logs)

    all_complete = True
    any_active = False
    for run_name in sorted(RUNS):
        config = RUNS[run_name]
        run_dir = os.path.join(CHUNKS, run_name)
        if not os.path.isdir(run_dir):
            os.makedirs(run_dir)
        state = run_state(run_name, config)
        if state["complete"]:
            merge_if_complete(run_name, config, state)
            state = run_state(run_name, config)
        print("{}: valid={}/3000 missing={} invalid={} unexpected={} pending_chunks={}".format(
            run_name, state["valid"], state["missing"], state["invalid"],
            state["unexpected"], array_spec(state["incomplete_chunks"]) or "none"))
        if not state["complete"]:
            all_complete = False
            if job_active(config["job"]):
                any_active = True
            if do_submit:
                submit_run(run_name, config, state)
    audit_requested()
    return all_complete, any_active


def parse_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Audit only; submit nothing (default).")
    group.add_argument("--submit", action="store_true", help="Submit incomplete, inactive array tasks once.")
    group.add_argument("--watch", action="store_true", help="Poll, merge, and resubmit until complete.")
    parser.add_argument("--poll-seconds", type=int, default=120)
    return parser.parse_args()


def main():
    args = parse_args()
    os.chdir(ROOT)
    if args.watch:
        while True:
            complete, _ = one_pass(do_submit=True)
            if complete:
                print("\nAll repair runs contain exactly 3000 valid records.")
                return
            print("\nWaiting {} seconds before the next audit...".format(args.poll_seconds))
            time.sleep(max(10, args.poll_seconds))
    else:
        complete, _ = one_pass(do_submit=args.submit)
        if complete:
            print("\nAll repair runs contain exactly 3000 valid records.")
        elif not args.submit:
            print("\nAudit only. Use --submit to start incomplete work.")


if __name__ == "__main__":
    main()
