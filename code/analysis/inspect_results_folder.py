#!/usr/bin/env python3
"""Compact, read-only audit of JSON files in results/. Python 3.6 compatible."""

import argparse
import collections
import hashlib
import json
import os
import sys


def norm(value):
    if value is None:
        return "<MISSING>"
    return str(value)


def record_key(record):
    return (
        norm(record.get("stage")),
        norm(record.get("pmid")),
        norm(record.get("candidate_tag")),
        norm(record.get("ground_truth")),
    )


def short_hash(value):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def get_path(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def prediction_paths(records):
    paths = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("prediction", "model_prediction"):
            if key in record:
                paths.add(key)
        for key, value in record.items():
            if isinstance(value, dict) and "prediction" in value:
                paths.add(key + ".prediction")
    return sorted(paths)


def infer_family(fields):
    if "judge_BAB_swapped_labels" in fields:
        return "interactive-swapped-labels"
    if "debate_BAB_swapped_labels" in fields:
        return "interactive-swapped-labels"
    if "debate_ABA" in fields or "judge_ABA" in fields:
        return "interactive-dual"
    if "a_turn1" in fields and "b_turn1" in fields:
        return "interactive-single"
    if "pro_argument" in fields and "con_argument" in fields:
        return "statement"
    return "baseline/unknown"


def outcome_summary(records, path):
    counts = collections.Counter()
    correct = 0
    denominator = 0
    for record in records:
        gt = record.get("ground_truth")
        pred = get_path(record, path)
        if pred in ("Yes", "No"):
            counts[pred] += 1
        elif pred is None:
            counts["missing"] += 1
        else:
            counts["invalid"] += 1
        if gt in ("Yes", "No"):
            denominator += 1
            if pred == gt:
                correct += 1
    accuracy = (100.0 * correct / denominator) if denominator else None
    return accuracy, counts


def metadata_text(metadata):
    if not isinstance(metadata, dict):
        return ""
    wanted = (
        "model", "judge_model", "mode", "use_manual", "complete",
        "merged_records", "source_file", "source_results",
    )
    parts = []
    for key in wanted:
        if key not in metadata:
            continue
        value = metadata[key]
        if key in ("source_file", "source_results") and isinstance(value, str):
            value = os.path.basename(value)
        parts.append("%s=%s" % (key, value))
    return ", ".join(parts)


def bab_text_hash(record):
    debate = record.get("debate_BAB")
    if not isinstance(debate, dict):
        return None
    values = [debate.get("b_opening"), debate.get("a_rebuttal"),
              debate.get("b_closing")]
    if not all(isinstance(value, str) and value for value in values):
        return None
    return short_hash(values)


def raw_hash_for_prediction_path(record, path):
    if "." in path:
        parent_name = path.split(".", 1)[0]
        parent = record.get(parent_name)
    else:
        parent = record
    if not isinstance(parent, dict):
        return None
    raw = parent.get("judge_output", parent.get("full_model_output"))
    if not isinstance(raw, str):
        return None
    return short_hash(raw)


def inspect_file(path, show_fields=False):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        raise ValueError("top-level 'results' is not a list")

    fields = set()
    bad_records = 0
    keys = []
    for record in records:
        if isinstance(record, dict):
            fields.update(record.keys())
            keys.append(record_key(record))
        else:
            bad_records += 1

    unique_keys = set(keys)
    key_fingerprint = short_hash(sorted(unique_keys))
    paths = prediction_paths(records)
    outcomes = {}
    for pred_path in paths:
        outcomes[pred_path] = outcome_summary(records, pred_path)

    basename = os.path.basename(path)
    is_swapped = "swapped" in basename.lower()
    swap_data = None
    if is_swapped:
        original_paths = set(("judge_ABA.prediction", "judge_BAB.prediction"))
        added_paths = [item for item in paths if item not in original_paths]
        prediction_maps = {}
        raw_maps = {}
        for pred_path in added_paths:
            prediction_maps[pred_path] = {}
            raw_maps[pred_path] = {}
        bab_hashes = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            key = record_key(record)
            text_hash = bab_text_hash(record)
            if text_hash is not None:
                bab_hashes[key] = text_hash
            for pred_path in added_paths:
                prediction_maps[pred_path][key] = get_path(record, pred_path)
                raw_hash = raw_hash_for_prediction_path(record, pred_path)
                if raw_hash is not None:
                    raw_maps[pred_path][key] = raw_hash
        swap_data = {
            "added_paths": added_paths,
            "predictions": prediction_maps,
            "raw_hashes": raw_maps,
            "bab_hashes": bab_hashes,
        }

    summary = {
        "name": basename,
        "count": len(records),
        "bad_records": bad_records,
        "keys": unique_keys,
        "key_fingerprint": key_fingerprint,
        "duplicate_keys": len(keys) - len(unique_keys),
        "family": infer_family(fields),
        "fields": sorted(fields),
        "paths": paths,
        "outcomes": outcomes,
        "metadata": payload.get("metadata", {}) if isinstance(payload, dict) else {},
        "swap": swap_data,
    }

    print("\n%s" % basename)
    print("  family=%s | records=%d | unique_keys=%d | duplicates=%d | keyset=%s%s" % (
        summary["family"], summary["count"], len(unique_keys),
        summary["duplicate_keys"], key_fingerprint,
        " | non_object_records=%d" % bad_records if bad_records else "",
    ))
    if paths:
        pieces = []
        for pred_path in paths:
            accuracy, counts = outcomes[pred_path]
            acc_text = "n/a" if accuracy is None else "%.2f%%" % accuracy
            invalid = counts["invalid"] + counts["missing"]
            pieces.append("%s: acc=%s Y=%d N=%d invalid=%d" % (
                pred_path, acc_text, counts["Yes"], counts["No"], invalid))
        print("  outcomes: " + " ; ".join(pieces))
    else:
        print("  outcomes: no recognised prediction field")
    meta = metadata_text(summary["metadata"])
    if meta:
        print("  metadata: " + meta)
    if show_fields:
        print("  fields: " + ", ".join(summary["fields"]))
    return summary


def choose_added_path(summary):
    swap = summary.get("swap") or {}
    paths = swap.get("added_paths", [])
    if not paths:
        return None
    preferred = sorted(paths, key=lambda item: (
        0 if "swapped_labels" in item else 1 if "swapped" in item else 2,
        item,
    ))
    return preferred[0]


def compare_swapped(left, right):
    print("\n=== Focused swapped-file check ===")
    print("left:  %s" % left["name"])
    print("right: %s" % right["name"])
    common_keys = left["keys"] & right["keys"]
    only_left = left["keys"] - right["keys"]
    only_right = right["keys"] - left["keys"]
    print("record identities: common=%d only_left=%d only_right=%d" % (
        len(common_keys), len(only_left), len(only_right)))

    left_swap = left.get("swap") or {}
    right_swap = right.get("swap") or {}
    left_bab = left_swap.get("bab_hashes", {})
    right_bab = right_swap.get("bab_hashes", {})
    text_comparable = [key for key in common_keys
                       if key in left_bab and key in right_bab]
    text_same = sum(1 for key in text_comparable
                    if left_bab[key] == right_bab[key])
    print("stored original BAB text: identical=%d/%d" % (
        text_same, len(text_comparable)))

    left_path = choose_added_path(left)
    right_path = choose_added_path(right)
    print("candidate added outcome paths: left=%s | right=%s" % (
        left_path or "NONE", right_path or "NONE"))
    if not left_path or not right_path:
        print("cannot compare added judgments automatically; rerun with --show-fields")
        return

    left_preds = left_swap["predictions"].get(left_path, {})
    right_preds = right_swap["predictions"].get(right_path, {})
    comparable = [key for key in common_keys
                  if left_preds.get(key) in ("Yes", "No")
                  and right_preds.get(key) in ("Yes", "No")]
    same = sum(1 for key in comparable
               if left_preds[key] == right_preds[key])
    flips = len(comparable) - same
    rate = (100.0 * flips / len(comparable)) if comparable else 0.0
    print("added predictions: same=%d | different=%d/%d (%.2f%%)" % (
        same, flips, len(comparable), rate))

    left_raw = left_swap["raw_hashes"].get(left_path, {})
    right_raw = right_swap["raw_hashes"].get(right_path, {})
    raw_comparable = [key for key in common_keys
                      if key in left_raw and key in right_raw]
    raw_same = sum(1 for key in raw_comparable
                   if left_raw[key] == right_raw[key])
    print("raw added judge outputs: byte-identical=%d/%d" % (
        raw_same, len(raw_comparable)))
    if (len(comparable) == len(common_keys) and flips == 0 and
            len(raw_comparable) == len(common_keys) and
            raw_same == len(common_keys)):
        print("takeaway: the two files appear to contain the same added judgments.")
    elif text_same == len(text_comparable) and text_comparable:
        print("takeaway: source BAB content matches, but added judgments are not exact duplicates.")


def main():
    parser = argparse.ArgumentParser(description="Audit result JSON schemas and counts.")
    parser.add_argument("results_dir", nargs="?", default="results")
    parser.add_argument("--show-fields", action="store_true")
    args = parser.parse_args()

    if not os.path.isdir(args.results_dir):
        sys.exit("Not a directory: %s" % args.results_dir)
    paths = sorted(
        os.path.join(args.results_dir, name)
        for name in os.listdir(args.results_dir)
        if name.endswith(".json") and os.path.isfile(os.path.join(args.results_dir, name))
    )
    if not paths:
        sys.exit("No .json files found in %s" % args.results_dir)

    print("Read-only audit: %d JSON files in %s" % (len(paths), args.results_dir))
    summaries = []
    for path in paths:
        try:
            summaries.append(inspect_file(path, args.show_fields))
        except Exception as exc:
            print("\n%s\n  ERROR: %s" % (os.path.basename(path), exc))

    groups = collections.defaultdict(list)
    for summary in summaries:
        groups[summary["key_fingerprint"]].append(summary["name"])
    repeated = [(fingerprint, names) for fingerprint, names in groups.items()
                if len(names) > 1]
    print("\n=== Identical record-identity sets ===")
    if not repeated:
        print("none")
    else:
        for fingerprint, names in sorted(repeated):
            print("%s: %s" % (fingerprint, ", ".join(sorted(names))))

    by_name = dict((summary["name"], summary) for summary in summaries)
    first_name = "interactive_results_BAB_swapped_full.json"
    second_name = "interactive_results_BAB_swapped_labels_full.json"
    if first_name in by_name and second_name in by_name:
        compare_swapped(by_name[first_name], by_name[second_name])
    else:
        print("\nFocused swapped-file check skipped: one or both named files are absent.")

    missing_pydantic_interactive = (
        "pydantic_interactive_results_full.json" not in by_name
    )
    if missing_pydantic_interactive:
        print("\nNOTE: pydantic_interactive_results_full.json is absent.")


if __name__ == "__main__":
    main()
