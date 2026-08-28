#!/usr/bin/env python3
"""Current-results extension for ``analyze_results.py``.

Place this file beside ``results/analyze_results.py``.  The main script already
contains the following hook and therefore needs no other edit::

    from analyze_results_latest_extension import install_latest_results_support
    install_latest_results_support(globals())

The extension is deliberately implemented as a small installation function so
that it can update the large analysis program without duplicating that file. It
adds support for:

* 2B and 4B baseline rejudges, with and without the manual;
* asymmetric title-only baseline, statement, and interactive runs;
* semantic de-duplication of ``*_full_rejudge2B.json`` and
  ``*_rejudge2B_full.json`` naming variants;
* completion/coverage and fallback diagnostics;
* judge-size-by-protocol comparisons;
* a difference-in-differences summary for the 0.8B-to-2B judge change;
* a common-record analysis of the three title-only conditions;
* explicit label-swap agreement and flip diagnostics;
* concise report tables and additional CSV files.

No experiment result JSON is modified.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import random
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


_STATE: Dict[str, Any] = {
    "rows": [],
    "context": {},
}


def _semantic_result_name(name: str) -> str:
    """Normalize only known filename-order aliases, not experiment identity."""
    lowered = name.casefold()
    lowered = re.sub(
        r"_full_rejudge(2b|4b)(?=\.json$)",
        r"_rejudge\1_full",
        lowered,
    )
    return lowered


def _preferred_file_score(row: Mapping[str, Any]) -> Tuple[int, int, float, int, str]:
    name = str(row.get("filename", ""))
    lowered = name.casefold()
    complete = int(bool(row.get("clean_3000_record_set")))
    records = int(row.get("unique_stage_pmid_records") or 0)
    modified = 0.0
    raw_modified = row.get("modified_at_utc")
    if raw_modified:
        try:
            modified = datetime.fromisoformat(str(raw_modified)).timestamp()
        except (TypeError, ValueError):
            modified = 0.0
    canonical_order = int(bool(re.search(r"_rejudge(?:2b|4b)_full\.json$", lowered)))
    if name == "interactive_results_BAB_swapped_labels_full.json":
        canonical_order += 2
    return complete, records, modified, canonical_order, lowered


def _judge_size_from_name(name: str) -> Optional[str]:
    lowered = name.casefold()
    if "rejudge4b" in lowered:
        return "4B"
    if "rejudge2b" in lowered:
        return "2B"
    return None


def _condition_completion(
    ns: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    expected_counts = ns["EXPECTED_STAGE_COUNTS"]
    unique_loose = {ns["make_stage_pmid_key"](row) for row in rows}
    unique_exact = {ns["make_exact_match_key"](row) for row in rows}
    stage_counts = Counter(
        row.get("stage")
        for row in rows
        if row.get("pmid") is not None
    )
    duplicate_exact = max(0, len(rows) - len(unique_exact))
    complete = (
        len(unique_loose) == ns["EXPECTED_TOTAL_RECORDS"]
        and duplicate_exact == 0
        and all(stage_counts.get(stage, 0) == count for stage, count in expected_counts.items())
    )
    return {
        "expected_records": ns["EXPECTED_TOTAL_RECORDS"],
        "unique_stage_pmid_count": len(unique_loose),
        "unique_exact_key_count": len(unique_exact),
        "missing_records": max(0, ns["EXPECTED_TOTAL_RECORDS"] - len(unique_loose)),
        "completion_rate": ns["safe_divide"](
            len(unique_loose), ns["EXPECTED_TOTAL_RECORDS"]
        ),
        "duplicate_exact_key_count": duplicate_exact,
        "stage_record_counts": dict(stage_counts),
        "is_complete": complete,
        "completion_status": "complete" if complete else "partial_or_invalid",
        "eligible_for_primary_ranking": complete,
    }


def _fallback_diagnostics(
    ns: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    fallback = [row for row in rows if row.get("needed_fallback") is True]
    direct = [row for row in rows if row.get("needed_fallback") is False]
    unknown = [row for row in rows if row.get("needed_fallback") is None]

    def metrics(subset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        value = ns["compute_accuracy_metrics"](subset)
        return {
            "records": len(subset),
            "strict_accuracy": value.get("strict_accuracy"),
            "valid_only_accuracy": value.get("valid_only_accuracy"),
            "balanced_accuracy": value.get("balanced_accuracy"),
            "unknown_predictions": value.get("unknown_prediction_count"),
        }

    by_stage: List[Dict[str, Any]] = []
    for stage in ns["EXPECTED_STAGE_COUNTS"]:
        stage_rows = [row for row in rows if row.get("stage") == stage]
        stage_fallback = [row for row in stage_rows if row.get("needed_fallback") is True]
        stage_known = [row for row in stage_rows if row.get("needed_fallback") is not None]
        by_stage.append(
            {
                "stage": stage,
                "records": len(stage_rows),
                "fallback_count": len(stage_fallback),
                "fallback_rate_among_known": ns["safe_divide"](
                    len(stage_fallback), len(stage_known)
                ),
            }
        )

    return {
        "records": len(rows),
        "fallback_known_records": len(fallback) + len(direct),
        "fallback_count": len(fallback),
        "direct_parse_count": len(direct),
        "fallback_unknown_count": len(unknown),
        "fallback_rate_among_known": ns["safe_divide"](
            len(fallback), len(fallback) + len(direct)
        ),
        "fallback_rate_all_records": ns["safe_divide"](len(fallback), len(rows)),
        "direct_parse_metrics": metrics(direct),
        "fallback_metrics": metrics(fallback),
        "by_stage": by_stage,
        "definition": (
            "needed_fallback=true means the normal structured-output parser did not "
            "supply the final verdict and the evaluation recovered it using its "
            "secondary scoring/parsing path. It is a run-quality flag, not itself an error."
        ),
    }


def _unique_exact_map(
    ns: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> Dict[Tuple[Any, ...], Mapping[str, Any]]:
    buckets: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[ns["make_exact_match_key"](row)].append(row)
    return {key: values[0] for key, values in buckets.items() if len(values) == 1}


def _strict_correct(row: Mapping[str, Any]) -> int:
    return int(row.get("binary_correct") is True)


def _percentile(values: Sequence[float], quantile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(len(ordered) - 1, low + 1)
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _cluster_bootstrap_mean(
    values_by_pmid: Mapping[str, Sequence[float]], samples: int, seed: int
) -> Optional[Tuple[float, float]]:
    clusters = [list(values) for _, values in sorted(values_by_pmid.items()) if values]
    if not clusters:
        return None
    rng = random.Random(seed)
    distribution: List[float] = []
    for _ in range(max(200, samples)):
        sampled = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        numerator = sum(sum(cluster) for cluster in sampled)
        denominator = sum(len(cluster) for cluster in sampled)
        if denominator:
            distribution.append(numerator / denominator)
    low = _percentile(distribution, 0.025)
    high = _percentile(distribution, 0.975)
    if low is None or high is None:
        return None
    return low, high


def _compact_comparison(
    ns: Mapping[str, Any],
    comparison: Mapping[str, Any],
    left_complete: bool,
    right_complete: bool,
    content_required: bool = False,
) -> Dict[str, Any]:
    bootstrap = comparison.get("clustered_bootstrap", {}) or {}
    outcomes = comparison.get("paired_outcomes", {}) or {}
    content = comparison.get("content_identity", {}) or {}
    pair_count = int(comparison.get("exact_pair_count") or 0)
    status = str(comparison.get("comparison_status") or "unavailable")
    content_verified: Optional[bool] = None
    if content_required and pair_count:
        available = int(content.get("argument_content_pair_count") or 0)
        matches = int(content.get("argument_content_match_count") or 0)
        content_verified = available == pair_count and matches == pair_count
        if not content_verified:
            status = (
                "content_mismatch"
                if available and matches < available
                else "conditionally_controlled_content_not_fully_verified"
            )
    if not left_complete or not right_complete:
        status = "partial_descriptive_excluded_from_primary_claims"
    return {
        "comparison_id": comparison.get("comparison_id"),
        "left_condition": comparison.get("left_condition"),
        "right_condition": comparison.get("right_condition"),
        "left_complete": left_complete,
        "right_complete": right_complete,
        "primary_eligible": left_complete and right_complete,
        "comparison_status": status,
        "exact_pairs": pair_count,
        "left_accuracy": (comparison.get("left_paired_metrics") or {}).get("strict_accuracy"),
        "right_accuracy": (comparison.get("right_paired_metrics") or {}).get("strict_accuracy"),
        "accuracy_difference_right_minus_left": comparison.get(
            "strict_accuracy_difference_right_minus_left"
        ),
        "balanced_accuracy_difference_right_minus_left": comparison.get(
            "balanced_accuracy_difference_right_minus_left"
        ),
        "clustered_bootstrap_ci_95": bootstrap.get("strict_confidence_interval_95"),
        "mcnemar_p_value": comparison.get("mcnemar_p_value"),
        "fixed_by_right": outcomes.get("records_fixed_by_right"),
        "broken_by_right": outcomes.get("records_broken_by_right"),
        "prediction_agreement_rate": outcomes.get("prediction_agreement_rate"),
        "argument_content_verified_for_all_pairs": content_verified,
        "argument_content_pair_count": content.get("argument_content_pair_count"),
        "argument_content_match_count": content.get("argument_content_match_count"),
    }


def _difference_in_differences(
    ns: Mapping[str, Any],
    rows_by_condition: Mapping[str, Sequence[Mapping[str, Any]]],
    protocol_name: str,
    baseline_small: str,
    baseline_large: str,
    protocol_small: str,
    protocol_large: str,
    context: Mapping[str, Any],
) -> Dict[str, Any]:
    condition_ids = (baseline_small, baseline_large, protocol_small, protocol_large)
    maps = {
        condition: _unique_exact_map(ns, rows_by_condition.get(condition, []))
        for condition in condition_ids
    }
    if any(not maps[condition] for condition in condition_ids):
        return {
            "protocol": protocol_name,
            "status": "unavailable",
            "common_exact_records": 0,
        }
    shared = set(maps[baseline_small])
    for condition in condition_ids[1:]:
        shared.intersection_update(maps[condition])
    if not shared:
        return {
            "protocol": protocol_name,
            "status": "unavailable_no_four_way_exact_overlap",
            "common_exact_records": 0,
        }

    baseline_changes: List[float] = []
    protocol_changes: List[float] = []
    did_values: List[float] = []
    by_pmid: Dict[str, List[float]] = defaultdict(list)
    for key in sorted(shared, key=repr):
        baseline_change = (
            _strict_correct(maps[baseline_large][key])
            - _strict_correct(maps[baseline_small][key])
        )
        protocol_change = (
            _strict_correct(maps[protocol_large][key])
            - _strict_correct(maps[protocol_small][key])
        )
        did = float(protocol_change - baseline_change)
        baseline_changes.append(float(baseline_change))
        protocol_changes.append(float(protocol_change))
        did_values.append(did)
        pmid = str(maps[protocol_small][key].get("pmid") or repr(key))
        by_pmid[pmid].append(did)

    samples = int(context.get("bootstrap_samples", 10_000))
    seed = int(context.get("random_seed", 42)) + sum(ord(char) for char in protocol_name)
    interval = _cluster_bootstrap_mean(by_pmid, samples, seed)
    return {
        "protocol": protocol_name,
        "status": "matched_difference_in_differences",
        "common_exact_records": len(shared),
        "baseline_gain_0_8B_to_2B": sum(baseline_changes) / len(baseline_changes),
        "protocol_gain_0_8B_to_2B": sum(protocol_changes) / len(protocol_changes),
        "difference_in_differences": sum(did_values) / len(did_values),
        "clustered_bootstrap_ci_95": interval,
        "cluster_unit": "PMID",
        "interpretation": (
            "Positive values mean that moving from the 0.8B to the 2B judge helped "
            "this protocol more than it helped the no-manual baseline on the same exact records."
        ),
        "causal_guardrail": (
            "This estimates a differential judge-size association. It does not by "
            "itself prove that debate is better than direct evidence."
        ),
    }


def _build_latest_analysis(
    ns: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    global_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    context = _STATE.get("context", {})
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("condition_id"))].append(row)

    condition_metrics = {
        str(row.get("condition_id")): row
        for row in global_metrics.get("condition_metrics", [])
    }
    stage_metrics = global_metrics.get("stage_metrics", [])
    stages_by_condition: Dict[str, Dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in stage_metrics:
        stages_by_condition[str(row.get("condition_id"))][str(row.get("stage"))] = row

    run_quality: List[Dict[str, Any]] = []
    fallback_rows: List[Dict[str, Any]] = []
    for condition_id, metric in sorted(condition_metrics.items()):
        fallback = _fallback_diagnostics(ns, grouped.get(condition_id, []))
        run_quality.append(
            {
                "condition_id": condition_id,
                "display_name": metric.get("display_name"),
                "source_files": metric.get("source_files"),
                "records": metric.get("unique_stage_pmid_count"),
                "expected_records": metric.get("expected_records"),
                "missing_records": metric.get("missing_records"),
                "completion_rate": metric.get("completion_rate"),
                "is_complete": metric.get("is_complete"),
                "unknown_predictions": metric.get("unknown_prediction_count"),
                "valid_prediction_coverage": metric.get("valid_prediction_coverage"),
                "fallback_count": fallback.get("fallback_count"),
                "fallback_rate": fallback.get("fallback_rate_among_known"),
                "eligible_for_primary_ranking": metric.get("eligible_for_primary_ranking"),
            }
        )
        fallback_rows.append(
            {
                "condition_id": condition_id,
                "display_name": metric.get("display_name"),
                **fallback,
            }
        )

    protocol_specs = [
        ("Baseline, no manual", "baseline.robust_0.8B.no_manual", "0.8B", False),
        ("Baseline, no manual", "baseline.robust_2B.no_manual", "2B", False),
        ("Baseline, no manual", "baseline.robust_4B.no_manual", "4B", False),
        ("Baseline, with manual", "baseline.robust_0.8B.with_manual", "0.8B", True),
        ("Baseline, with manual", "baseline.robust_2B.with_manual", "2B", True),
        ("Baseline, with manual", "baseline.robust_4B.with_manual", "4B", True),
        ("Independent statements", "statement.robust_0.8B", "0.8B", False),
        ("Independent statements", "statement.rejudge_2B", "2B", False),
        ("Interactive ABA", "interactive.robust_0.8B.ABA", "0.8B", False),
        ("Interactive ABA", "interactive.rejudge_2B.ABA", "2B", False),
        ("Interactive BAB", "interactive.robust_0.8B.BAB", "0.8B", False),
        ("Interactive BAB", "interactive.rejudge_2B.BAB", "2B", False),
    ]
    judge_protocol: List[Dict[str, Any]] = []
    for protocol, condition_id, judge, manual in protocol_specs:
        metric = condition_metrics.get(condition_id)
        if not metric:
            continue
        stage = stages_by_condition.get(condition_id, {})
        judge_protocol.append(
            {
                "protocol": protocol,
                "condition_id": condition_id,
                "judge": judge,
                "manual": manual,
                "records": metric.get("unique_stage_pmid_count"),
                "complete": metric.get("is_complete"),
                "strict_accuracy": metric.get("strict_accuracy"),
                "balanced_accuracy": metric.get("balanced_accuracy"),
                "true_tag_accuracy": (stage.get("Round 1: True Tag") or {}).get("strict_accuracy"),
                "unrelated_tag_accuracy": (stage.get("Round 2: Unrelated Tag") or {}).get("strict_accuracy"),
                "similar_tag_accuracy": (stage.get("Round 3: Similar Tag") or {}).get("strict_accuracy"),
                "false_positive_rate": metric.get("false_positive_rate"),
                "false_negative_rate": metric.get("false_negative_rate"),
                "yes_prediction_rate": metric.get("yes_prediction_rate"),
                "fallback_rate": metric.get("fallback_rate_among_known"),
            }
        )

    comparison_specs = [
        ("Baseline no manual: 0.8B → 2B", "baseline.robust_0.8B.no_manual", "baseline.robust_2B.no_manual", False),
        ("Baseline no manual: 2B → 4B", "baseline.robust_2B.no_manual", "baseline.robust_4B.no_manual", False),
        ("Baseline with manual: 0.8B → 2B", "baseline.robust_0.8B.with_manual", "baseline.robust_2B.with_manual", False),
        ("Baseline with manual: 2B → 4B", "baseline.robust_2B.with_manual", "baseline.robust_4B.with_manual", False),
        ("Manual effect at 0.8B", "baseline.robust_0.8B.no_manual", "baseline.robust_0.8B.with_manual", False),
        ("Manual effect at 2B", "baseline.robust_2B.no_manual", "baseline.robust_2B.with_manual", False),
        ("Manual effect at 4B", "baseline.robust_4B.no_manual", "baseline.robust_4B.with_manual", False),
        ("Statements: 0.8B → 2B", "statement.robust_0.8B", "statement.rejudge_2B", True),
        ("Interactive ABA: 0.8B → 2B", "interactive.robust_0.8B.ABA", "interactive.rejudge_2B.ABA", True),
        ("Interactive BAB: 0.8B → 2B", "interactive.robust_0.8B.BAB", "interactive.rejudge_2B.BAB", True),
    ]
    judge_comparisons: List[Dict[str, Any]] = []
    for label, left, right, content_required in comparison_specs:
        if not grouped.get(left) or not grouped.get(right):
            continue
        raw = ns["compute_paired_comparison"](
            left,
            right,
            rows,
            "current_judge_or_manual_comparison",
            "controlled_after_exact_matching",
            context,
        )
        compact = _compact_comparison(
            ns,
            raw,
            bool((condition_metrics.get(left) or {}).get("is_complete")),
            bool((condition_metrics.get(right) or {}).get("is_complete")),
            content_required,
        )
        compact["comparison"] = label
        judge_comparisons.append(compact)

    did_specs = [
        ("Independent statements", "statement.robust_0.8B", "statement.rejudge_2B"),
        ("Interactive ABA", "interactive.robust_0.8B.ABA", "interactive.rejudge_2B.ABA"),
        ("Interactive BAB", "interactive.robust_0.8B.BAB", "interactive.rejudge_2B.BAB"),
    ]
    did_rows = [
        _difference_in_differences(
            ns,
            grouped,
            protocol,
            "baseline.robust_0.8B.no_manual",
            "baseline.robust_2B.no_manual",
            small,
            large,
            context,
        )
        for protocol, small, large in did_specs
    ]

    title_conditions = (
        "asymmetric_titleonly.baseline",
        "asymmetric_titleonly.statement",
        "asymmetric_titleonly.interactive.ABA",
    )
    title_maps = {
        condition: _unique_exact_map(ns, grouped.get(condition, []))
        for condition in title_conditions
    }
    shared_title: set = set(title_maps[title_conditions[0]])
    for condition in title_conditions[1:]:
        shared_title.intersection_update(title_maps[condition])
    title_common_metrics: List[Dict[str, Any]] = []
    title_subset_rows: List[Mapping[str, Any]] = []
    for condition in title_conditions:
        subset = [title_maps[condition][key] for key in shared_title]
        title_subset_rows.extend(subset)
        metric = ns["compute_accuracy_metrics"](subset)
        title_common_metrics.append(
            {
                "condition_id": condition,
                "display_name": ns["_condition_display_name"](condition),
                "common_exact_records": len(subset),
                "strict_accuracy": metric.get("strict_accuracy"),
                "balanced_accuracy": metric.get("balanced_accuracy"),
                "false_positive_rate": metric.get("false_positive_rate"),
                "false_negative_rate": metric.get("false_negative_rate"),
                "yes_prediction_rate": metric.get("yes_prediction_rate"),
            }
        )
    title_comparisons: List[Dict[str, Any]] = []
    for label, left, right in (
        ("Baseline → statements", title_conditions[0], title_conditions[1]),
        ("Baseline → interactive ABA", title_conditions[0], title_conditions[2]),
        ("Statements → interactive ABA", title_conditions[1], title_conditions[2]),
    ):
        if shared_title:
            raw = ns["compute_paired_comparison"](
                left,
                right,
                title_subset_rows,
                "asymmetric_titleonly_common_subset",
                "matched_protocol_comparison",
                context,
            )
            compact = _compact_comparison(ns, raw, True, True, False)
            compact["comparison"] = label
            title_comparisons.append(compact)

    original_bab = "interactive.robust_0.8B.BAB"
    swapped_bab = "interactive.robust_0.8B.BAB_swapped_labels"
    label_swap: Dict[str, Any] = {"status": "unavailable"}
    if grouped.get(original_bab) and grouped.get(swapped_bab):
        paired = ns["pair_conditions"](grouped[original_bab], grouped[swapped_bab])
        outcomes = ns["compute_paired_outcome_counts"](paired.get("pairs", []))
        verification_rows = ns["verify_swapped_bab_content"](rows)
        verification = verification_rows[0] if verification_rows else {}
        label_swap = {
            "status": verification.get("comparison_status", "unverified"),
            "exact_pairs": paired.get("pair_count"),
            "prediction_agreement_count": outcomes.get("prediction_agreement_count"),
            "prediction_agreement_rate": outcomes.get("prediction_agreement_rate"),
            "prediction_flip_count": (
                (outcomes.get("pair_count") or 0)
                - (outcomes.get("prediction_agreement_count") or 0)
            ),
            "prediction_flip_rate": (
                None
                if not outcomes.get("pair_count")
                else 1.0 - float(outcomes.get("prediction_agreement_rate") or 0.0)
            ),
            "yes_to_no": outcomes.get("yes_to_no_count"),
            "no_to_yes": outcomes.get("no_to_yes_count"),
            "correctness_gained_after_swap": outcomes.get("records_fixed_by_right"),
            "correctness_lost_after_swap": outcomes.get("records_broken_by_right"),
            "net_accuracy_change": outcomes.get("right_minus_left_strict_accuracy"),
            "content_verified_pairs": verification.get("content_verified_pair_count"),
            "content_mismatch_pairs": verification.get("content_mismatch_pair_count"),
            "clean_label_test": verification.get("clean_label_test"),
        }

    complete_metrics = [
        metric for metric in condition_metrics.values() if metric.get("is_complete")
    ]
    complete_metrics.sort(
        key=lambda row: (
            row.get("balanced_accuracy") is not None,
            row.get("balanced_accuracy") or -1.0,
        ),
        reverse=True,
    )
    partial = [row for row in run_quality if not row.get("is_complete")]
    high_fallback = [
        row
        for row in run_quality
        if row.get("fallback_rate") is not None and row.get("fallback_rate") >= 0.10
    ]

    takeaways: List[str] = []
    if complete_metrics:
        best = complete_metrics[0]
        takeaways.append(
            f"Among complete runs, {best.get('display_name')} has the highest observed "
            f"balanced accuracy ({100.0 * float(best.get('balanced_accuracy') or 0):.1f}%)."
        )
    for comparison in judge_comparisons:
        if comparison.get("comparison") in {
            "Baseline no manual: 0.8B → 2B",
            "Baseline with manual: 0.8B → 2B",
            "Statements: 0.8B → 2B",
            "Interactive ABA: 0.8B → 2B",
            "Interactive BAB: 0.8B → 2B",
        } and comparison.get("accuracy_difference_right_minus_left") is not None:
            takeaways.append(
                f"{comparison['comparison']} changed exact-pair accuracy by "
                f"{100.0 * float(comparison['accuracy_difference_right_minus_left']):+.1f} percentage points."
            )
    if title_comparisons:
        for comparison in title_comparisons[:2]:
            difference = comparison.get("accuracy_difference_right_minus_left")
            if difference is not None:
                takeaways.append(
                    f"In the common title-only subset, {comparison['comparison'].lower()} "
                    f"changed accuracy by {100.0 * float(difference):+.1f} percentage points."
                )
    if partial:
        takeaways.append(
            "Partial runs are reported for diagnostics but excluded from the primary ranking: "
            + ", ".join(str(row.get("display_name")) for row in partial)
            + "."
        )
    if high_fallback:
        takeaways.append(
            "High fallback use requires parser-level caution in: "
            + ", ".join(
                f"{row.get('display_name')} ({100.0 * float(row.get('fallback_rate')):.1f}%)"
                for row in high_fallback
            )
            + "."
        )
    if label_swap.get("prediction_flip_rate") is not None:
        takeaways.append(
            "The BAB label swap changed individual verdicts on "
            f"{100.0 * float(label_swap['prediction_flip_rate']):.1f}% of exact pairs, "
            f"while the net accuracy change was {100.0 * float(label_swap.get('net_accuracy_change') or 0):+.1f} points."
        )

    return {
        "run_quality": run_quality,
        "fallback_diagnostics": fallback_rows,
        "judge_size_by_protocol": judge_protocol,
        "judge_and_manual_comparisons": judge_comparisons,
        "judge_size_difference_in_differences": did_rows,
        "titleonly_common_subset": {
            "conditions": list(title_conditions),
            "common_exact_records": len(shared_title),
            "condition_metrics": title_common_metrics,
            "comparisons": title_comparisons,
            "guardrail": (
                "The common subset makes the three title-only protocols directly "
                "comparable on record identity. It does not make their generated arguments identical."
            ),
        },
        "label_swap_stability": label_swap,
        "takeaways": takeaways,
        "fallback_definition": (
            "Fallback means that the intended structured verdict could not be used "
            "directly and a secondary recovery/scoring route supplied the prediction. "
            "It is not automatically wrong, but a high rate can indicate formatting, "
            "truncation, prompt, or parser incompatibility."
        ),
    }


def _latest_markdown(ns: Mapping[str, Any], latest: Mapping[str, Any]) -> str:
    table = ns["format_markdown_table"]
    lines = [
        "## Executive summary of the current runs",
        "",
    ]
    for takeaway in latest.get("takeaways", []):
        lines.append(f"- {takeaway}")
    lines.extend(
        [
            "",
            "### What fallback means",
            "",
            str(latest.get("fallback_definition")),
            "",
            "### Run quality and completion",
            "",
        ]
    )
    quality_rows = []
    for row in latest.get("run_quality", []):
        quality_rows.append(
            {
                "Condition": row.get("display_name"),
                "Records": row.get("records"),
                "Missing": row.get("missing_records"),
                "Complete": row.get("is_complete"),
                "Unknown": row.get("unknown_predictions"),
                "Coverage": row.get("valid_prediction_coverage"),
                "Fallback": row.get("fallback_rate"),
                "Primary ranking": row.get("eligible_for_primary_ranking"),
            }
        )
    lines.append(table(quality_rows, list(quality_rows[0].keys())) if quality_rows else "_No run-quality rows available._")

    lines.extend(["", "### Judge size by protocol", ""])
    protocol_rows = []
    for row in latest.get("judge_size_by_protocol", []):
        protocol_rows.append(
            {
                "Protocol": row.get("protocol"),
                "Judge": row.get("judge"),
                "Manual": row.get("manual"),
                "N": row.get("records"),
                "Complete": row.get("complete"),
                "Accuracy": row.get("strict_accuracy"),
                "Balanced": row.get("balanced_accuracy"),
                "True tag": row.get("true_tag_accuracy"),
                "Unrelated": row.get("unrelated_tag_accuracy"),
                "Similar": row.get("similar_tag_accuracy"),
                "FPR": row.get("false_positive_rate"),
                "FNR": row.get("false_negative_rate"),
                "Fallback": row.get("fallback_rate"),
            }
        )
    lines.append(table(protocol_rows, list(protocol_rows[0].keys())) if protocol_rows else "_No judge-size rows available._")

    lines.extend(["", "### Exact-pair judge-size and manual comparisons", ""])
    comparison_rows = []
    for row in latest.get("judge_and_manual_comparisons", []):
        interval = row.get("clustered_bootstrap_ci_95")
        comparison_rows.append(
            {
                "Comparison": row.get("comparison"),
                "Pairs": row.get("exact_pairs"),
                "A accuracy": row.get("left_accuracy"),
                "B accuracy": row.get("right_accuracy"),
                "Δ B−A": row.get("accuracy_difference_right_minus_left"),
                "95% CI": interval,
                "McNemar p": row.get("mcnemar_p_value"),
                "Status": row.get("comparison_status"),
            }
        )
    lines.append(table(comparison_rows, list(comparison_rows[0].keys())) if comparison_rows else "_No current exact-pair comparisons available._")

    lines.extend(["", "### Does judge size help debate more than the baseline?", ""])
    did_rows = []
    for row in latest.get("judge_size_difference_in_differences", []):
        did_rows.append(
            {
                "Protocol": row.get("protocol"),
                "Common records": row.get("common_exact_records"),
                "Baseline 0.8→2B gain": row.get("baseline_gain_0_8B_to_2B"),
                "Protocol 0.8→2B gain": row.get("protocol_gain_0_8B_to_2B"),
                "Difference-in-differences": row.get("difference_in_differences"),
                "95% CI": row.get("clustered_bootstrap_ci_95"),
                "Status": row.get("status"),
            }
        )
    lines.append(table(did_rows, list(did_rows[0].keys())) if did_rows else "_No difference-in-differences rows available._")
    lines.append(
        "\n> A positive difference-in-differences means that the 0.8B→2B judge change helped the debate protocol more than it helped the no-manual baseline. It does not show that debate beats the baseline."
    )

    title = latest.get("titleonly_common_subset", {}) or {}
    lines.extend(["", "### Asymmetric title-only conditions on one common subset", ""])
    title_rows = []
    for row in title.get("condition_metrics", []):
        title_rows.append(
            {
                "Condition": row.get("display_name"),
                "Common records": row.get("common_exact_records"),
                "Accuracy": row.get("strict_accuracy"),
                "Balanced": row.get("balanced_accuracy"),
                "FPR": row.get("false_positive_rate"),
                "FNR": row.get("false_negative_rate"),
                "Yes rate": row.get("yes_prediction_rate"),
            }
        )
    lines.append(table(title_rows, list(title_rows[0].keys())) if title_rows else "_The three title-only conditions do not have a usable three-way exact intersection._")
    title_comparisons = []
    for row in title.get("comparisons", []):
        title_comparisons.append(
            {
                "Comparison": row.get("comparison"),
                "Pairs": row.get("exact_pairs"),
                "Δ B−A": row.get("accuracy_difference_right_minus_left"),
                "95% CI": row.get("clustered_bootstrap_ci_95"),
                "McNemar p": row.get("mcnemar_p_value"),
            }
        )
    if title_comparisons:
        lines.extend(["", table(title_comparisons, list(title_comparisons[0].keys()))])

    label = latest.get("label_swap_stability", {}) or {}
    lines.extend(["", "### BAB displayed-label stability", ""])
    if label.get("status") != "unavailable":
        lines.append(
            table(
                [
                    {
                        "Pairs": label.get("exact_pairs"),
                        "Agreement": label.get("prediction_agreement_rate"),
                        "Flips": label.get("prediction_flip_count"),
                        "Flip rate": label.get("prediction_flip_rate"),
                        "Yes→No": label.get("yes_to_no"),
                        "No→Yes": label.get("no_to_yes"),
                        "Correctness gained": label.get("correctness_gained_after_swap"),
                        "Correctness lost": label.get("correctness_lost_after_swap"),
                        "Net accuracy Δ": label.get("net_accuracy_change"),
                        "Content test": label.get("status"),
                    }
                ],
                [
                    "Pairs", "Agreement", "Flips", "Flip rate", "Yes→No", "No→Yes",
                    "Correctness gained", "Correctness lost", "Net accuracy Δ", "Content test",
                ],
            )
        )
    else:
        lines.append("_The original and swapped BAB conditions were not both available._")
    return "\n".join(lines)


def install_latest_results_support(ns: Dict[str, Any]) -> None:
    """Install the current-results support into the importing analysis module."""
    if ns.get("LATEST_RESULTS_EXTENSION_VERSION") == "2.0":
        return
    ns["LATEST_RESULTS_EXTENSION_VERSION"] = "2.0"

    original_build_context = ns["build_run_context"]
    original_family = ns["infer_file_family"]
    original_generation = ns["infer_file_generation"]
    original_provenance = ns["infer_file_provenance"]
    original_reconcile = ns["reconcile_result_and_script_provenance"]
    original_choose = ns["choose_canonical_analysis_files"]
    original_condition_id = ns["_condition_id_for"]
    original_display_name = ns["_condition_display_name"]
    original_normalize_all = ns["normalize_all_files"]
    original_build_row = ns["build_normalized_row"]
    original_catalog = ns["build_condition_catalog"]
    original_condition_metrics = ns["compute_condition_metrics"]
    original_synthesis = ns["build_cross_experiment_synthesis"]
    original_assemble = ns["assemble_analysis_bundle"]
    original_render_report = ns["render_markdown_report"]
    original_write_outputs = ns["write_all_analysis_outputs"]
    original_find_tables = ns["_report_find_tables"]
    original_report_difference = ns["_report_difference"]
    original_report_ci = ns["_report_ci"]
    original_report_count = ns["_report_count"]

    def build_run_context(args: Any) -> Dict[str, Any]:
        context = original_build_context(args)
        _STATE["context"] = context
        return context

    def infer_file_family(path: Path, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> str:
        lowered = path.name.casefold()
        if "asymmetric_titleonly" in lowered:
            if "interactive" in lowered:
                return "interactive"
            if "statement" in lowered:
                return "statement"
            if "baseline" in lowered:
                return "baseline"
        return original_family(path, payload, schema)

    def infer_file_generation(path: Path, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> str:
        lowered = path.name.casefold()
        if "asymmetric_titleonly" in lowered:
            return "asymmetric_titleonly"
        if "rejudge4b" in lowered:
            return "rejudge_4B"
        if "rejudge2b" in lowered:
            return "rejudge_2B"
        return original_generation(path, payload, schema)

    def infer_file_provenance(path: Path, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> Dict[str, Any]:
        result = dict(original_provenance(path, payload, schema))
        generation = infer_file_generation(path, payload, schema)
        family = infer_file_family(path, payload, schema)
        result["generation"] = generation
        result["family"] = family
        statuses = dict(result.get("attribute_status", {}) or {})
        size = _judge_size_from_name(path.name)
        if size:
            result["judge_model"] = f"Qwen3.5-{size}"
            statuses["judge_model"] = "verified_from_result_filename"
        if generation == "asymmetric_titleonly":
            metadata = payload.get("metadata", {})
            found, found_path = ns["_find_first_mapping_key"](
                metadata,
                ("judge_model", "judge_model_id", "judge_model_name"),
            )
            if found_path is not None and found is not ns["MISSING"]:
                result["judge_model"] = str(found)
                statuses["judge_model"] = "verified_from_embedded_metadata"
            else:
                result["judge_model"] = None
                statuses["judge_model"] = "unknown_not_encoded_in_filename"
            result["judge_input_scope"] = "title_only"
            statuses["judge_input_scope"] = "verified_from_result_filename"
        else:
            result["judge_input_scope"] = "standard_experiment_input"
        lowered = path.name.casefold()
        if family == "baseline":
            if "nomanual" in lowered:
                result["manual_in_judge_prompt"] = False
                statuses["manual_in_judge_prompt"] = "verified_from_result_filename"
            elif "withmanual" in lowered:
                result["manual_in_judge_prompt"] = True
                statuses["manual_in_judge_prompt"] = "verified_from_result_filename"
        result["attribute_status"] = statuses
        return result

    def reconcile_result_and_script_provenance(
        inventory: Sequence[Mapping[str, Any]],
        script_features: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        output = original_reconcile(inventory, script_features)
        by_name = {str(row.get("filename")): row for row in inventory}
        for row in output:
            filename = str(row.get("filename", ""))
            size = _judge_size_from_name(filename)
            statuses = dict(row.get("attribute_status", {}) or {})
            if size:
                row["judge_model"] = f"Qwen3.5-{size}"
                row["generation"] = f"rejudge_{size}"
                statuses["judge_model"] = "verified_from_result_filename"
            if "asymmetric_titleonly" in filename.casefold():
                row["generation"] = "asymmetric_titleonly"
                row["judge_input_scope"] = "title_only"
                statuses["judge_input_scope"] = "verified_from_result_filename"
            lowered = filename.casefold()
            if "nomanual" in lowered:
                row["manual_in_judge_prompt"] = False
            elif "withmanual" in lowered:
                row["manual_in_judge_prompt"] = True
            row["attribute_status"] = statuses
            inventory_row = by_name.get(filename)
            if isinstance(inventory_row, dict):
                inventory_row["reconciled_provenance"] = dict(row)
        return output

    def choose_canonical_analysis_files(
        inventory: Sequence[Mapping[str, Any]],
        duplicate_groups: Sequence[Mapping[str, Any]],
    ) -> List[Path]:
        loaded = [row for row in inventory if row.get("load_status") == "loaded"]
        by_path = {Path(row["path"]).resolve(): row for row in loaded}
        excluded: set = set()

        for group in duplicate_groups:
            if not group.get("is_duplicate_group"):
                continue
            members = [
                by_path[Path(raw).resolve()]
                for raw in group.get("paths", [])
                if Path(raw).resolve() in by_path
            ]
            if not members:
                continue
            chosen = max(members, key=_preferred_file_score)
            for member in members:
                path = Path(member["path"]).resolve()
                if path != Path(chosen["path"]).resolve():
                    excluded.add(path)

        semantic_groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in loaded:
            semantic_groups[_semantic_result_name(str(row.get("filename", "")))].append(row)
        for members in semantic_groups.values():
            if len(members) < 2:
                continue
            chosen = max(members, key=_preferred_file_score)
            for member in members:
                path = Path(member["path"]).resolve()
                if path != Path(chosen["path"]).resolve():
                    excluded.add(path)

        return sorted(
            [path for path in by_path if path not in excluded],
            key=lambda path: (path.name.casefold(), path.name),
        )

    def condition_id_for(
        source_path: Path,
        file_info: Mapping[str, Any],
        variant: Optional[str] = None,
    ) -> str:
        lowered = source_path.name.casefold()
        family = str(file_info.get("family") or "unknown")
        if "asymmetric_titleonly" in lowered:
            if family == "baseline":
                return "asymmetric_titleonly.baseline"
            if family == "statement":
                return "asymmetric_titleonly.statement"
            if family == "interactive":
                return f"asymmetric_titleonly.interactive.{variant or 'ABA'}"
        size = _judge_size_from_name(source_path.name)
        if family == "baseline" and size:
            manual = "no_manual" if "nomanual" in lowered else "with_manual" if "withmanual" in lowered else "manual_unknown"
            return f"baseline.robust_{size}.{manual}"
        return original_condition_id(source_path, file_info, variant)

    display_names = {
        "baseline.robust_2B.no_manual": "Baseline 2B — no manual",
        "baseline.robust_2B.with_manual": "Baseline 2B — with manual",
        "baseline.robust_4B.no_manual": "Baseline 4B — no manual",
        "baseline.robust_4B.with_manual": "Baseline 4B — with manual",
        "asymmetric_titleonly.baseline": "Title-only asymmetric — baseline",
        "asymmetric_titleonly.statement": "Title-only asymmetric — statements",
        "asymmetric_titleonly.interactive.ABA": "Title-only asymmetric — interactive ABA",
    }

    def condition_display_name(condition_id: str) -> str:
        return display_names.get(condition_id, original_display_name(condition_id))

    def build_normalized_row(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        row = original_build_row(*args, **kwargs)
        source_path = args[0] if args else kwargs.get("source_path")
        file_info = args[1] if len(args) > 1 else kwargs.get("file_info", {})
        provenance = (
            file_info.get("reconciled_provenance")
            or file_info.get("provenance")
            or {}
        )
        row["judge_input_scope"] = provenance.get("judge_input_scope")
        if source_path is not None and "asymmetric_titleonly" in Path(source_path).name.casefold():
            row["judge_input_scope"] = "title_only"
        return row

    def normalize_all_files(*args: Any, **kwargs: Any) -> Any:
        result = original_normalize_all(*args, **kwargs)
        _STATE["rows"] = result[0]
        return result

    def build_condition_catalog(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        result = original_catalog(rows)
        grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("condition_id"))].append(row)
        for item in result:
            condition_rows = grouped.get(str(item.get("condition_id")), [])
            item.update(_condition_completion(ns, condition_rows))
            item.update(
                {
                    "judge_input_scope": (
                        condition_rows[0].get("judge_input_scope") if condition_rows else None
                    )
                }
            )
            fallback = _fallback_diagnostics(ns, condition_rows)
            item["fallback_count"] = fallback.get("fallback_count")
            item["fallback_rate_among_known"] = fallback.get("fallback_rate_among_known")
        return result

    def compute_condition_metrics(rows: Sequence[Mapping[str, Any]]) -> Any:
        condition_table, stage_table = original_condition_metrics(rows)
        grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("condition_id"))].append(row)
        completion_by_condition: Dict[str, Dict[str, Any]] = {}
        for item in condition_table:
            condition_id = str(item.get("condition_id"))
            condition_rows = grouped.get(condition_id, [])
            completion = _condition_completion(ns, condition_rows)
            completion_by_condition[condition_id] = completion
            item.update(completion)
            fallback = _fallback_diagnostics(ns, condition_rows)
            item.update(
                {
                    "fallback_count": fallback.get("fallback_count"),
                    "fallback_rate_among_known": fallback.get("fallback_rate_among_known"),
                    "direct_parse_count": fallback.get("direct_parse_count"),
                    "direct_parse_accuracy": (fallback.get("direct_parse_metrics") or {}).get("strict_accuracy"),
                    "fallback_accuracy": (fallback.get("fallback_metrics") or {}).get("strict_accuracy"),
                    "judge_input_scope": (
                        condition_rows[0].get("judge_input_scope") if condition_rows else None
                    ),
                }
            )
        for item in stage_table:
            item.update(completion_by_condition.get(str(item.get("condition_id")), {}))
        return condition_table, stage_table

    def build_cross_experiment_synthesis(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        result = original_synthesis(*args, **kwargs)
        global_metrics = args[0] if args else kwargs.get("global_metrics", {})
        latest = _build_latest_analysis(ns, _STATE.get("rows", []), global_metrics)
        if isinstance(global_metrics, dict):
            global_metrics["latest_results"] = latest
        result["latest_results"] = latest
        result["takeaways"] = list(latest.get("takeaways", [])) + list(result.get("takeaways", []))

        complete_metrics = [
            row
            for row in global_metrics.get("condition_metrics", [])
            if row.get("is_complete")
        ]
        complete_metrics.sort(
            key=lambda row: (
                row.get("balanced_accuracy") is not None,
                row.get("balanced_accuracy") or -1.0,
                row.get("strict_accuracy") or -1.0,
            ),
            reverse=True,
        )
        result["condition_ranking"] = [
            {
                "condition": row.get("display_name"),
                "strict_accuracy": row.get("strict_accuracy"),
                "valid_only_accuracy": row.get("valid_only_accuracy"),
                "balanced_accuracy": row.get("balanced_accuracy"),
                "unknown_rate": row.get("unknown_prediction_rate"),
                "records": row.get("unique_stage_pmid_count"),
                "complete": row.get("is_complete"),
            }
            for row in complete_metrics
        ]
        result["partial_runs_excluded_from_ranking"] = [
            row
            for row in latest.get("run_quality", [])
            if not row.get("is_complete")
        ]
        return result

    def assemble_analysis_bundle(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        bundle = original_assemble(*args, **kwargs)
        latest = (bundle.get("global_metrics", {}) or {}).get("latest_results", {})
        bundle.setdefault("sections", {})["latest_current_runs"] = latest
        tables = bundle.setdefault("tables", {})
        tables["run_quality"] = latest.get("run_quality", [])
        tables["fallback_diagnostics"] = latest.get("fallback_diagnostics", [])
        tables["judge_size_by_protocol"] = latest.get("judge_size_by_protocol", [])
        tables["judge_size_comparisons"] = latest.get("judge_and_manual_comparisons", [])
        tables["judge_size_difference_in_differences"] = latest.get(
            "judge_size_difference_in_differences", []
        )
        title = latest.get("titleonly_common_subset", {}) or {}
        tables["titleonly_common_subset"] = title.get("condition_metrics", [])
        tables["titleonly_comparisons"] = title.get("comparisons", [])
        label = latest.get("label_swap_stability", {}) or {}
        tables["label_swap_stability"] = [label] if label else []
        return bundle

    def report_difference(comparison: Mapping[str, Any]) -> Optional[float]:
        for path in (
            "strict_accuracy_difference_right_minus_left",
            "accuracy_difference_right_minus_left",
            "paired.accuracy_difference_right_minus_left",
            "clustered_bootstrap.strict_difference_right_minus_left",
        ):
            value = ns["_report_direct_get"](comparison, path)
            if value is not ns["MISSING"] and value is not None:
                return ns["_report_fraction"](value)
        return original_report_difference(comparison)

    def report_ci(value: Mapping[str, Any]) -> Optional[Tuple[float, float]]:
        for path in (
            "clustered_bootstrap_ci_95",
            "paired.clustered_bootstrap_95ci",
            "clustered_bootstrap.strict_confidence_interval_95",
        ):
            candidate = ns["_report_direct_get"](value, path)
            if candidate is not ns["MISSING"] and isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
                low = ns["_report_fraction"](candidate[0])
                high = ns["_report_fraction"](candidate[1])
                if low is not None and high is not None:
                    return min(low, high), max(low, high)
        return original_report_ci(value)

    def report_count(mapping: Any, names: Sequence[str]) -> Optional[int]:
        value = original_report_count(mapping, names)
        if value is not None:
            return value
        if isinstance(mapping, Mapping):
            for path in (
                "exact_pair_count",
                "exact_pairs",
                "paired.matched_records",
                "matching.exact_matched_records",
                "pairing.pair_count",
            ):
                candidate = ns["_report_direct_get"](mapping, path)
                if candidate is not ns["MISSING"] and candidate is not None:
                    try:
                        return int(candidate)
                    except (TypeError, ValueError):
                        pass
        return None

    def find_tables(value: Any, key_terms: Sequence[str]) -> List[Dict[str, Any]]:
        rows = original_find_tables(value, key_terms)
        comparison_search = any(
            token in term.casefold()
            for term in key_terms
            for token in ("comparison", "effect", "label_swap", "paired_result")
        )
        output: List[Dict[str, Any]] = []
        seen: set = set()
        for row in rows:
            if comparison_search:
                left, right = ns["_report_pair_names"](row)
                if left == "A" and right == "B":
                    continue
            signature = json.dumps(ns["_report_json_safe"](row), sort_keys=True, ensure_ascii=False)
            if signature in seen:
                continue
            seen.add(signature)
            output.append(row)
        return output

    def render_inventory_section(bundle: Mapping[str, Any]) -> str:
        inventory = ns["_report_as_table"](bundle.get("inventory", []))
        lines = ["## 1. Inventory, integrity, and provenance", ""]
        if not inventory:
            return "\n".join(lines + ["_No result-file inventory was available._"])
        display = []
        for row in inventory:
            display.append(
                {
                    "File": row.get("filename"),
                    "Family": row.get("family"),
                    "Generation": row.get("generation"),
                    "Records": row.get("unique_stage_pmid_records"),
                    "Complete": row.get("clean_3000_record_set"),
                    "Unknown": row.get("unknown_prediction_count"),
                    "Prediction paths": row.get("prediction_paths"),
                    "Issues": row.get("audit_issue_count"),
                }
            )
        lines.append(ns["format_markdown_table"](display, list(display[0].keys())))
        lines.extend(
            [
                "",
                "> Full nested schema audits remain available in `analysis_data.json`; the Markdown report uses compact schema labels to stay readable.",
            ]
        )
        return "\n".join(lines)

    def render_condition_overview_section(bundle: Mapping[str, Any]) -> str:
        catalog = ns["_report_as_table"](bundle.get("catalog", []))
        metrics = {
            str(row.get("condition_id")): row
            for row in ns["_report_condition_metric_rows"](bundle)
        }
        display = []
        for condition in catalog:
            condition_id = str(condition.get("condition_id"))
            metric = metrics.get(condition_id, {})
            display.append(
                {
                    "Condition": condition.get("display_name") or condition_id,
                    "Judge": condition.get("judge_model"),
                    "Debater": condition.get("debater_model"),
                    "Judge input": condition.get("judge_input_scope"),
                    "Manual": condition.get("manual_in_judge_prompt"),
                    "Assigned tags to judge": condition.get("assigned_tags_in_judge_prompt"),
                    "N": metric.get("unique_stage_pmid_count", condition.get("unique_stage_pmid_count")),
                    "Complete": metric.get("is_complete", condition.get("is_complete")),
                    "Accuracy": metric.get("strict_accuracy"),
                    "Balanced": metric.get("balanced_accuracy"),
                    "Unknown": metric.get("unknown_prediction_count"),
                    "Fallback": metric.get("fallback_rate_among_known"),
                }
            )
        lines = ["## 2. Condition overview", ""]
        lines.append(
            ns["format_markdown_table"](display, list(display[0].keys()))
            if display
            else "_No normalized conditions were available._"
        )
        lines.extend(
            [
                "",
                "> Strict accuracy counts unresolved predictions as failures. Partial runs are retained for diagnostics but excluded from the primary ranking.",
            ]
        )
        return "\n".join(lines)

    def render_markdown_report(bundle: Mapping[str, Any]) -> str:
        base = original_render_report(bundle)
        latest = (bundle.get("global_metrics", {}) or {}).get("latest_results", {})
        if not latest:
            return base
        enhanced = _latest_markdown(ns, latest)
        marker = "## 1. Inventory, integrity, and provenance"
        if marker in base:
            return base.replace(marker, enhanced + "\n\n" + marker, 1)
        return base + "\n\n" + enhanced + "\n"

    def write_all_analysis_outputs(*args: Any, **kwargs: Any) -> None:
        original_write_outputs(*args, **kwargs)
        bundle = args[0] if args else kwargs["bundle"]
        output_paths = args[3] if len(args) > 3 else kwargs["output_paths"]
        output_root = ns["_report_output_root"](output_paths)
        filenames = {
            "run_quality": "run_quality.csv",
            "fallback_diagnostics": "fallback_diagnostics.csv",
            "judge_size_by_protocol": "judge_size_by_protocol.csv",
            "judge_size_comparisons": "judge_size_comparisons.csv",
            "judge_size_difference_in_differences": "judge_size_difference_in_differences.csv",
            "titleonly_common_subset": "titleonly_common_subset.csv",
            "titleonly_comparisons": "titleonly_comparisons.csv",
            "label_swap_stability": "label_swap_stability.csv",
        }
        generated = []
        for table_name, filename in filenames.items():
            path = output_root / filename
            ns["write_csv_table"](path, ns["_report_as_table"](bundle.get("tables", {}).get(table_name, [])))
            generated.append(str(path))
        if isinstance(bundle, dict):
            bundle["generated_files"] = ns["_report_dedupe"](
                list(bundle.get("generated_files", [])) + generated
            )
            json_path = ns["_report_output_path"](
                output_paths,
                ("json", "analysis_data", "data_json"),
                "analysis_data.json",
            )
            ns["write_json_artifact"](json_path, bundle)

    ns["build_run_context"] = build_run_context
    ns["infer_file_family"] = infer_file_family
    ns["infer_file_generation"] = infer_file_generation
    ns["infer_file_provenance"] = infer_file_provenance
    ns["reconcile_result_and_script_provenance"] = reconcile_result_and_script_provenance
    ns["choose_canonical_analysis_files"] = choose_canonical_analysis_files
    ns["_condition_id_for"] = condition_id_for
    ns["_condition_display_name"] = condition_display_name
    ns["build_normalized_row"] = build_normalized_row
    ns["normalize_all_files"] = normalize_all_files
    ns["build_condition_catalog"] = build_condition_catalog
    ns["compute_condition_metrics"] = compute_condition_metrics
    ns["build_cross_experiment_synthesis"] = build_cross_experiment_synthesis
    ns["assemble_analysis_bundle"] = assemble_analysis_bundle
    ns["_report_difference"] = report_difference
    ns["_report_ci"] = report_ci
    ns["_report_count"] = report_count
    ns["_report_find_tables"] = find_tables
    ns["render_inventory_section"] = render_inventory_section
    ns["render_condition_overview_section"] = render_condition_overview_section
    ns["render_markdown_report"] = render_markdown_report
    ns["write_all_analysis_outputs"] = write_all_analysis_outputs
