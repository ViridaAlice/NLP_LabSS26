#!/usr/bin/env python3
"""Merge and validate resumable BAB swapped-label result chunks.

Compatible with Python 3.6+. The source file is never modified.
"""

import argparse
import glob
import io
import json
import os
import sys
import tempfile


DEFAULT_PATTERNS = [
    "interactive_results_BAB_swapped_chunk*.json",
    "interactive_results_bab_swapped_chunk*.json",
    "*BAB*swapped*chunk*.json",
    "*bab*swapped*chunk*.json",
    "*BAB*label*chunk*.json",
    "*bab*label*chunk*.json",
]

SWAPPED_JUDGE_FIELDS = [
    "judge_BAB_swapped_labels",
    "judge_BAB_label_swapped",
    "judge_BAB_swapped",
    "judge_BAB_relabelled",
    "judge_BAB_relabeled",
    "judge_swapped",
    "swapped_judge_BAB",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Merge swapped-label result chunks and check completeness."
    )
    parser.add_argument("--input-dir", default=".", help="Directory containing chunk JSON files.")
    parser.add_argument("--source", required=True, help="Original interactive_results_full.json.")
    parser.add_argument("--output", required=True, help="New merged output JSON file.")
    parser.add_argument(
        "--pattern",
        action="append",
        default=None,
        help="Chunk filename glob. May be supplied more than once.",
    )
    parser.add_argument(
        "--swapped-judge-field",
        default=None,
        help="Exact field containing the new swapped-label judgment.",
    )
    return parser.parse_args()


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_results(data, path):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    raise ValueError("{} does not contain a JSON list or a 'results' list".format(path))


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def record_key(record):
    stage = normalize_text(record.get("stage"))
    pmid = normalize_text(record.get("pmid"))
    candidate = normalize_text(record.get("candidate_tag"))
    if not stage or not pmid:
        return None
    return (stage, pmid, candidate)


def key_as_dict(key):
    return {"stage": key[0], "pmid": key[1], "candidate_tag": key[2]}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prediction_is_valid(judgment):
    if not isinstance(judgment, dict):
        return False
    prediction = normalize_text(judgment.get("prediction")).lower()
    return prediction in ("yes", "no")


def find_swapped_judgment(record, explicit_field=None):
    if explicit_field:
        value = record.get(explicit_field)
        return explicit_field, value

    for field in SWAPPED_JUDGE_FIELDS:
        if field in record:
            return field, record.get(field)

    candidates = []
    for field, value in record.items():
        lower = field.lower()
        if field in ("judge_ABA", "judge_BAB"):
            continue
        if isinstance(value, dict) and "judge" in lower:
            if "swap" in lower or "relabel" in lower or "label" in lower:
                candidates.append((field, value))

    if len(candidates) == 1:
        return candidates[0]

    # Also support minimal chunk records whose new judgment is called simply "judge".
    if isinstance(record.get("judge"), dict):
        return "judge", record.get("judge")

    # Also support a judgment stored directly at the top level.
    if normalize_text(record.get("prediction")).lower() in ("yes", "no"):
        return ".", record

    return None, None


