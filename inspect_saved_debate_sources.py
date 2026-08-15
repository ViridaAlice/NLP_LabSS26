#!/usr/bin/env python3
"""Validate the two exact full debate sources used by the asymmetric jobs."""

import hashlib
import json
import os

EXPECTED = 3000
SOURCES = {
    "statement": "results/pydantic_statement_results_full.json",
    "interactive": "results/interactive_results_full_rejudge2B.json",
}


def text(value):
    if value is None:
        return ""
    return str(value).strip()


def first(record, names):
    if not isinstance(record, dict):
        return None
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    value = text(value).lower()
    if value in ("true", "1", "yes", "pro", "pro_first"):
        return True
    if value in ("false", "0", "no", "con", "con_first"):
        return False
    return None


def results(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "records", "data", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return None


def identity(record):
    stage = text(first(record, ("stage", "round", "round_name", "evaluation_stage")))
    pmid = text(first(record, ("pmid", "PMID", "article_id")))
    candidate = text(
        first(record, ("candidate_tag", "candidate_mesh_tag", "mesh_tag", "tag"))
    )
    ground = text(
        first(
            record,
            ("ground_truth", "target", "expected_answer", "correct_answer", "label"),
        )
    ).lower()
    if not ground:
        stage_lower = stage.lower()
        if "true tag" in stage_lower or "round 1" in stage_lower:
            ground = "yes"
        elif (
            "unrelated" in stage_lower
            or "similar tag" in stage_lower
            or "round 2" in stage_lower
            or "round 3" in stage_lower
        ):
            ground = "no"
    if ground in ("true", "1", "positive", "belongs"):
        ground = "yes"
    if ground in ("false", "0", "negative", "does not belong"):
        ground = "no"
    if not stage or not pmid or not candidate or ground not in ("yes", "no"):
        return None
    return stage.lower(), pmid, candidate.lower(), ground


def pro_first(record):
    parsed = as_bool(
        first(record, ("pro_first", "a_is_pro", "pro_is_a", "pro_goes_first"))
    )
    if parsed is not None:
        return parsed
    side = text(first(record, ("a_side", "debater_a_side"))).upper()
    if side == "PRO":
        return True
    if side == "CON":
        return False
    return None


def debate_aba(record):
    value = first(record, ("debate_ABA", "debate_aba", "aba_debate"))
    return value if isinstance(value, dict) else {}


def interactive_turns(record):
    debate = debate_aba(record)
    a1 = first(record, ("a_turn1", "a_opening", "debater_a_turn1"))
    if a1 is None:
        a1 = first(debate, ("a_turn1", "a_opening", "debater_a_turn1"))
    b1 = first(record, ("b_turn1", "b_response", "b_rebuttal", "debater_b_turn1"))
    if b1 is None:
        b1 = first(
            debate,
            ("b_turn1", "b_response", "b_rebuttal", "debater_b_turn1"),
        )
    a2 = first(record, ("a_turn2", "a_rebuttal", "a_closing", "debater_a_turn2"))
    if a2 is None:
        a2 = first(
            debate,
            ("a_turn2", "a_rebuttal", "a_closing", "debater_a_turn2"),
        )
    return text(a1), text(b1), text(a2)


def usable(record, kind):
    if identity(record) is None or pro_first(record) is None:
        return False
    if kind == "statement":
        pro = text(first(record, ("pro_argument", "pro_statement", "argument_pro", "pro_output")))
        con = text(first(record, ("con_argument", "con_statement", "argument_con", "con_output")))
        # Literal "Unknown" is still an exact saved output and is deliberately reused.
        return bool(pro and con)
    if kind == "interactive":
        return all(interactive_turns(record))
    return False


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect(kind, path):
    print("\n%s source" % kind.capitalize())
    print("  Exact path: %s" % path)
    if not os.path.isfile(path):
        print("  Status: MISSING")
        return False

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        print("  Status: UNREADABLE: %s" % exc)
        return False

    records = results(payload)
    if records is None:
        print("  Status: NO RESULTS LIST")
        return False

    keys = set()
    invalid = 0
    duplicates = 0
    unknown_statement_texts = 0
    for record in records:
        if kind == "statement" and isinstance(record, dict):
            for value in (
                first(record, ("pro_argument", "pro_statement", "argument_pro", "pro_output")),
                first(record, ("con_argument", "con_statement", "argument_con", "con_output")),
            ):
                if text(value).lower() == "unknown":
                    unknown_statement_texts += 1
        if not usable(record, kind):
            invalid += 1
            continue
        key = identity(record)
        if key in keys:
            duplicates += 1
        else:
            keys.add(key)

    complete = len(keys) == EXPECTED
    print("  SHA-256: %s" % sha256(path))
    print("  Raw records: %d" % len(records))
    print("  Unique usable records: %d / %d" % (len(keys), EXPECTED))
    print("  Invalid/incomplete records: %d" % invalid)
    print("  Duplicate usable records: %d" % duplicates)
    if kind == "statement":
        print("  Literal 'Unknown' saved statements retained: %d" % unknown_statement_texts)
    print("  Status: %s" % ("COMPLETE" if complete else "INCOMPLETE"))
    return complete


def main():
    print("Only these two exact full files are accepted by default.")
    print("No pydantic_*_results_chunkN.json files are searched or used.")
    statuses = [inspect(kind, path) for kind, path in SOURCES.items()]
    return 0 if all(statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
