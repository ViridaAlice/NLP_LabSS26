#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compare three judge conditions:

1. ABA: original ABA debate and original A/B names
2. BAB: original BAB debate and original A/B names
3. BAB relabelled: the same BAB text, but original B is shown as A and
   original A is shown as B

The script is compatible with Python 3.6 and uses only the standard library.
It creates:
  - comparison_report.md
  - comparison_summary.json
  - record_level_comparison.csv

Important interpretation:
The original-BAB versus relabelled-BAB comparison is the cleanest comparison,
because debate text and physical turn order are held constant. ABA versus BAB
also changes generated arguments, so it is not a pure position-only test.
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict


CONDITION_ABA = "ABA_original"
CONDITION_BAB = "BAB_original"
CONDITION_SWAP = "BAB_relabelled"

PREFERRED_SWAPPED_KEYS = [
    "judge_BAB_swapped_labels",
    "judge_BAB_swapped",
    "judge_BAB_names_swapped",
    "judge_BAB_relabelled",
    "judge_BAB_relabeled",
    "judge_swapped_labels",
    "judge_swapped",
    "swapped_judge",
    "new_judge",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare ABA, original BAB, and relabelled BAB judge results."
    )
    parser.add_argument(
        "--original",
        required=True,
        help="Original full JSON containing judge_ABA and judge_BAB.",
    )
    parser.add_argument(
        "--swapped",
        required=True,
        help="Merged JSON containing the new relabelled-BAB judgments.",
    )
    parser.add_argument(
        "--output-dir",
        default="comparison_three_conditions",
        help="New/existing directory for reports (default: comparison_three_conditions).",
    )
    parser.add_argument(
        "--swapped-judge-key",
        default=None,
        help=(
            "Optional explicit path to the new judge object, for example "
            "judge_BAB_swapped_labels. Normally it is detected automatically."
        ),
    )
    return parser.parse_args()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_results(data, path):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    raise ValueError("%s must be a JSON list or an object with a 'results' list." % path)


def atomic_write_text(path, text):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path, value):
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    atomic_write_text(path, text + "\n")


def normalize_prediction(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("yes", "true", "pro", "belongs", "1"):
        return "PRO"
    if text in ("no", "false", "con", "does not belong", "0"):
        return "CON"
    return None


def normalize_side(value):
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in ("PRO", "YES", "TRUE", "BELONGS"):
        return "PRO"
    if text in ("CON", "NO", "FALSE", "DOES NOT BELONG"):
        return "CON"
    return None


def record_key(record):
    return (
        str(record.get("stage", "")),
        str(record.get("pmid", "")),
        str(record.get("candidate_tag", "")),
    )


def short_key(record):
    return (str(record.get("stage", "")), str(record.get("pmid", "")))


def display_key(key):
    return "stage=%r, pmid=%r, candidate=%r" % key


def get_path(obj, path):
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_judge_object(value):
    return isinstance(value, dict) and normalize_prediction(value.get("prediction")) is not None


def recursively_find_judges(obj, prefix="", depth=0):
    found = []
    if depth > 4 or not isinstance(obj, dict):
        return found
    for key, value in obj.items():
        path = key if not prefix else prefix + "." + key
        if is_judge_object(value):
            found.append((path, value))
        elif isinstance(value, dict):
            found.extend(recursively_find_judges(value, path, depth + 1))
    return found


def extract_swapped_judge(record, explicit_path=None):
    if explicit_path:
        value = get_path(record, explicit_path)
        if is_judge_object(value):
            return value, explicit_path
        return None, explicit_path

    for key in PREFERRED_SWAPPED_KEYS:
        value = get_path(record, key)
        if is_judge_object(value):
            return value, key

    candidates = recursively_find_judges(record)
    marked = []
    for path, value in candidates:
        lower = path.lower()
        if any(token in lower for token in ("swap", "relabel", "rename", "new")):
            marked.append((path, value))
    if len(marked) == 1:
        return marked[0][1], marked[0][0]
    if len(marked) > 1:
        # Prefer the shortest path; this usually selects the top-level result.
        marked.sort(key=lambda item: (item[0].count("."), len(item[0])))
        return marked[0][1], marked[0][0]

    # Some generators save only the new judgment under judge_BAB in the new file.
    value = record.get("judge_BAB")
    if is_judge_object(value):
        return value, "judge_BAB (fallback in swapped file)"

    # Last fallback: a record may itself be the judgment.
    if is_judge_object(record):
        return record, "<record itself>"
    return None, None


def infer_sides(record):
    a_side = normalize_side(record.get("a_side"))
    b_side = normalize_side(record.get("b_side"))
    if a_side is None and "a_is_pro" in record:
        a_side = "PRO" if bool(record.get("a_is_pro")) else "CON"
    if a_side is None and "pro_first" in record:
        a_side = "PRO" if bool(record.get("pro_first")) else "CON"
    if a_side is not None and b_side is None:
        b_side = "CON" if a_side == "PRO" else "PRO"
    if b_side is not None and a_side is None:
        a_side = "CON" if b_side == "PRO" else "PRO"
    return a_side, b_side


def safe_float(value):
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError):
        pass
    return None


