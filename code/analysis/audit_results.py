#!/usr/bin/env python3
"""Concise, dependency-free audit of JSON files in results/.

Compatible with Python 3.6+. It does not modify result files.
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict


def parse_args():
    parser = argparse.ArgumentParser(description="Audit result JSON files.")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--expected", type=int, default=3000)
    parser.add_argument("--output", default="")
    return parser.parse_args()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_results_hash(results):
    raw = json.dumps(
        results, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def record_key(record):
    return (str(record.get("stage")), str(record.get("pmid")))


def prediction_paths(records):
    paths = set()
    for record in records:
        if "prediction" in record:
            paths.add("prediction")
        if "model_prediction" in record:
            paths.add("model_prediction")
        for key, value in record.items():
            if key.startswith("judge_") and isinstance(value, dict):
                if "prediction" in value:
                    paths.add(key + ".prediction")
    return sorted(paths)


def get_path(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def audit_file(path, expected):
    payload = load_json(path)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("results", [])
    else:
        raise ValueError("top-level JSON must be an object or list")
    if not isinstance(records, list):
        raise ValueError("'results' is not a list")

    keys = [record_key(r) for r in records if isinstance(r, dict)]
    key_counts = Counter(keys)
    unique = len(key_counts)
    duplicates = sum(count - 1 for count in key_counts.values() if count > 1)
    stages = Counter(str(r.get("stage")) for r in records if isinstance(r, dict))

    predictions = {}
    for pred_path in prediction_paths(records):
        literal_unknown = 0
        invalid_or_missing = 0
        yes = 0
        no = 0
        for record in records:
            value = get_path(record, pred_path) if isinstance(record, dict) else None
            normalized = str(value).strip().lower() if value is not None else ""
            if normalized == "yes":
                yes += 1
            elif normalized == "no":
                no += 1
            else:
                invalid_or_missing += 1
                if normalized == "unknown":
                    literal_unknown += 1
        predictions[pred_path] = {
            "yes": yes,
            "no": no,
            "unknown": literal_unknown,
            "invalid": invalid_or_missing,
        }

    all_valid = bool(predictions) and all(
        item["invalid"] == 0 for item in predictions.values()
    )
    complete = (
        len(records) == expected
        and unique == expected
        and duplicates == 0
        and all_valid
    )

    return {
        "name": os.path.basename(path),
        "records": len(records),
        "unique": unique,
        "missing": max(0, expected - unique),
        "duplicates": duplicates,
        "stages": stages,
        "predictions": predictions,
        "complete": complete,
        "file_hash": sha256_file(path),
        "results_hash": normalized_results_hash(records),
    }


def esc(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def prediction_summary(item):
    if not item["predictions"]:
        return "No prediction field detected"
    parts = []
    for path in sorted(item["predictions"]):
        stats = item["predictions"][path]
        if stats["invalid"] == stats["unknown"]:
            parts.append("{}: {} Unknown".format(path, stats["unknown"]))
        else:
            parts.append(
                "{}: {} Unknown; {} invalid/missing total".format(
                    path, stats["unknown"], stats["invalid"]
                )
            )
    return "; ".join(parts)


def duplicate_sections(items):
    sections = []
    for title, field in (
        ("Byte-identical files", "file_hash"),
        ("Identical normalized `results` arrays", "results_hash"),
    ):
        groups = defaultdict(list)
        for item in items:
            groups[item[field]].append(item["name"])
        duplicates = [sorted(names) for names in groups.values() if len(names) > 1]
        sections.append("## {}\n".format(title))
        if duplicates:
            for names in sorted(duplicates):
                sections.append("- " + ", ".join("`{}`".format(n) for n in names))
        else:
            sections.append("- None detected.")
        sections.append("")
    return sections


def render(items, errors, expected):
    lines = [
        "# Completion audit",
        "",
        "Expected: **{} unique `(stage, pmid)` records per file**.".format(expected),
        "",
        "| File | Records | Unique | Missing | Duplicates | Unknown / invalid predictions | Status |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for item in items:
        lines.append(
            "| `{}` | {:,} | {:,} | {:,} | {:,} | {} | {} |".format(
                esc(item["name"]),
                item["records"],
                item["unique"],
                item["missing"],
                item["duplicates"],
                esc(prediction_summary(item)),
                "Complete" if item["complete"] else "**Needs attention**",
            )
        )

    lines.extend(["", "## Stage counts", ""])
    for item in items:
        stage_text = "; ".join(
            "{}={}".format(stage, count)
            for stage, count in sorted(item["stages"].items())
        )
        lines.append("- `{}`: {}".format(item["name"], stage_text or "none"))
    lines.append("")
    lines.extend(duplicate_sections(items))

    if errors:
        lines.extend(["## Files that could not be audited", ""])
        for name, message in errors:
            lines.append("- `{}`: {}".format(name, message))
        lines.append("")

    lines.extend([
        "## Interpretation",
        "",
        "- **Complete** requires exactly {} records, {} unique keys, no duplicate keys, and only Yes/No in every detected prediction path.".format(expected, expected),
        "- `Unknown` is reported separately, while `invalid/missing total` also includes absent, null, or non-binary values.",
        "- For interactive files, each `judge_*` path is audited independently.",
        "- A normalized duplicate has the same `results` content even if metadata or JSON formatting differs.",
        "",
    ])
    return "\n".join(lines)


def main():
    args = parse_args()
    if not os.path.isdir(args.results_dir):
        sys.exit("Results directory not found: {}".format(args.results_dir))

    names = sorted(
        name for name in os.listdir(args.results_dir)
        if name.lower().endswith(".json")
    )
    items = []
    errors = []
    for name in names:
        path = os.path.join(args.results_dir, name)
        try:
            items.append(audit_file(path, args.expected))
        except Exception as exc:
            errors.append((name, str(exc)))

    report = render(items, errors, args.expected)
    print(report)
    if args.output:
        parent = os.path.dirname(os.path.abspath(args.output))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(report)
        print("\nWrote {}".format(args.output))


if __name__ == "__main__":
    main()
