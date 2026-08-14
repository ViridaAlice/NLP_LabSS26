#!/usr/bin/env python3

import glob
import json
import os
import re
import sys

EXPECTED = 3000
RESULTS_DIR = "results"

LARGER_RUNS = [
    ("Qwen3.5-2B without manual", "2B", False),
    ("Qwen3.5-2B with manual", "2B", True),
    ("Qwen3.5-4B without manual", "4B", False),
    ("Qwen3.5-4B with manual", "4B", True),
]

ASYMMETRIC_RUNS = [
    (
        "Asymmetric baseline: title-only 0.8B judge",
        "asymmetric_titleonly_baseline",
    ),
    (
        "Asymmetric statement: 2B debaters -> title-only 0.8B judge",
        "asymmetric_titleonly_statement",
    ),
    (
        "Asymmetric interactive ABA: 2B debaters -> title-only 0.8B judge",
        "asymmetric_titleonly_interactive_aba",
    ),
]


def normalize(value):
    return str(value or "").strip().lower().replace("\\", "/")


def truth_value(value):
    if isinstance(value, bool):
        return value
    text = normalize(value)
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except Exception as exc:
        return None, str(exc)


def extract_results(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "records", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def metadata_dict(payload):
    if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
        return payload["metadata"]
    return {}


def combined_text(path, payload, records):
    pieces = [path]
    metadata = metadata_dict(payload)

    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            pieces.append("%s=%s" % (key, value))

    if isinstance(payload, dict):
        for key in (
            "experiment_id",
            "judge_model",
            "judge_model_id",
            "debater_model",
            "model",
            "model_id",
            "use_manual",
        ):
            if key in payload:
                pieces.append("%s=%s" % (key, payload[key]))

    for record in records[:5]:
        if not isinstance(record, dict):
            continue
        for key in (
            "experiment_id",
            "judge_model",
            "judge_model_id",
            "model",
            "model_id",
            "use_manual",
        ):
            if key in record:
                pieces.append("%s=%s" % (key, record[key]))

    return normalize(" ".join(pieces))


def detect_model(text):
    compact = re.sub(r"[^a-z0-9.]+", "", text)

    if (
        "qwen3.54b" in compact
        or "qwen354b" in compact
        or "judge4b" in compact
        or "model4b" in compact
    ):
        return "4B"

    if (
        "qwen3.52b" in compact
        or "qwen352b" in compact
        or "judge2b" in compact
        or "model2b" in compact
    ):
        return "2B"

    return None


def detect_manual(text, records):
    values = set()
    for record in records:
        if isinstance(record, dict) and "use_manual" in record:
            parsed = truth_value(record.get("use_manual"))
            if parsed is not None:
                values.add(parsed)

    if len(values) == 1:
        return list(values)[0]

    compact = re.sub(r"[^a-z0-9]+", "", text)
    if (
        "nomanual" in compact
        or "withoutmanual" in compact
        or "usemanualfalse" in compact
    ):
        return False
    if "withmanual" in compact or "usemanualtrue" in compact:
        return True
    return None


def detect_asymmetric_experiment(path, payload):
    metadata = metadata_dict(payload)
    explicit = normalize(
        metadata.get("experiment_id", payload.get("experiment_id", "") if isinstance(payload, dict) else "")
    )
    known = {experiment_id for _, experiment_id in ASYMMETRIC_RUNS}
    if explicit in known:
        return explicit

    filename = normalize(os.path.basename(path))
    for experiment_id in known:
        if experiment_id in filename:
            return experiment_id
    return None


def record_key(record):
    if not isinstance(record, dict):
        return None

    stage = normalize(record.get("stage"))
    pmid = normalize(record.get("pmid"))
    candidate = normalize(record.get("candidate_tag"))
    ground_truth = normalize(record.get("ground_truth"))

    if not stage or not pmid:
        return None
    return (stage, pmid, candidate, ground_truth)


def record_is_generated(record):
    if not isinstance(record, dict):
        return False

    if "generation_complete" in record and truth_value(
        record.get("generation_complete")
    ) is False:
        return False

    prediction = normalize(
        record.get("prediction", record.get("model_prediction", ""))
    )
    return prediction in ("yes", "no")


def summarize_files(files, expected=EXPECTED):
    keys = set()
    raw_count = 0
    invalid_count = 0
    duplicate_count = 0

    for _, records in files:
        for record in records:
            raw_count += 1
            if not record_is_generated(record):
                invalid_count += 1
                continue

            key = record_key(record)
            if key is None:
                invalid_count += 1
                continue

            if key in keys:
                duplicate_count += 1
            else:
                keys.add(key)

    unique_count = len(keys)
    complete = unique_count == expected
    return {
        "complete": complete,
        "unique": unique_count,
        "raw": raw_count,
        "invalid": invalid_count,
        "duplicates": duplicate_count,
        "missing": max(0, expected - unique_count),
        "extra": max(0, unique_count - expected),
    }


def print_run(label, files, summary):
    if summary["complete"]:
        status = "COMPLETE"
    elif summary["unique"] < EXPECTED:
        status = "RE-RUN / RESUME (%d missing)" % summary["missing"]
    else:
        status = "CHECK OUTPUT (%d unexpected extra records)" % summary["extra"]

    print("")
    print(label)
    print("  Status:            %s" % status)
    print("  Unique generated:  %d / %d" % (summary["unique"], EXPECTED))
    print("  Matching files:    %d" % len(files))
    print("  Raw records:       %d" % summary["raw"])
    print("  Invalid records:   %d" % summary["invalid"])
    print("  Duplicate records: %d" % summary["duplicates"])

    if not files:
        print("  Warning: no matching result files found")
    else:
        for path, records in files:
            print("    - %s (%d records)" % (path, len(records)))


def discover_results():
    patterns = [
        os.path.join(RESULTS_DIR, "*.json"),
        os.path.join(RESULTS_DIR, "**", "*.json"),
    ]
    paths = set()
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            if os.path.isfile(path):
                paths.add(path)
    return sorted(paths)


def main():
    larger_grouped = {}
    asymmetric_grouped = {}
    unreadable = []

    for path in discover_results():
        filename = normalize(os.path.basename(path))
        if filename.startswith("test_"):
            continue

        potentially_relevant = (
            "baseline" in filename or "asymmetric_titleonly" in filename
        )
        if not potentially_relevant:
            continue

        payload, error = load_json(path)
        if error is not None:
            unreadable.append((path, error))
            continue

        records = extract_results(payload)
        if records is None:
            continue

        asymmetric_id = detect_asymmetric_experiment(path, payload)
        if asymmetric_id is not None:
            asymmetric_grouped.setdefault(asymmetric_id, []).append((path, records))
            continue

        if "baseline" not in filename:
            continue

        text = combined_text(path, payload, records)
        model = detect_model(text)
        use_manual = detect_manual(text, records)
        if model not in ("2B", "4B") or use_manual is None:
            continue

        larger_grouped.setdefault((model, use_manual), []).append((path, records))

    print("=" * 78)
    print("LARGER-JUDGE BASELINE COMPLETION CHECK")
    print("A run is complete only with 3,000 unique generated Yes/No records.")
    print("=" * 78)

    larger_complete = True
    for label, model, use_manual in LARGER_RUNS:
        files = larger_grouped.get((model, use_manual), [])
        summary = summarize_files(files)
        print_run(label, files, summary)
        if not summary["complete"]:
            larger_complete = False

    print("")
    print("=" * 78)
    print("ASYMMETRIC TITLE-ONLY JUDGE COMPLETION CHECK")
    print("Pipeline order per chunk: baseline -> statement -> interactive ABA.")
    print("=" * 78)

    asymmetric_complete = True
    asymmetric_summaries = {}
    for label, experiment_id in ASYMMETRIC_RUNS:
        files = asymmetric_grouped.get(experiment_id, [])
        summary = summarize_files(files)
        asymmetric_summaries[experiment_id] = summary
        print_run(label, files, summary)
        if not summary["complete"]:
            asymmetric_complete = False

    print("")
    print("=" * 78)
    if asymmetric_complete:
        print("ASYMMETRIC PIPELINE COMPLETE: do not restart submit_asymmetric.sh.")
    else:
        next_label = next(
            label
            for label, experiment_id in ASYMMETRIC_RUNS
            if not asymmetric_summaries[experiment_id]["complete"]
        )
        print("ASYMMETRIC PIPELINE NEEDS ANOTHER RESUME ROUND.")
        print("Earliest incomplete phase: %s" % next_label)
        print("First ensure no asym_title array is running or pending:")
        print("  squeue -u \"$USER\" -n asym_title")
        print("If that command shows no jobs, restart safely with:")
        print("  sbatch submit_asymmetric.sh")
        print("Do not run overlapping copies; they would write the same checkpoints.")

    if unreadable:
        print("")
        print("WARNING: %d relevant JSON file(s) could not be read:" % len(unreadable))
        for path, error in unreadable:
            print("  - %s: %s" % (path, error))

    print("")
    if larger_complete:
        print("All four larger-judge baseline runs are complete.")
    else:
        print("One or more larger-judge baseline runs still need their own resume job.")

    all_complete = larger_complete and asymmetric_complete and not unreadable
    if all_complete:
        print("ALL SEVEN TRACKED RUNS ARE COMPLETE.")
        return 0

    print("ONE OR MORE TRACKED RUNS ARE INCOMPLETE.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