def confidence_value(judge, name):
    confidence = judge.get("confidence", {}) if isinstance(judge, dict) else {}
    if not isinstance(confidence, dict):
        return None
    return safe_float(confidence.get(name))


def condition_row(condition, judge, truth_side, a_side, b_side,
                  presented_a_side, first_side):
    prediction = normalize_prediction(judge.get("prediction"))
    if prediction is None:
        return None
    correct = prediction == truth_side
    presented_a_correct = presented_a_side == truth_side
    first_correct = first_side == truth_side
    return {
        "condition": condition,
        "prediction": prediction,
        "correct": correct,
        "chose_pro": prediction == "PRO",
        "chose_con": prediction == "CON",
        "chose_presented_a": prediction == presented_a_side,
        "chose_first": prediction == first_side,
        "chose_original_a": prediction == a_side,
        "truth_side": truth_side,
        "a_side": a_side,
        "b_side": b_side,
        "presented_a_side": presented_a_side,
        "first_side": first_side,
        "presented_a_correct": presented_a_correct,
        "first_correct": first_correct,
        "error_toward_a": (not presented_a_correct) and prediction == presented_a_side,
        "error_away_from_a": presented_a_correct and prediction != presented_a_side,
        "error_toward_first": (not first_correct) and prediction == first_side,
        "error_away_from_first": first_correct and prediction != first_side,
        "needed_fallback": bool(judge.get("needed_fallback", False)),
        "prob_belongs": confidence_value(judge, "verdict_prob_belongs"),
        "prob_a_right": confidence_value(judge, "debater_prob_A_right"),
    }


def rate(numerator, denominator):
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def mean(values):
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / float(len(cleaned))


