#!/usr/bin/env python3

import glob
import json
import os
import re
import sys

EXPECTED = 3000
RESULTS_DIR = "results"

RUNS = [
    ("Qwen3.5-2B without manual", "2B", False),
    ("Qwen3.5-2B with manual",    "2B", True),
    ("Qwen3.5-4B without manual", "4B", False),
    ("Qwen3.5-4B with manual",    "4B", True),
]


def normalize(value):
    return str(value or "").strip().lower().replace("\\", "/")


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


def combined_text(path, payload, records):
    pieces = [path]

    if isinstance(payload, dict):
        metadata = payload.get("metadata", {})
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                if isinstance(value, (str, int, float, bool)):
                    pieces.append("%s=%s" % (key, value))

        for key in (
            "judge_model",
            "judge_model_id",
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
    # Prefer the explicit record field.
    values = set()
    for record in records:
        if isinstance(record, dict) and "use_manual" in record:
            value = record.get("use_manual")
            if isinstance(value, bool):
                values.add(value)
            elif normalize(value) in ("true", "1", "yes"):
                values.add(True)
            elif normalize(value) in ("false", "0", "no"):
                values.add(False)

    if len(values) == 1:
        return list(values)[0]

    compact = re.sub(r"[^a-z0-9]+", "", text)

    if (
        "nomanual" in compact
        or "withoutmanual" in compact
        or "usemanualfalse" in compact
    ):
        return False

    if (
        "withmanual" in compact
        or "usemanualtrue" in compact
    ):
        return True

    return None


def record_key(record):
    if not isinstance(record, dict):
        return None

    stage = normalize(record.get("stage"))
    pmid = normalize(record.get("pmid"))
    candidate = normalize(record.get("candidate_tag"))
    ground_truth = normalize(record.get("ground_truth"))

    # Candidate and ground truth prevent accidental collisions.
    if not stage or not pmid:
        return None

    return (stage, pmid, candidate, ground_truth)


def record_is_generated(record):
    if not isinstance(record, dict):
        return False

    prediction = normalize(
        record.get("prediction", record.get("model_prediction", ""))
    )

    return prediction in ("yes", "no")


def main():
    patterns = [
        os.path.join(RESULTS_DIR, "*.json"),
        os.path.join(RESULTS_DIR, "**", "*.json"),
    ]

    paths = set()
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            if os.path.isfile(path):
                paths.add(path)

    grouped = {}
    unreadable = []

    for path in sorted(paths):
        filename = normalize(os.path.basename(path))

        # Ignore original 0.8B and unrelated experiment results early.
        if "baseline" not in filename:
            continue

        payload, error = load_json(path)
        if error is not None:
            unreadable.append((path, error))
            continue

        records = extract_results(payload)
        if records is None:
            continue

        text = combined_text(path, payload, records)
        model = detect_model(text)
        use_manual = detect_manual(text, records)

        if model not in ("2B", "4B") or use_manual is None:
            continue

        key = (model, use_manual)
        grouped.setdefault(key, []).append((path, records))

    all_complete = True

    print("=" * 78)
    print("LARGER-JUDGE BASELINE COMPLETION CHECK")
    print("A run is complete only with 3,000 unique generated Yes/No records.")
    print("=" * 78)

    for label, model, use_manual in RUNS:
        files = grouped.get((model, use_manual), [])
        keys = set()
        raw_count = 0
        invalid_count = 0
        duplicate_count = 0

        for path, records in files:
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
        complete = unique_count == EXPECTED

        if complete:
            status = "COMPLETE"
        elif unique_count < EXPECTED:
            status = "RE-RUN / RESUME (%d missing)" % (EXPECTED - unique_count)
            all_complete = False
        else:
            status = "CHECK OUTPUT (%d unexpected extra records)" % (
                unique_count - EXPECTED
            )
            all_complete = False

        print("")
        print(label)
        print("  Status:            %s" % status)
        print("  Unique generated:  %d / %d" % (unique_count, EXPECTED))
        print("  Matching files:    %d" % len(files))
        print("  Raw records:       %d" % raw_count)
        print("  Invalid records:   %d" % invalid_count)
        print("  Duplicate records: %d" % duplicate_count)

        if not files:
            print("  Warning: no matching result files found")
        else:
            for path, records in files:
                print("    - %s (%d records)" % (path, len(records)))

    print("")
    print("=" * 78)

    if unreadable:
        print("WARNING: %d baseline JSON file(s) could not be read:" % len(unreadable))
        for path, error in unreadable:
            print("  - %s: %s" % (path, error))
        all_complete = False

    if all_complete:
        print("ALL FOUR RUNS ARE COMPLETE.")
        return 0

    print("ONE OR MORE RUNS NEED TO BE RE-RUN OR RESUMED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
