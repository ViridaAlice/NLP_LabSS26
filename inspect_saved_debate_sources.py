#!/usr/bin/env python3
"""Inspect the exact full-result JSON files reused by asymmetric judging."""

from __future__ import annotations

import json
from pathlib import Path

SKIP_PARTS = {
    ".git",
    "NLPLab_env",
    "asymmetric_recompute_archive",
    "__pycache__",
}

CONTAINERS = ("results", "records", "data", "items")
STATEMENT_PRO = {"pro_argument", "pro_statement", "argument_pro", "pro_output"}
STATEMENT_CON = {"con_argument", "con_statement", "argument_con", "con_output"}
INTERACTIVE_A1 = {"a_turn1", "a_opening", "debater_a_turn1"}
INTERACTIVE_B1 = {"b_turn1", "b_response", "debater_b_turn1"}
INTERACTIVE_A2 = {"a_turn2", "a_rebuttal", "debater_a_turn2"}
IDENTITY = {
    "pmid",
    "PMID",
    "article_id",
    "stage",
    "round",
    "round_name",
    "evaluation_stage",
    "candidate_tag",
    "candidate_mesh_tag",
    "mesh_tag",
    "tag",
    "ground_truth",
    "target",
    "expected_answer",
    "correct_answer",
    "label",
    "pro_first",
    "pro_is_a",
    "pro_goes_first",
    "a_side",
    "debater_a_side",
}

EXPECTED_SOURCES = (
    ("statement", Path("results/pydantic_statement_results_full.json")),
    ("interactive", Path("results/interactive_results_full_rejudge2B.json")),
)


def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in CONTAINERS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def skipped(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return True
    return any(part.startswith("Qwen3.5-") for part in path.parts)


def classify(keys: set[str]) -> list[str]:
    kinds = []
    if keys & STATEMENT_PRO and keys & STATEMENT_CON:
        kinds.append("statement")
    if keys & INTERACTIVE_A1 and keys & INTERACTIVE_B1 and keys & INTERACTIVE_A2:
        kinds.append("interactive")
    return kinds


def record_keys(records):
    keys = set()
    for record in records[:50]:
        if isinstance(record, dict):
            keys.update(record)
    return keys


def main() -> int:
    print("Exact full-result files used by the asymmetric programs:")
    exact_ok = True

    for expected_kind, path in EXPECTED_SOURCES:
        if not path.is_file():
            exact_ok = False
            print(f"  MISSING  {expected_kind:11s}  {path}")
            continue

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            exact_ok = False
            print(f"  UNREADABLE {expected_kind:10s}  {path}: {exc}")
            continue

        records = extract_records(payload)
        if records is None:
            exact_ok = False
            print(f"  INVALID  {expected_kind:11s}  {path}: no results list")
            continue

        keys = record_keys(records)
        kinds = classify(keys)
        status = "OK" if expected_kind in kinds else "FIELDS NOT RECOGNIZED"
        if status != "OK":
            exact_ok = False
        print(
            f"  {status:21s} records={len(records):5d}  "
            f"expected={expected_kind:11s}  {path}"
        )
        relevant = sorted(
            keys
            & (
                STATEMENT_PRO
                | STATEMENT_CON
                | INTERACTIVE_A1
                | INTERACTIVE_B1
                | INTERACTIVE_A2
                | IDENTITY
            )
        )
        print("    relevant keys: " + (", ".join(relevant) or "NONE"))

    print("\nOther reusable-debate candidates (informational only):")
    matches = []
    unreadable = []
    expected_resolved = {path.resolve() for _, path in EXPECTED_SOURCES if path.exists()}

    for path in sorted(Path(".").rglob("*.json")):
        if skipped(path) or path.resolve() in expected_resolved:
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            unreadable.append((path, exc))
            continue

        records = extract_records(payload)
        if not records:
            continue
        keys = record_keys(records)
        kinds = classify(keys)
        if kinds:
            matches.append((path, len(records), ",".join(kinds)))

    if not matches:
        print("  NONE")
    for path, count, kinds in matches:
        print(f"  {kinds:21s} records={count:5d}  {path}")

    if unreadable:
        print(f"\nNote: {len(unreadable)} unrelated JSON file(s) could not be read.")

    return 0 if exact_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