def wilson_interval(successes, n, z=1.959963984540054):
    if n <= 0:
        return [None, None]
    p = float(successes) / float(n)
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    half = z * math.sqrt((p * (1.0 - p) / n) + z2 / (4.0 * n * n)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def logsumexp(log_values):
    if not log_values:
        return float("-inf")
    maximum = max(log_values)
    return maximum + math.log(sum(math.exp(value - maximum) for value in log_values))


def exact_binomial_two_sided(successes, n):
    """Exact two-sided binomial p-value for null probability 0.5."""
    if n <= 0:
        return None
    tail = min(successes, n - successes)
    logs = []
    log_two = math.log(2.0)
    for k in range(tail + 1):
        log_probability = (
            math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            - n * log_two
        )
        logs.append(log_probability)
    p_value = 2.0 * math.exp(logsumexp(logs))
    return min(1.0, p_value)


def two_proportion_p(success_1, n_1, success_2, n_2):
    """Two-sided pooled two-proportion z-test; returns None for empty groups."""
    if n_1 <= 0 or n_2 <= 0:
        return None
    pooled = float(success_1 + success_2) / float(n_1 + n_2)
    variance = pooled * (1.0 - pooled) * (1.0 / n_1 + 1.0 / n_2)
    if variance <= 0.0:
        return 1.0 if rate(success_1, n_1) == rate(success_2, n_2) else 0.0
    z_value = (rate(success_1, n_1) - rate(success_2, n_2)) / math.sqrt(variance)
    return math.erfc(abs(z_value) / math.sqrt(2.0))


def summarize_condition(rows):
    n = len(rows)
    correct = sum(1 for row in rows if row["correct"])
    pro = sum(1 for row in rows if row["chose_pro"])
    chose_a = sum(1 for row in rows if row["chose_presented_a"])
    chose_first = sum(1 for row in rows if row["chose_first"])
    fallback = sum(1 for row in rows if row["needed_fallback"])

    truth_pro = [row for row in rows if row["truth_side"] == "PRO"]
    truth_con = [row for row in rows if row["truth_side"] == "CON"]
    false_negatives = sum(1 for row in truth_pro if row["prediction"] == "CON")
    false_positives = sum(1 for row in truth_con if row["prediction"] == "PRO")

    first_pro = [row for row in rows if row["first_side"] == "PRO"]
    first_con = [row for row in rows if row["first_side"] == "CON"]
    a_pro = [row for row in rows if row["presented_a_side"] == "PRO"]
    a_con = [row for row in rows if row["presented_a_side"] == "CON"]

    a_false = [row for row in rows if not row["presented_a_correct"]]
    a_true = [row for row in rows if row["presented_a_correct"]]
    first_false = [row for row in rows if not row["first_correct"]]
    first_true = [row for row in rows if row["first_correct"]]
    toward_a = sum(1 for row in a_false if row["error_toward_a"])
    away_a = sum(1 for row in a_true if row["error_away_from_a"])
    toward_first = sum(1 for row in first_false if row["error_toward_first"])
    away_first = sum(1 for row in first_true if row["error_away_from_first"])

    return {
        "n": n,
        "accuracy": rate(correct, n),
        "accuracy_ci95": wilson_interval(correct, n),
        "pro_choice_rate": rate(pro, n),
        "con_choice_rate": rate(n - pro, n),
        "presented_a_choice_rate": rate(chose_a, n),
        "presented_a_vs_50_p": exact_binomial_two_sided(chose_a, n),
        "first_speaker_choice_rate": rate(chose_first, n),
        "first_speaker_vs_50_p": exact_binomial_two_sided(chose_first, n),
        "ground_truth_pro_rate": rate(len(truth_pro), n),
        "false_positive_rate_pro_on_true_con": rate(false_positives, len(truth_con)),
        "false_negative_rate_con_on_true_pro": rate(false_negatives, len(truth_pro)),
        "fpr_vs_fnr_p": two_proportion_p(
            false_positives, len(truth_con), false_negatives, len(truth_pro)
        ),
        "pro_choice_if_first_is_pro": rate(
            sum(1 for row in first_pro if row["chose_pro"]), len(first_pro)
        ),
        "pro_choice_if_first_is_con": rate(
            sum(1 for row in first_con if row["chose_pro"]), len(first_con)
        ),
        "first_choice_if_first_is_pro": rate(
            sum(1 for row in first_pro if row["chose_first"]), len(first_pro)
        ),
        "first_choice_if_first_is_con": rate(
            sum(1 for row in first_con if row["chose_first"]), len(first_con)
        ),
        "presented_a_choice_if_a_is_pro": rate(
            sum(1 for row in a_pro if row["chose_presented_a"]), len(a_pro)
        ),
        "presented_a_choice_if_a_is_con": rate(
            sum(1 for row in a_con if row["chose_presented_a"]), len(a_con)
        ),
        "error_toward_presented_a_rate": rate(toward_a, len(a_false)),
        "error_away_from_presented_a_rate": rate(away_a, len(a_true)),
        "a_error_direction_p": two_proportion_p(toward_a, len(a_false), away_a, len(a_true)),
        "error_toward_first_rate": rate(toward_first, len(first_false)),
        "error_away_from_first_rate": rate(away_first, len(first_true)),
        "first_error_direction_p": two_proportion_p(
            toward_first, len(first_false), away_first, len(first_true)
        ),
        "mean_prob_belongs": mean([row["prob_belongs"] for row in rows]),
        "mean_prob_presented_a_right": mean([row["prob_a_right"] for row in rows]),
        "fallback_rate": rate(fallback, n),
    }


def paired_boolean(rows, field, left_condition, right_condition):
    left_only = 0
    right_only = 0
    both = 0
    neither = 0
    for item in rows:
        left = bool(item[left_condition][field])
        right = bool(item[right_condition][field])
        if left and right:
            both += 1
        elif left:
            left_only += 1
        elif right:
            right_only += 1
        else:
            neither += 1
    discordant = left_only + right_only
    return {
        "field": field,
        "left_condition": left_condition,
        "right_condition": right_condition,
        "left_rate": rate(left_only + both, len(rows)),
        "right_rate": rate(right_only + both, len(rows)),
        "right_minus_left": (
            rate(right_only + both, len(rows)) - rate(left_only + both, len(rows))
            if rows else None
        ),
        "left_only": left_only,
        "right_only": right_only,
        "both": both,
        "neither": neither,
        "discordant": discordant,
        "exact_p": exact_binomial_two_sided(left_only, discordant),
    }


def paired_comparison(rows, left, right):
    prediction_flips = sum(
        1 for item in rows
        if item[left]["prediction"] != item[right]["prediction"]
    )
    return {
        "left": left,
        "right": right,
        "n": len(rows),
        "prediction_agreement_rate": rate(len(rows) - prediction_flips, len(rows)),
        "prediction_flip_rate": rate(prediction_flips, len(rows)),
        "accuracy": paired_boolean(rows, "correct", left, right),
        "pro_choice": paired_boolean(rows, "chose_pro", left, right),
        "presented_a_choice": paired_boolean(rows, "chose_presented_a", left, right),
        "first_speaker_choice": paired_boolean(rows, "chose_first", left, right),
    }


def relabelling_analysis(rows):
    follows_a_label = 0
    follows_b_label = 0
    stable_original_a_content = 0
    stable_original_b_content = 0
    unexpected = 0

    for item in rows:
        original = item[CONDITION_BAB]
        swapped = item[CONDITION_SWAP]
        if original["prediction"] != swapped["prediction"]:
            if original["chose_presented_a"] and swapped["chose_presented_a"]:
                follows_a_label += 1
            elif (not original["chose_presented_a"] and
                  not swapped["chose_presented_a"]):
                follows_b_label += 1
            else:
                unexpected += 1
        else:
            if original["chose_original_a"]:
                stable_original_a_content += 1
            else:
                stable_original_b_content += 1

    flips = follows_a_label + follows_b_label + unexpected
    stable = stable_original_a_content + stable_original_b_content
    directional_n = follows_a_label + follows_b_label
    return {
        "n": len(rows),
        "same_side_or_prediction_count": stable,
        "same_side_or_prediction_rate": rate(stable, len(rows)),
        "changed_side_or_prediction_count": flips,
        "changed_side_or_prediction_rate": rate(flips, len(rows)),
        "on_flip_followed_presented_a_label": follows_a_label,
        "on_flip_followed_presented_b_label": follows_b_label,
        "on_flip_unexpected": unexpected,
        "a_label_share_among_directional_flips": rate(follows_a_label, directional_n),
        "a_vs_b_label_exact_p": exact_binomial_two_sided(follows_a_label, directional_n),
        "stable_original_a_content": stable_original_a_content,
        "stable_original_b_content": stable_original_b_content,
    }


def percent(value, digits=1):
    if value is None:
        return "n/a"
    return ("%%.%df%%%%" % digits) % (100.0 * value)


def p_text(value):
    if value is None:
        return "n/a"
    if value < 0.001:
        return "<0.001"
    return "%.3f" % value


def delta_pp(value):
    if value is None:
        return "n/a"
    return "%+.1f pp" % (100.0 * value)


def condition_name(name):
    names = {
        CONDITION_ABA: "ABA (original)",
        CONDITION_BAB: "BAB (original names)",
        CONDITION_SWAP: "BAB (A/B names swapped)",
    }
    return names.get(name, name)


def build_takeaways(overall, pair_bab_swap, relabel):
    lines = []
    swap_flip = relabel["changed_side_or_prediction_rate"]
    a_count = relabel["on_flip_followed_presented_a_label"]
    b_count = relabel["on_flip_followed_presented_b_label"]
    label_p = relabel["a_vs_b_label_exact_p"]

    if swap_flip is not None:
        lines.append(
            "Renaming A and B changed **%s** of judgments while preserving the BAB text "
            "and its physical order." % percent(swap_flip)
        )
    if (a_count + b_count) > 0:
        if label_p is not None and label_p < 0.05 and a_count > b_count:
            lines.append(
                "Among relabelling-induced flips, %d followed the displayed **A** label and "
                "%d followed **B** (exact p=%s). This is evidence compatible with an "
                "A-name preference." % (a_count, b_count, p_text(label_p))
            )
        elif label_p is not None and label_p < 0.05 and b_count > a_count:
            lines.append(
                "Among relabelling-induced flips, %d followed displayed A and %d followed "
                "**B** (exact p=%s). The directional evidence favors a B-name preference, "
                "not an A-name preference." % (a_count, b_count, p_text(label_p))
            )
        else:
            lines.append(
                "Among relabelling-induced flips, %d followed displayed A and %d followed "
                "displayed B (exact p=%s). There is no statistically clear directional "
                "A-versus-B preference in these flips." % (a_count, b_count, p_text(label_p))
            )

    first_pair = pair_bab_swap["first_speaker_choice"]
    first_delta = first_pair["right_minus_left"]
    if first_delta is not None:
        if first_pair["exact_p"] is not None and first_pair["exact_p"] < 0.05:
            direction = "increased" if first_delta > 0 else "decreased"
            lines.append(
                "When the same first speaker/content was renamed from B to A, selection of "
                "the first speaker %s by **%s** (paired exact p=%s). This cleanly shows "
                "that the displayed name interacts with apparent position." % (
                    direction, delta_pp(abs(first_delta)), p_text(first_pair["exact_p"])
                )
            )
        else:
            lines.append(
                "Selection of the physically first speaker changed by %s after that speaker "
                "was renamed B→A (paired exact p=%s); this is not a clear directional effect." % (
                    delta_pp(first_delta), p_text(first_pair["exact_p"])
                )
            )

    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        summary = overall[condition]
        fpr = summary["false_positive_rate_pro_on_true_con"]
        fnr = summary["false_negative_rate_con_on_true_pro"]
        p_value = summary["fpr_vs_fnr_p"]
        if fpr is not None and fnr is not None and p_value is not None and p_value < 0.05:
            if fpr > fnr:
                direction = "PRO/Yes"
            else:
                direction = "CON/No"
            lines.append(
                "%s has a significant error asymmetry toward **%s**: FPR=%s versus "
                "FNR=%s (two-proportion p=%s)." % (
                    condition_name(condition), direction, percent(fpr), percent(fnr),
                    p_text(p_value)
                )
            )

    best = max(overall.keys(), key=lambda key: overall[key]["accuracy"] or -1.0)
    worst = min(overall.keys(), key=lambda key: overall[key]["accuracy"] or 2.0)
    lines.append(
        "Highest observed accuracy is %s for **%s**; lowest is %s for **%s**." % (
            percent(overall[best]["accuracy"]), condition_name(best),
            percent(overall[worst]["accuracy"]), condition_name(worst)
        )
    )
    return lines


def markdown_report(integrity, overall, stages, pairwise, relabel, takeaways,
                    swapped_paths):
    lines = []
    lines.append("# Three-way judge-bias comparison")
    lines.append("")
    lines.append("## Data integrity")
    lines.append("")
    lines.append("| Check | Value |")
    lines.append("|---|---:|")
    lines.append("| Original records | %d |" % integrity["original_records"])
    lines.append("| Swapped/relabelled records | %d |" % integrity["swapped_records"])
    lines.append("| Complete matched triples analyzed | %d |" % integrity["complete_triples"])
    lines.append("| Missing swapped records | %d |" % integrity["missing_swapped_records"])
    lines.append("| Invalid/missing original judgments | %d |" % integrity["invalid_original_judgments"])
    lines.append("| Invalid/missing swapped judgments | %d |" % integrity["invalid_swapped_judgments"])
    lines.append("| Duplicate exact keys in swapped file | %d |" % integrity["duplicate_swapped_keys"])
    lines.append("")
    lines.append("Detected swapped judge path(s): `%s`." % ", ".join(swapped_paths))
    lines.append("")

    lines.append("## Main takeaway")
    lines.append("")
    for item in takeaways:
        lines.append("- " + item)
    lines.append("")

    lines.append("## Overall results")
    lines.append("")
    lines.append("| Condition | N | Accuracy | Pro/Yes chosen | Displayed A chosen | First speaker chosen | FPR | FNR | Mean P(A right) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        item = overall[condition]
        lines.append(
            "| %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
                condition_name(condition), item["n"], percent(item["accuracy"]),
                percent(item["pro_choice_rate"]),
                percent(item["presented_a_choice_rate"]),
                percent(item["first_speaker_choice_rate"]),
                percent(item["false_positive_rate_pro_on_true_con"]),
                percent(item["false_negative_rate_con_on_true_pro"]),
                percent(item["mean_prob_presented_a_right"]),
            )
        )
    lines.append("")
    lines.append("FPR = choosing Pro/Yes when Con/No is true. FNR = choosing Con/No when Pro/Yes is true.")
    lines.append("")

    lines.append("## Role and order interactions")
    lines.append("")
    lines.append("| Condition | P(Pro | first=Pro) | P(Pro | first=Con) | First wins when Pro | First wins when Con | P(A wins | A=Pro) | P(A wins | A=Con) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        item = overall[condition]
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |" % (
                condition_name(condition),
                percent(item["pro_choice_if_first_is_pro"]),
                percent(item["pro_choice_if_first_is_con"]),
                percent(item["first_choice_if_first_is_pro"]),
                percent(item["first_choice_if_first_is_con"]),
                percent(item["presented_a_choice_if_a_is_pro"]),
                percent(item["presented_a_choice_if_a_is_con"]),
            )
        )
    lines.append("")

    lines.append("## Error-direction diagnostics")
    lines.append("")
    lines.append("| Condition | Error toward displayed A | Error away from displayed A | p | Error toward first | Error away from first | p |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        item = overall[condition]
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |" % (
                condition_name(condition),
                percent(item["error_toward_presented_a_rate"]),
                percent(item["error_away_from_presented_a_rate"]),
                p_text(item["a_error_direction_p"]),
                percent(item["error_toward_first_rate"]),
                percent(item["error_away_from_first_rate"]),
                p_text(item["first_error_direction_p"]),
            )
        )
    lines.append("")
    lines.append("These compare error rates conditional on whether displayed A/first speaker is actually on the incorrect or correct side.")
    lines.append("")

    lines.append("## Clean BAB relabelling test")
    lines.append("")
    lines.append("The BAB text and physical sequence are identical; only displayed A/B names change.")
    lines.append("")
    lines.append("| Outcome | Count | Rate/share |")
    lines.append("|---|---:|---:|")
    lines.append("| Prediction/side unchanged | %d | %s |" % (
        relabel["same_side_or_prediction_count"],
        percent(relabel["same_side_or_prediction_rate"])))
    lines.append("| Prediction/side changed | %d | %s |" % (
        relabel["changed_side_or_prediction_count"],
        percent(relabel["changed_side_or_prediction_rate"])))
    lines.append("| Flip followed displayed A label | %d | %s of directional flips |" % (
        relabel["on_flip_followed_presented_a_label"],
        percent(relabel["a_label_share_among_directional_flips"])))
    lines.append("| Flip followed displayed B label | %d | %s of directional flips |" % (
        relabel["on_flip_followed_presented_b_label"],
        percent(1.0 - relabel["a_label_share_among_directional_flips"]
                if relabel["a_label_share_among_directional_flips"] is not None else None)))
    lines.append("| Stable choice of original A content/side | %d | — |" % relabel["stable_original_a_content"])
    lines.append("| Stable choice of original B content/side | %d | — |" % relabel["stable_original_b_content"])
    lines.append("")
    lines.append("Exact A-label versus B-label test among directional flips: p=%s." % p_text(relabel["a_vs_b_label_exact_p"]))
    lines.append("")

    lines.append("## Paired comparisons")
    lines.append("")
    lines.append("| Comparison | Prediction flip | Accuracy left | Accuracy right | Accuracy Δ | p | First-choice left | First-choice right | First-choice Δ | p |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in pairwise:
        accuracy = item["accuracy"]
        first = item["first_speaker_choice"]
        lines.append(
            "| %s → %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                condition_name(item["left"]), condition_name(item["right"]),
                percent(item["prediction_flip_rate"]),
                percent(accuracy["left_rate"]), percent(accuracy["right_rate"]),
                delta_pp(accuracy["right_minus_left"]), p_text(accuracy["exact_p"]),
                percent(first["left_rate"]), percent(first["right_rate"]),
                delta_pp(first["right_minus_left"]), p_text(first["exact_p"]),
            )
        )
    lines.append("")

    lines.append("## Results by stage")
    lines.append("")
    lines.append("| Stage | Condition | N | Accuracy | Pro/Yes | Displayed A | First speaker |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for stage in sorted(stages.keys()):
        for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
            item = stages[stage][condition]
            lines.append(
                "| %s | %s | %d | %s | %s | %s | %s |" % (
                    stage, condition_name(condition), item["n"],
                    percent(item["accuracy"]), percent(item["pro_choice_rate"]),
                    percent(item["presented_a_choice_rate"]),
                    percent(item["first_speaker_choice_rate"]),
                )
            )
    lines.append("")

    lines.append("## Interpretation cautions")
    lines.append("")
    lines.append("- **Original BAB vs relabelled BAB is the strongest causal comparison**: content and physical order are held fixed.")
    lines.append("- ABA vs BAB is descriptive, not a pure position experiment, because the two orders contain separately generated arguments.")
    lines.append("- If judge generation uses sampling rather than deterministic decoding, some relabelling differences may be ordinary run-to-run randomness. Repeated seeds/runs are needed to separate that variance from naming effects.")
    lines.append("- A high raw Pro/Yes rate is not by itself proof of Pro bias when the ground-truth class balance is unequal. FPR versus FNR is the more useful error-asymmetry diagnostic.")
    lines.append("- The first speaker also gets the closing turn in ABA/BAB. Therefore, 'first-speaker bias' here is technically an opener/closer or two-turn-role advantage, not a pure primacy effect.")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_csv(path, triples):
    fields = [
        "stage", "pmid", "candidate_tag", "ground_truth", "a_side", "b_side",
        "swapped_judge_path",
    ]
    condition_fields = [
        "prediction", "correct", "chose_pro", "chose_presented_a", "chose_first",
        "chose_original_a", "presented_a_side", "first_side", "needed_fallback",
        "prob_belongs", "prob_a_right",
    ]
    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        fields.extend([condition + "__" + field for field in condition_fields])
    fields.extend([
        "bab_vs_relabel_prediction_flip",
        "aba_vs_bab_prediction_flip",
        "relabel_flip_direction",
    ])

    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in triples:
            output = {
                "stage": item["stage"],
                "pmid": item["pmid"],
                "candidate_tag": item["candidate_tag"],
                "ground_truth": item["ground_truth"],
                "a_side": item["a_side"],
                "b_side": item["b_side"],
                "swapped_judge_path": item["swapped_judge_path"],
            }
            for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
                for field in condition_fields:
                    output[condition + "__" + field] = item[condition].get(field)
            original = item[CONDITION_BAB]
            swapped = item[CONDITION_SWAP]
            output["bab_vs_relabel_prediction_flip"] = (
                original["prediction"] != swapped["prediction"]
            )
            output["aba_vs_bab_prediction_flip"] = (
                item[CONDITION_ABA]["prediction"] != original["prediction"]
            )
            if original["prediction"] == swapped["prediction"]:
                output["relabel_flip_direction"] = "stable_original_side"
            elif original["chose_presented_a"] and swapped["chose_presented_a"]:
                output["relabel_flip_direction"] = "followed_displayed_A"
            elif (not original["chose_presented_a"] and
                  not swapped["chose_presented_a"]):
                output["relabel_flip_direction"] = "followed_displayed_B"
            else:
                output["relabel_flip_direction"] = "unexpected"
            writer.writerow(output)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main():
    args = parse_args()
    original_data = load_json(args.original)
    swapped_data = load_json(args.swapped)
    original_records = get_results(original_data, args.original)
    swapped_records = get_results(swapped_data, args.swapped)

    swapped_exact = defaultdict(list)
    swapped_short = defaultdict(list)
    for record in swapped_records:
        swapped_exact[record_key(record)].append(record)
        swapped_short[short_key(record)].append(record)

    duplicate_swapped = sum(1 for values in swapped_exact.values() if len(values) > 1)
    missing_swapped = 0
    invalid_original = 0
    invalid_swapped = 0
    triples = []
    issue_examples = []
    swapped_paths = Counter()

    for original in original_records:
        exact = swapped_exact.get(record_key(original), [])
        if len(exact) == 1:
            swapped = exact[0]
        else:
            short = swapped_short.get(short_key(original), [])
            swapped = short[0] if len(short) == 1 else None

        if swapped is None:
            missing_swapped += 1
            if len(issue_examples) < 10:
                issue_examples.append("Missing swapped match: " + display_key(record_key(original)))
            continue

        judge_aba = original.get("judge_ABA")
        judge_bab = original.get("judge_BAB")
        if not is_judge_object(judge_aba) or not is_judge_object(judge_bab):
            invalid_original += 1
            if len(issue_examples) < 10:
                issue_examples.append("Invalid original judges: " + display_key(record_key(original)))
            continue

        judge_swap, judge_path = extract_swapped_judge(swapped, args.swapped_judge_key)
        if not is_judge_object(judge_swap):
            invalid_swapped += 1
            if len(issue_examples) < 10:
                issue_examples.append("Invalid swapped judge: " + display_key(record_key(original)))
            continue
        swapped_paths[judge_path] += 1

        a_side, b_side = infer_sides(original)
        truth_side = normalize_prediction(original.get("ground_truth"))
        if a_side is None or b_side is None or truth_side is None:
            invalid_original += 1
            if len(issue_examples) < 10:
                issue_examples.append("Invalid side/truth metadata: " + display_key(record_key(original)))
            continue

        # ABA: original A opens and closes; displayed A has original A's side.
        aba = condition_row(
            CONDITION_ABA, judge_aba, truth_side, a_side, b_side,
            presented_a_side=a_side, first_side=a_side
        )
        # Original BAB: original B opens and closes; displayed A has original A's side.
        bab = condition_row(
            CONDITION_BAB, judge_bab, truth_side, a_side, b_side,
            presented_a_side=a_side, first_side=b_side
        )
        # Relabelled BAB: original B still physically opens/closes, but is displayed as A.
        relabelled = condition_row(
            CONDITION_SWAP, judge_swap, truth_side, a_side, b_side,
            presented_a_side=b_side, first_side=b_side
        )
        if aba is None or bab is None or relabelled is None:
            invalid_swapped += 1
            continue

        triples.append({
            "stage": str(original.get("stage", "")),
            "pmid": str(original.get("pmid", "")),
            "candidate_tag": str(original.get("candidate_tag", "")),
            "ground_truth": "Yes" if truth_side == "PRO" else "No",
            "a_side": a_side,
            "b_side": b_side,
            "swapped_judge_path": judge_path,
            CONDITION_ABA: aba,
            CONDITION_BAB: bab,
            CONDITION_SWAP: relabelled,
        })

    if not triples:
        print("ERROR: No complete matched triples could be analyzed.", file=sys.stderr)
        if issue_examples:
            print("Examples:", file=sys.stderr)
            for issue in issue_examples:
                print("  - " + issue, file=sys.stderr)
        return 2

    condition_rows = {}
    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        condition_rows[condition] = [item[condition] for item in triples]
    overall = {
        condition: summarize_condition(rows)
        for condition, rows in condition_rows.items()
    }

    grouped = defaultdict(list)
    for item in triples:
        grouped[item["stage"]].append(item)
    stages = {}
    for stage, items in grouped.items():
        stages[stage] = {}
        for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
            stages[stage][condition] = summarize_condition(
                [item[condition] for item in items]
            )

    pairwise = [
        paired_comparison(triples, CONDITION_ABA, CONDITION_BAB),
        paired_comparison(triples, CONDITION_BAB, CONDITION_SWAP),
        paired_comparison(triples, CONDITION_ABA, CONDITION_SWAP),
    ]
    pair_bab_swap = pairwise[1]
    relabel = relabelling_analysis(triples)
    integrity = {
        "original_records": len(original_records),
        "swapped_records": len(swapped_records),
        "complete_triples": len(triples),
        "missing_swapped_records": missing_swapped,
        "invalid_original_judgments": invalid_original,
        "invalid_swapped_judgments": invalid_swapped,
        "duplicate_swapped_keys": duplicate_swapped,
        "issue_examples": issue_examples,
    }
    takeaways = build_takeaways(overall, pair_bab_swap, relabel)

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    summary = {
        "inputs": {
            "original": os.path.abspath(args.original),
            "swapped": os.path.abspath(args.swapped),
        },
        "integrity": integrity,
        "detected_swapped_judge_paths": dict(swapped_paths),
        "overall": overall,
        "by_stage": stages,
        "paired_comparisons": pairwise,
        "clean_bab_relabelling_analysis": relabel,
        "automatic_takeaways": takeaways,
    }

    summary_path = os.path.join(output_dir, "comparison_summary.json")
    report_path = os.path.join(output_dir, "comparison_report.md")
    csv_path = os.path.join(output_dir, "record_level_comparison.csv")
    atomic_write_json(summary_path, summary)
    atomic_write_text(
        report_path,
        markdown_report(
            integrity, overall, stages, pairwise, relabel, takeaways,
            sorted(swapped_paths.keys())
        ),
    )
    write_csv(csv_path, triples)

    print("\n=== THREE-WAY COMPARISON COMPLETE ===")
    print("Complete matched triples: %d" % len(triples))
    print("Detected swapped judge path(s): %s" % ", ".join(sorted(swapped_paths.keys())))
    for condition in (CONDITION_ABA, CONDITION_BAB, CONDITION_SWAP):
        item = overall[condition]
        print(
            "%s: accuracy=%s | Pro=%s | displayed A=%s | first=%s" % (
                condition_name(condition), percent(item["accuracy"]),
                percent(item["pro_choice_rate"]),
                percent(item["presented_a_choice_rate"]),
                percent(item["first_speaker_choice_rate"]),
            )
        )
    print("BAB relabelling prediction flip rate: %s" % percent(
        relabel["changed_side_or_prediction_rate"]
    ))
    print("\nTakeaways:")
    for takeaway in takeaways:
        print("- " + takeaway.replace("**", ""))
    print("\nWrote:")
    print("  " + report_path)
    print("  " + summary_path)
    print("  " + csv_path)

    if missing_swapped or invalid_original or invalid_swapped or duplicate_swapped:
        print("\nWARNING: Integrity checks found incomplete/invalid/duplicate records.")
        print("Read the Data integrity section of %s." % report_path)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
