#!/usr/bin/env python3
"""Locate JSON files that appear to contain reusable statement/ABA debates."""

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


def main() -> int:
    matches = []
    unreadable = []

    for path in sorted(Path(".").rglob("*.json")):
        if skipped(path):
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

        keys = set()
        for record in records[:50]:
            if isinstance(record, dict):
                keys.update(record)
        kinds = classify(keys)
        if not kinds:
            continue

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
        matches.append((path, len(records), ",".join(kinds), relevant))

    print("Reusable-debate candidates (archive/model/venv directories excluded):")
    if not matches:
        print("  NONE FOUND")
    for path, count, kinds, relevant in matches:
        print(f"  {kinds:21s} records={count:5d}  {path}")
        print("    relevant keys: " + ", ".join(relevant))

    print("\nExact filenames currently expected by the asymmetric programs:")
    for chunk in range(4):
        for kind in ("statement", "interactive"):
            name = f"pydantic_{kind}_results_chunk{chunk}.json"
            found = [
                path
                for path in (Path(name), Path("results") / name)
                if path.is_file()
            ]
            state = str(found[0]) if found else "MISSING"
            print(f"  {name}: {state}")

    if unreadable:
        print(f"\nNote: {len(unreadable)} JSON file(s) could not be read.")

    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
