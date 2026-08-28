#!/usr/bin/env python3
"""Compare original BAB judgments with judgments after swapping A/B labels.

Compatible with Python 3.6+. Requires only the Python standard library.
"""

import argparse
import csv
import io
import json
import math
import os
import sys
import tempfile


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
        description="Compare original BAB and swapped-A/B-label judge results."
    )
    parser.add_argument("--original", required=True, help="Original interactive_results_full.json.")
    parser.add_argument("--swapped", required=True, help="Merged swapped-label results JSON.")
    parser.add_argument("--output-dir", default="comparison_BAB_label_swap")
    parser.add_argument("--original-judge-field", default="judge_BAB")
    parser.add_argument(
        "--swapped-judge-field",
        default=None,
        help="New judge-result field. Normally detected automatically.",
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


def text(value):
    if value is None:
        return ""
    return str(value).strip()


def key_for(record):
    stage = text(record.get("stage"))
    pmid = text(record.get("pmid"))
    tag = text(record.get("candidate_tag"))
    if not stage or not pmid:
        return None
    return (stage, pmid, tag)


def key_dict(key):
    return {"stage": key[0], "pmid": key[1], "candidate_tag": key[2]}


def index_records(records, label):
    result = {}
    duplicates = []
    invalid = 0
    order = []
    for record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        key = key_for(record)
        if key is None:
            invalid += 1
            continue
        if key in result:
            duplicates.append(key)
            continue
        result[key] = record
        order.append(key)
    if duplicates:
        raise ValueError("{} contains {} duplicate record keys".format(label, len(duplicates)))
    if invalid:
        raise ValueError("{} contains {} records without stage/pmid".format(label, invalid))
    return result, order


def normalize_prediction(value):
    value = text(value).lower()
    if value == "yes":
        return "Yes"
    if value == "no":
        return "No"
    return None


def find_swapped_field(records, explicit=None):
    if explicit:
        return explicit

    counts = {}
    for record in records:
        for field in SWAPPED_JUDGE_FIELDS:
            if isinstance(record.get(field), dict):
                counts[field] = counts.get(field, 0) + 1
        for field, value in record.items():
            lower = field.lower()
            if field in ("judge_ABA", "judge_BAB"):
                continue
            if isinstance(value, dict) and "judge" in lower:
                if "swap" in lower or "relabel" in lower or "label" in lower:
                    counts[field] = counts.get(field, 0) + 1
        if isinstance(record.get("judge"), dict):
            counts["judge"] = counts.get("judge", 0) + 1

    if counts:
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    direct_count = sum(
        1 for record in records
        if normalize_prediction(record.get("prediction")) is not None
    )
    if direct_count:
        return "."

    available = set()
    for record in records[:20]:
        available.update(record.keys())
    raise ValueError(
        "Could not detect the swapped judge field. Available fields include: {}. "
        "Use --swapped-judge-field FIELD.".format(", ".join(sorted(available)))
    )


def judgment_from(record, field):
    if field == ".":
        return record
    value = record.get(field)
    return value if isinstance(value, dict) else None


def nested_number(judgment, *path):
    value = judgment
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def mean(values):
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / float(len(clean))


def percent(part, total):
    if not total:
        return None
    return 100.0 * part / float(total)


def exact_mcnemar_p(original_only_correct, swapped_only_correct):
    """Two-sided exact McNemar/binomial p-value, without SciPy."""
    n = original_only_correct + swapped_only_correct
    if n == 0:
        return 1.0
    k = min(original_only_correct, swapped_only_correct)
    log_terms = []
    for i in range(k + 1):
        log_probability = (
            math.lgamma(n + 1.0)
            - math.lgamma(i + 1.0)
            - math.lgamma(n - i + 1.0)
            - n * math.log(2.0)
        )
        log_terms.append(log_probability)
    maximum = max(log_terms)
    log_sum = maximum + math.log(sum(math.exp(value - maximum) for value in log_terms))
    p_value = 2.0 * math.exp(log_sum)
    return min(1.0, p_value)


def selected_content_speaker(record, prediction):
    wanted_side = "PRO" if prediction == "Yes" else "CON"
    a_side = text(record.get("a_side")).upper()
    b_side = text(record.get("b_side")).upper()
    if a_side == wanted_side:
        return "A"
    if b_side == wanted_side:
        return "B"
    # Fall back to a_is_pro if explicit sides are unavailable.
    if isinstance(record.get("a_is_pro"), bool):
        a_is_pro = record.get("a_is_pro")
        if (prediction == "Yes" and a_is_pro) or (prediction == "No" and not a_is_pro):
            return "A"
        return "B"
    return None


def inverted_label(content_speaker):
    if content_speaker == "A":
        return "B"
    if content_speaker == "B":
        return "A"
    return None


def group_statistics(rows):
    n = len(rows)
    original_correct = sum(1 for row in rows if row["original_correct"])
    swapped_correct = sum(1 for row in rows if row["swapped_correct"])
    flips = sum(1 for row in rows if row["prediction_changed"])
    original_yes = sum(1 for row in rows if row["original_prediction"] == "Yes")
    swapped_yes = sum(1 for row in rows if row["swapped_prediction"] == "Yes")
    original_a_wins = sum(1 for row in rows if row["original_displayed_winner"] == "A")
    swapped_a_wins = sum(1 for row in rows if row["swapped_displayed_winner"] == "A")
    return {
        "n": n,
        "original_accuracy_percent": percent(original_correct, n),
        "swapped_accuracy_percent": percent(swapped_correct, n),
        "accuracy_delta_percentage_points": percent(swapped_correct - original_correct, n),
        "prediction_flip_rate_percent": percent(flips, n),
        "original_yes_rate_percent": percent(original_yes, n),
        "swapped_yes_rate_percent": percent(swapped_yes, n),
        "yes_rate_delta_percentage_points": percent(swapped_yes - original_yes, n),
        "original_displayed_A_win_rate_percent": percent(original_a_wins, n),
        "swapped_displayed_A_win_rate_percent": percent(swapped_a_wins, n),
    }


def grouped(rows, field):
    buckets = {}
    for row in rows:
        value = row.get(field) or "Unknown"
        buckets.setdefault(value, []).append(row)
    return dict((name, group_statistics(items)) for name, items in sorted(buckets.items()))


def atomic_json(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    fd, temporary = tempfile.mkstemp(prefix=".compare_tmp_", suffix=".json", dir=directory)
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


def write_csv(path, rows):
    fields = [
        "pmid", "stage", "candidate_tag", "ground_truth", "a_side", "b_side",
        "original_prediction", "swapped_prediction", "prediction_changed",
        "original_correct", "swapped_correct", "correctness_changed",
        "original_content_winner", "swapped_content_winner",
        "original_displayed_winner", "swapped_displayed_winner",
        "original_verdict_prob_belongs", "swapped_verdict_prob_belongs",
        "verdict_prob_delta",
        "original_boolean_prob_true", "swapped_boolean_prob_true",
        "boolean_prob_delta",
        "original_prob_displayed_A_right", "swapped_prob_displayed_A_right",
        "displayed_A_probability_delta",
        "original_prob_content_B_right", "swapped_prob_content_B_right",
        "content_B_probability_delta",
    ]
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    args = parse_args()
    try:
        original_records = get_results(load_json(args.original), args.original)
        swapped_records = get_results(load_json(args.swapped), args.swapped)
        original_map, original_order = index_records(original_records, "original file")
        swapped_map, unused_order = index_records(swapped_records, "swapped file")
        swapped_field = find_swapped_field(swapped_records, args.swapped_judge_field)
    except Exception as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1

    original_keys = set(original_map.keys())
    swapped_keys = set(swapped_map.keys())
    missing = [key for key in original_order if key not in swapped_keys]
    unexpected = sorted(swapped_keys - original_keys)
    matched_keys = [key for key in original_order if key in swapped_keys]

    rows = []
    invalid = []
    for key in matched_keys:
        original_record = original_map[key]
        swapped_record = swapped_map[key]
        original_judgment = judgment_from(original_record, args.original_judge_field)
        swapped_judgment = judgment_from(swapped_record, swapped_field)
        original_prediction = normalize_prediction(
            original_judgment.get("prediction") if original_judgment else None
        )
        swapped_prediction = normalize_prediction(
            swapped_judgment.get("prediction") if swapped_judgment else None
        )
        ground_truth = normalize_prediction(original_record.get("ground_truth"))
        if not original_prediction or not swapped_prediction or not ground_truth:
            invalid.append(key)
            continue

        original_correct = original_prediction == ground_truth
        swapped_correct = swapped_prediction == ground_truth
        original_content_winner = selected_content_speaker(original_record, original_prediction)
        swapped_content_winner = selected_content_speaker(original_record, swapped_prediction)

        original_verdict = nested_number(original_judgment, "confidence", "verdict_prob_belongs")
        swapped_verdict = nested_number(swapped_judgment, "confidence", "verdict_prob_belongs")
        original_boolean = nested_number(original_judgment, "confidence", "boolean_prob_true")
        swapped_boolean = nested_number(swapped_judgment, "confidence", "boolean_prob_true")
        original_p_a = nested_number(original_judgment, "confidence", "debater_prob_A_right")
        swapped_p_a = nested_number(swapped_judgment, "confidence", "debater_prob_A_right")

        # In the original BAB transcript, displayed A is original content A.
        # In the swapped transcript, displayed A is original content B.
        original_content_b_prob = None if original_p_a is None else 1.0 - original_p_a
        swapped_content_b_prob = swapped_p_a

        row = {
            "pmid": key[1],
            "stage": key[0],
            "candidate_tag": key[2],
            "ground_truth": ground_truth,
            "a_side": text(original_record.get("a_side")),
            "b_side": text(original_record.get("b_side")),
            "original_prediction": original_prediction,
            "swapped_prediction": swapped_prediction,
            "prediction_changed": original_prediction != swapped_prediction,
            "original_correct": original_correct,
            "swapped_correct": swapped_correct,
            "correctness_changed": original_correct != swapped_correct,
            "original_content_winner": original_content_winner,
            "swapped_content_winner": swapped_content_winner,
            "original_displayed_winner": original_content_winner,
            "swapped_displayed_winner": inverted_label(swapped_content_winner),
            "original_verdict_prob_belongs": original_verdict,
            "swapped_verdict_prob_belongs": swapped_verdict,
            "verdict_prob_delta": None if original_verdict is None or swapped_verdict is None else swapped_verdict - original_verdict,
            "original_boolean_prob_true": original_boolean,
            "swapped_boolean_prob_true": swapped_boolean,
            "boolean_prob_delta": None if original_boolean is None or swapped_boolean is None else swapped_boolean - original_boolean,
            "original_prob_displayed_A_right": original_p_a,
            "swapped_prob_displayed_A_right": swapped_p_a,
            "displayed_A_probability_delta": None if original_p_a is None or swapped_p_a is None else swapped_p_a - original_p_a,
            "original_prob_content_B_right": original_content_b_prob,
            "swapped_prob_content_B_right": swapped_content_b_prob,
            "content_B_probability_delta": None if original_content_b_prob is None or swapped_content_b_prob is None else swapped_content_b_prob - original_content_b_prob,
        }
        rows.append(row)

    n = len(rows)
    original_correct_count = sum(1 for row in rows if row["original_correct"])
    swapped_correct_count = sum(1 for row in rows if row["swapped_correct"])
    both_correct = sum(1 for row in rows if row["original_correct"] and row["swapped_correct"])
    original_only = sum(1 for row in rows if row["original_correct"] and not row["swapped_correct"])
    swapped_only = sum(1 for row in rows if not row["original_correct"] and row["swapped_correct"])
    both_wrong = n - both_correct - original_only - swapped_only
    no_to_yes = sum(1 for row in rows if row["original_prediction"] == "No" and row["swapped_prediction"] == "Yes")
    yes_to_no = sum(1 for row in rows if row["original_prediction"] == "Yes" and row["swapped_prediction"] == "No")

    original_p_a_values = [row["original_prob_displayed_A_right"] for row in rows]
    swapped_p_a_values = [row["swapped_prob_displayed_A_right"] for row in rows]
    content_b_deltas = [row["content_B_probability_delta"] for row in rows]

    summary = {
        "files": {
            "original": os.path.abspath(args.original),
            "swapped": os.path.abspath(args.swapped),
            "original_judge_field": args.original_judge_field,
            "swapped_judge_field": swapped_field,
        },
        "coverage": {
            "original_records": len(original_records),
            "swapped_records": len(swapped_records),
            "matched_valid_records": n,
            "missing_swapped_count": len(missing),
            "unexpected_swapped_count": len(unexpected),
            "invalid_matched_count": len(invalid),
            "complete": len(missing) == 0 and len(unexpected) == 0 and len(invalid) == 0,
        },
        "overall": group_statistics(rows),
        "prediction_changes": {
            "same_prediction": n - no_to_yes - yes_to_no,
            "changed_prediction": no_to_yes + yes_to_no,
            "No_to_Yes": no_to_yes,
            "Yes_to_No": yes_to_no,
        },
        "paired_accuracy": {
            "both_correct": both_correct,
            "original_correct_swapped_wrong": original_only,
            "original_wrong_swapped_correct": swapped_only,
            "both_wrong": both_wrong,
            "mcnemar_exact_two_sided_p": exact_mcnemar_p(original_only, swapped_only),
        },
        "confidence": {
            "mean_original_prob_displayed_A_right": mean(original_p_a_values),
            "mean_swapped_prob_displayed_A_right": mean(swapped_p_a_values),
            "mean_displayed_A_probability_delta": mean([
                row["displayed_A_probability_delta"] for row in rows
            ]),
            "mean_original_prob_content_B_right": mean([
                row["original_prob_content_B_right"] for row in rows
            ]),
            "mean_swapped_prob_content_B_right": mean([
                row["swapped_prob_content_B_right"] for row in rows
            ]),
            "mean_content_B_probability_delta_after_being_renamed_A": mean(content_b_deltas),
            "interpretation": (
                "For content-B support, original P(B right) is 1-P(A right); "
                "after relabeling, the same content B is displayed as A, so its support is P(A right)."
            ),
        },
        "by_stage": grouped(rows, "stage"),
        "by_ground_truth": grouped(rows, "ground_truth"),
        "by_original_b_side": grouped(rows, "b_side"),
        "validation": {
            "missing_swapped_records": [key_dict(key) for key in missing],
            "unexpected_swapped_records": [key_dict(key) for key in unexpected],
            "invalid_matched_records": [key_dict(key) for key in invalid],
        },
    }

    if not os.path.isdir(args.output_dir):
        os.makedirs(args.output_dir)
    summary_path = os.path.join(args.output_dir, "summary.json")
    csv_path = os.path.join(args.output_dir, "record_comparison.csv")
    atomic_json(summary_path, summary)
    write_csv(csv_path, rows)

    overall = summary["overall"]
    print("\n==== ORIGINAL BAB vs SWAPPED A/B LABELS ====")
    print("Swapped judge field:       {}".format(swapped_field))
    print("Matched valid records:     {}".format(n))
    print("Missing swapped records:   {}".format(len(missing)))
    print("Invalid matched records:   {}".format(len(invalid)))
    print("Original accuracy:         {:.3f}%".format(overall["original_accuracy_percent"] or 0.0))
    print("Swapped-label accuracy:    {:.3f}%".format(overall["swapped_accuracy_percent"] or 0.0))
    print("Accuracy change:           {:+.3f} percentage points".format(overall["accuracy_delta_percentage_points"] or 0.0))
    print("Prediction flip rate:      {:.3f}%".format(overall["prediction_flip_rate_percent"] or 0.0))
    print("No -> Yes:                 {}".format(no_to_yes))
    print("Yes -> No:                 {}".format(yes_to_no))
    print("McNemar exact p-value:     {:.6g}".format(summary["paired_accuracy"]["mcnemar_exact_two_sided_p"]))
    print("Original displayed-A wins: {:.3f}%".format(overall["original_displayed_A_win_rate_percent"] or 0.0))
    print("Swapped displayed-A wins:  {:.3f}%".format(overall["swapped_displayed_A_win_rate_percent"] or 0.0))
    print("Summary JSON:              {}".format(summary_path))
    print("Record-level CSV:          {}".format(csv_path))

    return 0 if summary["coverage"]["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