def atomic_write_json(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    fd, temporary = tempfile.mkstemp(prefix=".merge_tmp_", suffix=".json", dir=directory)
    try:
        with io.open(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def discover_chunk_files(input_dir, patterns, source, output):
    found = []
    for pattern in patterns:
        found.extend(glob.glob(os.path.join(input_dir, pattern)))

    excluded = set([os.path.abspath(source), os.path.abspath(output)])
    unique = []
    seen = set()
    for path in sorted(found):
        absolute = os.path.abspath(path)
        if absolute in excluded or absolute in seen or not os.path.isfile(path):
            continue
        seen.add(absolute)
        unique.append(path)
    return unique


def main():
    args = parse_args()
    patterns = args.pattern if args.pattern else DEFAULT_PATTERNS

    if not os.path.isfile(args.source):
        sys.exit("ERROR: source file not found: {}".format(args.source))

    chunk_files = discover_chunk_files(
        args.input_dir, patterns, args.source, args.output
    )
    if not chunk_files:
        print("ERROR: no chunk files found in {}.".format(args.input_dir), file=sys.stderr)
        print("Patterns searched:", file=sys.stderr)
        for pattern in patterns:
            print("  {}".format(pattern), file=sys.stderr)
        print("Use --pattern 'YOUR_CHUNK_PREFIX_chunk*.json' if necessary.", file=sys.stderr)
        return 1

    try:
        source_data = load_json(args.source)
        source_results = get_results(source_data, args.source)
    except Exception as exc:
        print("ERROR reading source: {}".format(exc), file=sys.stderr)
        return 1

    source_order = []
    source_map = {}
    source_duplicate_keys = []
    source_invalid_records = 0
    for record in source_results:
        key = record_key(record)
        if key is None:
            source_invalid_records += 1
            continue
        if key in source_map:
            source_duplicate_keys.append(key)
            continue
        source_map[key] = record
        source_order.append(key)

    merged_map = {}
    record_source_file = {}
    identical_duplicates = 0
    conflicts = []
    unreadable_files = []
    invalid_key_records = []
    per_file_counts = {}

    for path in chunk_files:
        try:
            records = get_results(load_json(path), path)
        except Exception as exc:
            unreadable_files.append({"file": path, "error": str(exc)})
            continue

        per_file_counts[os.path.basename(path)] = len(records)
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                invalid_key_records.append({"file": path, "index": index, "reason": "not an object"})
                continue
            key = record_key(record)
            if key is None:
                invalid_key_records.append({"file": path, "index": index, "reason": "missing stage or pmid"})
                continue
            if key in merged_map:
                if canonical_json(merged_map[key]) == canonical_json(record):
                    identical_duplicates += 1
                else:
                    conflicts.append({
                        "key": key_as_dict(key),
                        "first_file": record_source_file[key],
                        "second_file": path,
                    })
                continue
            merged_map[key] = record
            record_source_file[key] = path

    source_keys = set(source_map.keys())
    merged_keys = set(merged_map.keys())
    missing_keys = [key for key in source_order if key not in merged_keys]
    unexpected_keys = sorted(merged_keys - source_keys)

    invalid_judgments = []
    detected_fields = {}
    for key in source_order:
        if key not in merged_map:
            continue
        field, judgment = find_swapped_judgment(
            merged_map[key], args.swapped_judge_field
        )
        if field:
            detected_fields[field] = detected_fields.get(field, 0) + 1
        if not prediction_is_valid(judgment):
            invalid_judgments.append(key)

    # Keep source order so the merged file aligns with interactive_results_full.json.
    merged_results = [merged_map[key] for key in source_order if key in merged_map]
    merged_results.extend(merged_map[key] for key in unexpected_keys)

    complete = (
        len(source_duplicate_keys) == 0
        and source_invalid_records == 0
        and len(unreadable_files) == 0
        and len(invalid_key_records) == 0
        and len(conflicts) == 0
        and len(missing_keys) == 0
        and len(unexpected_keys) == 0
        and len(invalid_judgments) == 0
        and len(merged_results) == len(source_results)
    )

    metadata = {
        "experiment": "BAB debate with A/B presentation labels swapped",
        "complete": complete,
        "source_file": os.path.abspath(args.source),
        "source_records": len(source_results),
        "unique_source_records": len(source_map),
        "merged_records": len(merged_results),
        "matched_source_records": len(source_keys & merged_keys),
        "chunk_files": [os.path.abspath(path) for path in chunk_files],
        "records_per_chunk_file": per_file_counts,
        "detected_swapped_judge_fields": detected_fields,
        "missing_count": len(missing_keys),
        "unexpected_count": len(unexpected_keys),
        "invalid_judgment_count": len(invalid_judgments),
        "conflicting_duplicate_count": len(conflicts),
        "identical_duplicate_count": identical_duplicates,
        "unreadable_file_count": len(unreadable_files),
    }

    validation = {
        "missing_records": [key_as_dict(key) for key in missing_keys],
        "unexpected_records": [key_as_dict(key) for key in unexpected_keys],
        "invalid_judgment_records": [key_as_dict(key) for key in invalid_judgments],
        "conflicting_duplicates": conflicts,
        "invalid_key_records": invalid_key_records,
        "unreadable_files": unreadable_files,
        "source_duplicate_records": [key_as_dict(key) for key in source_duplicate_keys],
        "source_invalid_record_count": source_invalid_records,
    }

    atomic_write_json(args.output, {
        "metadata": metadata,
        "validation": validation,
        "results": merged_results,
    })

    print("\n==== SWAPPED-LABEL CHUNK MERGE ====")
    print("Chunk files read:          {}".format(len(chunk_files)))
    print("Expected source records:   {}".format(len(source_results)))
    print("Merged records:            {}".format(len(merged_results)))
    print("Missing records:           {}".format(len(missing_keys)))
    print("Unexpected records:        {}".format(len(unexpected_keys)))
    print("Invalid judgments:         {}".format(len(invalid_judgments)))
    print("Conflicting duplicates:    {}".format(len(conflicts)))
    print("Identical duplicates:      {}".format(identical_duplicates))
    print("Judge fields found:        {}".format(detected_fields))
    print("Complete:                  {}".format("YES" if complete else "NO"))
    print("Merged output:             {}".format(args.output))

    if missing_keys:
        print("\nFirst missing records:")
        for key in missing_keys[:10]:
            print("  stage={!r}, pmid={!r}, tag={!r}".format(key[0], key[1], key[2]))
    if invalid_judgments:
        print("\nFirst records with missing/invalid swapped judgments:")
        for key in invalid_judgments[:10]:
            print("  stage={!r}, pmid={!r}, tag={!r}".format(key[0], key[1], key[2]))

    # Nonzero status makes an incomplete run easy to detect in shell scripts.
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
