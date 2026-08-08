#!/usr/bin/env python3
"""Compare original BAB judgments with judgments of identical text under swapped A/B labels.

No third-party Python packages are required. The script writes:
  * <output-prefix>.json: aggregate and per-stage statistics
  * <output-prefix>.csv: one paired row per matched example

Example:
    python3 compare_bab_label_swap.py \
      --original interactive_results_full.json \
      --swapped bab_swapped_results_full.json \
      --output-prefix bab_label_swap_comparison
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


AUTO_SWAPPED_JUDGE_FIELDS = (
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
        description="Paired comparison of original BAB and A/B-label-swapped BAB judgments."
    )
    parser.add_argument("--original", required=True, help="Original interactive_results_full.json.")
    parser.add_argument("--swapped", required=True, help="Merged label-swapped result JSON.")
    parser.add_argument(
        "--output-prefix",
        default="bab_label_swap_comparison",
        help="Prefix for the new .json and .csv reports.",
    )
    parser.add_argument(
        "--original-judge-field",
        default="judge_BAB",
        help="Dot path of the original BAB judge object (default: judge_BAB).",
    )
    parser.add_argument(
        "--swapped-judge-field",
        help="Dot path of the swapped judge object. If omitted, it is detected.",
    )
    parser.add_argument(
        "--key-fields",
        nargs="+",
        default=["stage", "pmid"],
        help="Fields forming a unique record key (default: stage pmid).",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Create reports even if the original and swapped key sets differ.",
    )
    parser.add_argument("--force", action="store_true", help="Replace existing report files.")
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


def make_key(record: Dict[str, Any], fields: Sequence[str]) -> Tuple[str, ...]:
    values: List[str] = []
    for field in fields:
        if field not in record or record[field] is None:
            raise ValueError(f"record is missing key field {field!r}")
        values.append(str(record[field]))
    return tuple(values)


def index_unique(
    records: Iterable[Dict[str, Any]], fields: Sequence[str], source_name: str
) -> Dict[Tuple[str, ...], Dict[str, Any]]:
    result: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    for record in records:
        key = make_key(record, fields)
        if key in result:
            raise ValueError(f"{source_name}: duplicate key {dict(zip(fields, key))}")
        result[key] = record
    return result


def get_dot_path(record: Dict[str, Any], path: str) -> Any:
    current: Any = record
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return None
        current = current[component]
    return current


def normalize_yes_no(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip().lower()
    if text in {"yes", "true"}:
        return "Yes"
    if text in {"no", "false"}:
        return "No"
    return None


def prediction_from_judge(judge: Any) -> Optional[str]:
    if not isinstance(judge, dict):
        return None
    return normalize_yes_no(judge.get("prediction", judge.get("answer")))


def looks_like_judge(value: Any) -> bool:
    return prediction_from_judge(value) is not None


def infer_swapped_judge_field(record: Dict[str, Any]) -> Optional[str]:
    for field in AUTO_SWAPPED_JUDGE_FIELDS:
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
    return candidates[0] if len(candidates) == 1 else None


def parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def nested_number(judge: Any, path: str) -> Optional[float]:
    value = get_dot_path(judge, path) if isinstance(judge, dict) else None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def selected_original_a(prediction: str, a_is_pro: bool) -> bool:
    """Whether the verdict selected the argument content generated by original speaker A."""
    return (prediction == "Yes" and a_is_pro) or (prediction == "No" and not a_is_pro)


def percent(count: int, total: int) -> Optional[float]:
    return 100.0 * count / total if total else None


def mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def round_or_none(value: Optional[float], digits: int = 6) -> Optional[float]:
    return round(value, digits) if value is not None else None


def exact_two_sided_binomial_p(left: int, right: int) -> Optional[float]:
    """Two-sided exact p-value under p=0.5, appropriate for McNemar discordances."""
    n = left + right
    if n == 0:
        return None
    tail_end = min(left, right)
    numerator = sum(math.comb(n, k) for k in range(tail_end + 1))
    probability = Fraction(numerator, 1 << n)
    return min(1.0, 2.0 * float(probability))


def extract_bab_texts(record: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    containers = [
        record.get("debate_BAB"),
        record.get("source_debate_BAB"),
        record.get("reused_debate_BAB"),
    ]
    for debate in containers:
        if not isinstance(debate, dict):
            continue
        values = (
            debate.get("b_opening"),
            debate.get("a_rebuttal"),
            debate.get("b_closing"),
        )
        if all(isinstance(value, str) and value for value in values):
            return values
    return None


def calculate_statistics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    original_correct = sum(row["original_correct"] for row in rows)
    swapped_correct = sum(row["swapped_correct"] for row in rows)
    flips = sum(row["prediction_changed"] for row in rows)
    original_yes = sum(row["original_prediction"] == "Yes" for row in rows)
    swapped_yes = sum(row["swapped_prediction"] == "Yes" for row in rows)

    original_correct_swapped_wrong = sum(
        row["original_correct"] and not row["swapped_correct"] for row in rows
    )
    original_wrong_swapped_correct = sum(
        not row["original_correct"] and row["swapped_correct"] for row in rows
    )

    both_correct = sum(row["original_correct"] and row["swapped_correct"] for row in rows)
    both_wrong = sum(not row["original_correct"] and not row["swapped_correct"] for row in rows)

    original_selected_a = sum(row["original_selected_original_A"] for row in rows)
    swapped_selected_a = sum(row["swapped_selected_original_A"] for row in rows)
    original_selected_b = n - original_selected_a
    swapped_selected_b = n - swapped_selected_a

    # Original B is displayed as B in the old prompt and as A in the swapped prompt.
    # Therefore B gains are switches toward content after it receives the A label.
    original_b_gains_after_a_label = sum(
        row["original_selected_original_A"] and row["swapped_selected_original_B"]
        for row in rows
    )
    original_b_losses_after_a_label = sum(
        row["original_selected_original_B"] and row["swapped_selected_original_A"]
        for row in rows
    )

    original_probs = [
        row["original_debater_prob_displayed_A_right"]
        for row in rows
        if row["original_debater_prob_displayed_A_right"] is not None
    ]
    swapped_probs = [
        row["swapped_debater_prob_displayed_A_right"]
        for row in rows
        if row["swapped_debater_prob_displayed_A_right"] is not None
    ]

    return {
        "n": n,
        "accuracy": {
            "original_percent": round_or_none(percent(original_correct, n)),
            "swapped_percent": round_or_none(percent(swapped_correct, n)),
            "swapped_minus_original_percentage_points": round_or_none(
                percent(swapped_correct - original_correct, n)
            ),
            "both_correct": both_correct,
            "both_wrong": both_wrong,
            "original_correct_swapped_wrong": original_correct_swapped_wrong,
            "original_wrong_swapped_correct": original_wrong_swapped_correct,
            "mcnemar_exact_two_sided_p": round_or_none(
                exact_two_sided_binomial_p(
                    original_correct_swapped_wrong, original_wrong_swapped_correct
                ),
                12,
            ),
        },
        "predictions": {
            "original_yes_percent": round_or_none(percent(original_yes, n)),
            "swapped_yes_percent": round_or_none(percent(swapped_yes, n)),
            "changed_count": flips,
            "changed_percent": round_or_none(percent(flips, n)),
            "agreement_percent": round_or_none(percent(n - flips, n)),
            "yes_to_no": sum(
                row["original_prediction"] == "Yes" and row["swapped_prediction"] == "No"
                for row in rows
            ),
            "no_to_yes": sum(
                row["original_prediction"] == "No" and row["swapped_prediction"] == "Yes"
                for row in rows
            ),
        },
        "speaker_label_analysis": {
            "interpretation": (
                "Original content B was displayed as B originally and as A after swapping. "
                "A positive B-content change means that this same content was selected more "
                "often after receiving the A label."
            ),
            "original_content_B_selected_before_percent": round_or_none(
                percent(original_selected_b, n)
            ),
            "original_content_B_selected_after_receiving_A_label_percent": round_or_none(
                percent(swapped_selected_b, n)
            ),
            "B_content_change_percentage_points": round_or_none(
                percent(swapped_selected_b - original_selected_b, n)
            ),
            "B_content_gains_after_receiving_A_label": original_b_gains_after_a_label,
            "B_content_losses_after_receiving_A_label": original_b_losses_after_a_label,
            "label_effect_exact_two_sided_p": round_or_none(
                exact_two_sided_binomial_p(
                    original_b_gains_after_a_label, original_b_losses_after_a_label
                ),
                12,
            ),
            "displayed_A_selected_original_percent": round_or_none(
                percent(original_selected_a, n)
            ),
            "displayed_A_selected_swapped_percent": round_or_none(
                percent(swapped_selected_b, n)
            ),
            "mean_model_P_displayed_A_right_original": round_or_none(mean(original_probs)),
            "mean_model_P_displayed_A_right_swapped": round_or_none(mean(swapped_probs)),
            "probability_n_original": len(original_probs),
            "probability_n_swapped": len(swapped_probs),
        },
    }


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


def write_csv(path: str, rows: Sequence[Dict[str, Any]], key_fields: Sequence[str]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(key_fields) + [
        "candidate_tag",
        "ground_truth",
        "a_is_pro",
        "original_prediction",
        "swapped_prediction",
        "prediction_changed",
        "original_correct",
        "swapped_correct",
        "accuracy_change",
        "original_selected_original_A",
        "original_selected_original_B",
        "swapped_selected_original_A",
        "swapped_selected_original_B",
        "original_displayed_A_selected",
        "swapped_displayed_A_selected",
        "original_debater_prob_displayed_A_right",
        "swapped_debater_prob_displayed_A_right",
        "transcript_content_verified_identical",
        "swapped_judge_field",
    ]
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    args = parse_args()
    json_output = args.output_prefix + ".json"
    csv_output = args.output_prefix + ".csv"
    existing = [path for path in (json_output, csv_output) if os.path.exists(path)]
    if existing and not args.force:
        print(
            "ERROR: report output already exists: " + ", ".join(existing) +
            "\nChoose another --output-prefix or pass --force.",
            file=sys.stderr,
        )
        return 1

    original_records = records_from_document(load_json(args.original), args.original)
    swapped_document = load_json(args.swapped)
    swapped_records = records_from_document(swapped_document, args.swapped)

    original = index_unique(original_records, args.key_fields, args.original)
    swapped = index_unique(swapped_records, args.key_fields, args.swapped)

    original_keys = set(original)
    swapped_keys = set(swapped)
    missing_swapped = sorted(original_keys - swapped_keys)
    unexpected_swapped = sorted(swapped_keys - original_keys)

    if (missing_swapped or unexpected_swapped) and not args.allow_incomplete:
        print(
            "ERROR: original and swapped key sets differ.\n"
            f"  Missing from swapped: {len(missing_swapped)}\n"
            f"  Unexpected in swapped: {len(unexpected_swapped)}\n"
            "Run the merge/completeness script first, or pass --allow-incomplete.",
            file=sys.stderr,
        )
        return 2

    rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    field_counts: Counter[str] = Counter()
    transcript_checks = Counter()

    for key in sorted(original_keys & swapped_keys):
        old_record = original[key]
        new_record = swapped[key]
        old_judge = get_dot_path(old_record, args.original_judge_field)
        swapped_field = args.swapped_judge_field or infer_swapped_judge_field(new_record)
        new_judge = get_dot_path(new_record, swapped_field) if swapped_field else None

        old_prediction = prediction_from_judge(old_judge)
        new_prediction = prediction_from_judge(new_judge)
        ground_truth = normalize_yes_no(
            old_record.get("ground_truth", new_record.get("ground_truth"))
        )
        a_is_pro = parse_bool(old_record.get("a_is_pro", old_record.get("pro_first")))

        if not swapped_field or old_prediction is None or new_prediction is None or ground_truth is None:
            skipped.append(
                {
                    **dict(zip(args.key_fields, key)),
                    "reason": "missing valid judge prediction, ground truth, or swapped judge field",
                    "swapped_judge_field": swapped_field,
                }
            )
            continue
        if a_is_pro is None:
            skipped.append(
                {
                    **dict(zip(args.key_fields, key)),
                    "reason": "missing/invalid a_is_pro (or pro_first)",
                    "swapped_judge_field": swapped_field,
                }
            )
            continue

        field_counts[swapped_field] += 1
        old_correct = old_prediction == ground_truth
        new_correct = new_prediction == ground_truth
        old_selected_a = selected_original_a(old_prediction, a_is_pro)
        new_selected_a = selected_original_a(new_prediction, a_is_pro)

        old_texts = extract_bab_texts(old_record)
        new_texts = extract_bab_texts(new_record)
        if old_texts is not None and new_texts is not None:
            transcript_equal: Optional[bool] = old_texts == new_texts
            transcript_checks["identical" if transcript_equal else "different"] += 1
        else:
            transcript_equal = None
            transcript_checks["not_verifiable_from_saved_fields"] += 1

        old_probability = nested_number(old_judge, "confidence.debater_prob_A_right")
        new_probability = nested_number(new_judge, "confidence.debater_prob_A_right")

        row: Dict[str, Any] = {
            **dict(zip(args.key_fields, key)),
            "candidate_tag": old_record.get("candidate_tag", new_record.get("candidate_tag")),
            "ground_truth": ground_truth,
            "a_is_pro": a_is_pro,
            "original_prediction": old_prediction,
            "swapped_prediction": new_prediction,
            "prediction_changed": old_prediction != new_prediction,
            "original_correct": old_correct,
            "swapped_correct": new_correct,
            "accuracy_change": int(new_correct) - int(old_correct),
            "original_selected_original_A": old_selected_a,
            "original_selected_original_B": not old_selected_a,
            "swapped_selected_original_A": new_selected_a,
            "swapped_selected_original_B": not new_selected_a,
            "original_displayed_A_selected": old_selected_a,
            # In the swapped presentation, displayed A contains original B's text.
            "swapped_displayed_A_selected": not new_selected_a,
            "original_debater_prob_displayed_A_right": old_probability,
            "swapped_debater_prob_displayed_A_right": new_probability,
            "transcript_content_verified_identical": transcript_equal,
            "swapped_judge_field": swapped_field,
        }
        rows.append(row)

    if skipped and not args.allow_incomplete:
        print(
            f"ERROR: {len(skipped)} matched record(s) could not be compared. "
            "Pass --allow-incomplete to report the valid subset.",
            file=sys.stderr,
        )
        return 2

    if transcript_checks["different"]:
        print(
            "ERROR: saved BAB text differs for one or more paired records. This is not a pure "
            "speaker-label comparison, so no report was written.",
            file=sys.stderr,
        )
        return 2

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("stage", "Unknown"))].append(row)

    report = {
        "metadata": {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "original_file": args.original,
            "swapped_file": args.swapped,
            "original_judge_field": args.original_judge_field,
            "swapped_judge_fields_detected": dict(field_counts),
            "key_fields": args.key_fields,
            "original_records": len(original),
            "swapped_records": len(swapped),
            "matched_records": len(original_keys & swapped_keys),
            "compared_records": len(rows),
            "skipped_matched_records": len(skipped),
            "missing_from_swapped": len(missing_swapped),
            "unexpected_in_swapped": len(unexpected_swapped),
            "transcript_checks": dict(transcript_checks),
            "pure_label_swap_verified_for_all_comparable_saved_transcripts": (
                transcript_checks["different"] == 0
            ),
        },
        "overall": calculate_statistics(rows),
        "by_stage": {stage: calculate_statistics(stage_rows) for stage, stage_rows in sorted(groups.items())},
        "missing_from_swapped_examples": [
            dict(zip(args.key_fields, key)) for key in missing_swapped[:100]
        ],
        "unexpected_in_swapped_examples": [
            dict(zip(args.key_fields, key)) for key in unexpected_swapped[:100]
        ],
        "skipped_examples": skipped[:100],
        "interpretation_notes": [
            "Prediction changed percent is the direct paired measure of sensitivity to speaker names.",
            "Accuracy change shows whether the relabeling helped or harmed correctness.",
            "McNemar's exact test evaluates whether correct-to-wrong and wrong-to-correct changes are asymmetric.",
            "For the label-effect test, original content B is tracked before and after it receives the displayed A label. A positive change favors an A-label preference.",
            "A small p-value indicates evidence of an asymmetric paired change; it does not by itself measure effect size or prove a causal mechanism beyond this controlled prompt change.",
        ],
    }

    atomic_write_json(json_output, report)
    write_csv(csv_output, rows, args.key_fields)

    overall = report["overall"]
    accuracy = overall["accuracy"]
    predictions = overall["predictions"]
    labels = overall["speaker_label_analysis"]

    print("\n==== BAB SPEAKER-LABEL COMPARISON ====")
    print(f"Compared records:                    {overall['n']}")
    print(f"Original BAB accuracy:               {accuracy['original_percent']:.3f}%")
    print(f"Swapped-label accuracy:              {accuracy['swapped_percent']:.3f}%")
    print(
        "Accuracy change (swapped-original): "
        f"{accuracy['swapped_minus_original_percentage_points']:+.3f} percentage points"
    )
    print(f"Prediction changed:                  {predictions['changed_count']} ({predictions['changed_percent']:.3f}%)")
    print(f"Accuracy McNemar exact p:            {accuracy['mcnemar_exact_two_sided_p']}")
    print(
        "Original-B content selected before: "
        f"{labels['original_content_B_selected_before_percent']:.3f}%"
    )
    print(
        "Original-B selected after A label:   "
        f"{labels['original_content_B_selected_after_receiving_A_label_percent']:.3f}%"
    )
    print(
        "B-content change after A label:      "
        f"{labels['B_content_change_percentage_points']:+.3f} percentage points"
    )
    print(f"Label-effect exact p:                {labels['label_effect_exact_two_sided_p']}")
    print(f"JSON report:                         {json_output}")
    print(f"Per-record CSV:                      {csv_output}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
