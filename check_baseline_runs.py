#!/usr/bin/env python3

import glob
import json
import os
import re
import sys

EXPECTED = 3000
RESULTS_DIR = "results"

LARGER_RUNS = [
    ("Qwen3.5-2B without manual", "2B", False),
    ("Qwen3.5-2B with manual", "2B", True),
    ("Qwen3.5-4B without manual", "4B", False),
    ("Qwen3.5-4B with manual", "4B", True),
]

ASYMMETRIC_RUNS = [
    (
        "Asymmetric baseline: title-only 0.8B judge",
        "asymmetric_titleonly_baseline",
    ),
    (
        "Asymmetric statement: saved 2B debates -> title-only 0.8B judge",
        "asymmetric_titleonly_statement",
    ),
    (
        "Asymmetric interactive ABA: saved 2B debates -> title-only 0.8B judge",
        "asymmetric_titleonly_interactive_aba",
    ),
]

# The asymmetric judge-only runs reuse these exact full-result source files.
SOURCE_RUNS = [
    (
        "Saved statement debates: pydantic_statement_results_full.json",
        "statement",
        re.compile(r"^pydantic_statement_results_full\.json$", re.IGNORECASE),
    ),
    (
        "Saved interactive debates: interactive_results_full_rejudge2B.json",
        "interactive",
        re.compile(r"^interactive_results_full_rejudge2B\.json$", re.IGNORECASE),
    ),
]


def normalize(value):
    return str(value or "").strip().lower().replace("\\", "/")


def text_value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def truth_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = normalize(value)
    if text in ("true", "1", "yes", "pro", "pro_first"):
        return True
    if text in ("false", "0", "no", "con", "con_first"):
        return False
    return None


def first_value(record, names):
    if not isinstance(record, dict):
        return None
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except Exception as exc:
        return None, str(exc)


def extract_results(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "records", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def metadata_dict(payload):
    if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
        return payload["metadata"]
    return {}


def combined_text(path, payload, records):
    pieces = [path]
    metadata = metadata_dict(payload)

    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            pieces.append("%s=%s" % (key, value))

    if isinstance(payload, dict):
        for key in (
            "experiment_id",
            "judge_model",
            "judge_model_id",
            "debater_model",
            "model",
            "model_id",
            "use_manual",
        ):
            if key in payload:
                pieces.append("%s=%s" % (key, payload[key]))

    for record in records[:5]:
        if not isinstance(record, dict):
            continue
        for key in (
            "experiment_id",
            "judge_model",
            "judge_model_id",
            "model",
            "model_id",
            "use_manual",
        ):
            if key in record:
                pieces.append("%s=%s" % (key, record[key]))

    return normalize(" ".join(pieces))


def detect_model(text):
    compact = re.sub(r"[^a-z0-9.]+", "", text)

    if (
        "qwen3.54b" in compact
        or "qwen354b" in compact
        or "judge4b" in compact
        or "model4b" in compact
    ):
        return "4B"

    if (
        "qwen3.52b" in compact
        or "qwen352b" in compact
        or "judge2b" in compact
        or "model2b" in compact
    ):
        return "2B"

    return None


def detect_manual(text, records):
    values = set()
    for record in records:
        if isinstance(record, dict) and "use_manual" in record:
            parsed = truth_value(record.get("use_manual"))
            if parsed is not None:
                values.add(parsed)

    if len(values) == 1:
        return list(values)[0]

    compact = re.sub(r"[^a-z0-9]+", "", text)
    if (
        "nomanual" in compact
        or "withoutmanual" in compact
        or "usemanualfalse" in compact
    ):
        return False
    if "withmanual" in compact or "usemanualtrue" in compact:
        return True
    return None


def detect_asymmetric_experiment(path, payload):
    metadata = metadata_dict(payload)
    explicit = normalize(
        metadata.get(
            "experiment_id",
            payload.get("experiment_id", "") if isinstance(payload, dict) else "",
        )
    )
    known = {experiment_id for _, experiment_id in ASYMMETRIC_RUNS}
    if explicit in known:
        return explicit

    filename = normalize(os.path.basename(path))
    for experiment_id in known:
        if experiment_id in filename:
            return experiment_id
    return None


def record_key(record):
    if not isinstance(record, dict):
        return None

    stage = normalize(record.get("stage"))
    pmid = normalize(record.get("pmid"))
    candidate = normalize(record.get("candidate_tag"))
    ground_truth = normalize(record.get("ground_truth"))

    if not stage or not pmid:
        return None
    return (stage, pmid, candidate, ground_truth)


def record_is_generated(record):
    if not isinstance(record, dict):
        return False

    if "generation_complete" in record and truth_value(
        record.get("generation_complete")
    ) is False:
        return False

    prediction = normalize(
        record.get("prediction", record.get("model_prediction", ""))
    )
    return prediction in ("yes", "no")


def summarize_files(files, expected=EXPECTED):
    keys = set()
    raw_count = 0
    invalid_count = 0
    duplicate_count = 0

    for _, records in files:
        for record in records:
            raw_count += 1
            if not record_is_generated(record):
                invalid_count += 1
                continue

            key = record_key(record)
            if key is None:
                invalid_count += 1
                continue

            if key in keys:
                duplicate_count += 1
            else:
                keys.add(key)

    unique_count = len(keys)
    complete = unique_count == expected
    return {
        "complete": complete,
        "unique": unique_count,
        "raw": raw_count,
        "invalid": invalid_count,
        "duplicates": duplicate_count,
        "missing": max(0, expected - unique_count),
        "extra": max(0, unique_count - expected),
    }


def source_identity(record):
    if not isinstance(record, dict):
        return None
    stage = normalize(
        first_value(record, ("stage", "round", "round_name", "evaluation_stage"))
    )
    pmid = normalize(first_value(record, ("pmid", "PMID", "article_id")))
    candidate = normalize(
        first_value(record, ("candidate_tag", "candidate_mesh_tag", "mesh_tag", "tag"))
    )
    ground = normalize(
        first_value(
            record,
            ("ground_truth", "target", "expected_answer", "correct_answer", "label"),
        )
    )
    if not ground:
        if "true tag" in stage or "round 1" in stage:
            ground = "yes"
        elif (
            "unrelated" in stage
            or "similar tag" in stage
            or "round 2" in stage
            or "round 3" in stage
        ):
            ground = "no"
    if ground in ("true", "1", "positive", "belongs"):
        ground = "yes"
    if ground in ("false", "0", "negative", "does not belong"):
        ground = "no"
    if not stage or not pmid or not candidate or ground not in ("yes", "no"):
        return None
    return (stage, pmid, candidate, ground)


def source_pro_first(record):
    value = first_value(record, ("pro_first", "pro_is_a", "pro_goes_first"))
    parsed = truth_value(value)
    if parsed is not None:
        return parsed
    a_side = normalize(first_value(record, ("a_side", "debater_a_side")))
    if a_side == "pro":
        return True
    if a_side == "con":
        return False
    return None


def valid_saved_text(value):
    text = text_value(value).lower()
    return bool(text and text not in ("unknown", "none", "null"))


def source_record_is_usable(record, kind):
    if source_identity(record) is None or source_pro_first(record) is None:
        return False

    if kind == "statement":
        pro_argument = first_value(
            record,
            ("pro_argument", "pro_statement", "argument_pro", "pro_output"),
        )
        con_argument = first_value(
            record,
            ("con_argument", "con_statement", "argument_con", "con_output"),
        )
        return valid_saved_text(pro_argument) and valid_saved_text(con_argument)

    if kind == "interactive":
        a_turn1 = first_value(record, ("a_turn1", "a_opening", "debater_a_turn1"))
        b_turn1 = first_value(record, ("b_turn1", "b_response", "debater_b_turn1"))
        a_turn2 = first_value(record, ("a_turn2", "a_rebuttal", "debater_a_turn2"))
        return all(valid_saved_text(value) for value in (a_turn1, b_turn1, a_turn2))

    return False


def summarize_source_files(files, kind, expected=EXPECTED):
    keys = set()
    raw_count = 0
    invalid_count = 0
    duplicate_count = 0

    for _, records in files:
        for record in records:
            raw_count += 1
            if not source_record_is_usable(record, kind):
                invalid_count += 1
                continue
            key = source_identity(record)
            if key in keys:
                duplicate_count += 1
            else:
                keys.add(key)

    unique_count = len(keys)
    return {
        "complete": unique_count == expected,
        "unique": unique_count,
        "raw": raw_count,
        "invalid": invalid_count,
        "duplicates": duplicate_count,
        "missing": max(0, expected - unique_count),
        "extra": max(0, unique_count - expected),
    }


def print_run(label, files, summary):
    if summary["complete"]:
        status = "COMPLETE"
    elif summary["unique"] < EXPECTED:
        status = "RE-RUN / RESUME (%d missing)" % summary["missing"]
    else:
        status = "CHECK OUTPUT (%d unexpected extra records)" % summary["extra"]

    print("")
    print(label)
    print("  Status:            %s" % status)
    print("  Unique generated:  %d / %d" % (summary["unique"], EXPECTED))
    print("  Matching files:    %d" % len(files))
    print("  Raw records:       %d" % summary["raw"])
    print("  Invalid records:   %d" % summary["invalid"])
    print("  Duplicate records: %d" % summary["duplicates"])

    if not files:
        print("  Warning: no matching result files found")
    else:
        for path, records in files:
            print("    - %s (%d records)" % (path, len(records)))


def print_source_run(label, files, summary):
    if summary["complete"]:
        status = "AVAILABLE AND COMPLETE"
    elif summary["unique"] < EXPECTED:
        status = "SOURCE INCOMPLETE (%d usable debates missing)" % summary["missing"]
    else:
        status = "CHECK SOURCE (%d unexpected extra debates)" % summary["extra"]

    print("")
    print(label)
    print("  Status:             %s" % status)
    print("  Unique usable:      %d / %d" % (summary["unique"], EXPECTED))
    print("  Matching files:     %d" % len(files))
    print("  Raw source records: %d" % summary["raw"])
    print("  Invalid debates:    %d" % summary["invalid"])
    print("  Duplicate debates:  %d" % summary["duplicates"])
    for path, records in files:
        print("    - %s (%d records)" % (path, len(records)))
    if not files:
        print("  Warning: no matching saved debate files found")


def discover_results():
    patterns = [
        os.path.join(RESULTS_DIR, "*.json"),
        os.path.join(RESULTS_DIR, "**", "*.json"),
    ]
    paths = set()
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            if os.path.isfile(path):
                paths.add(path)
    return sorted(paths)


def main():
    larger_grouped = {}
    asymmetric_grouped = {}
    source_grouped = {kind: [] for _, kind, _ in SOURCE_RUNS}
    unreadable = []

    source_patterns = [(kind, pattern) for _, kind, pattern in SOURCE_RUNS]

    for path in discover_results():
        filename_raw = os.path.basename(path)
        filename = normalize(filename_raw)
        if filename.startswith("test_"):
            continue

        source_kind = None
        for kind, pattern in source_patterns:
            if pattern.match(filename_raw):
                source_kind = kind
                break

        potentially_relevant = (
            source_kind is not None
            or "baseline" in filename
            or "asymmetric_titleonly" in filename
        )
        if not potentially_relevant:
            continue

        payload, error = load_json(path)
        if error is not None:
            unreadable.append((path, error))
            continue

        records = extract_results(payload)
        if records is None:
            continue

        if source_kind is not None:
            source_grouped[source_kind].append((path, records))
            continue

        asymmetric_id = detect_asymmetric_experiment(path, payload)
        if asymmetric_id is not None:
            asymmetric_grouped.setdefault(asymmetric_id, []).append((path, records))
            continue

        if "baseline" not in filename:
            continue

        text = combined_text(path, payload, records)
        model = detect_model(text)
        use_manual = detect_manual(text, records)
        if model not in ("2B", "4B") or use_manual is None:
            continue

        larger_grouped.setdefault((model, use_manual), []).append((path, records))

    print("=" * 78)
    print("LARGER-JUDGE BASELINE COMPLETION CHECK")
    print("A run is complete only with 3,000 unique generated Yes/No records.")
    print("=" * 78)

    larger_complete = True
    for label, model, use_manual in LARGER_RUNS:
        files = larger_grouped.get((model, use_manual), [])
        summary = summarize_files(files)
        print_run(label, files, summary)
        if not summary["complete"]:
            larger_complete = False

    print("")
    print("=" * 78)
    print("SAVED 2B DEBATE SOURCE CHECK")
    print("Statement and interactive asymmetric jobs reuse these exact full files.")
    print("=" * 78)

    source_summaries = {}
    for label, kind, _ in SOURCE_RUNS:
        files = source_grouped.get(kind, [])
        summary = summarize_source_files(files, kind)
        source_summaries[kind] = summary
        print_source_run(label, files, summary)

    print("")
    print("=" * 78)
    print("ASYMMETRIC TITLE-ONLY JUDGE COMPLETION CHECK")
    print("Statement and ABA load only the 0.8B judge, not a debater model.")
    print("=" * 78)

    asymmetric_complete = True
    asymmetric_summaries = {}
    for label, experiment_id in ASYMMETRIC_RUNS:
        files = asymmetric_grouped.get(experiment_id, [])
        summary = summarize_files(files)
        asymmetric_summaries[experiment_id] = summary
        print_run(label, files, summary)
        if not summary["complete"]:
            asymmetric_complete = False

    baseline_needed = not asymmetric_summaries[
        "asymmetric_titleonly_baseline"
    ]["complete"]
    statement_needed = not asymmetric_summaries[
        "asymmetric_titleonly_statement"
    ]["complete"]
    interactive_needed = not asymmetric_summaries[
        "asymmetric_titleonly_interactive_aba"
    ]["complete"]
    judge_only_needed = statement_needed or interactive_needed

    print("")
    print("=" * 78)
    if asymmetric_complete:
        print("ASYMMETRIC PIPELINE COMPLETE: do not restart submit_asymmetric.sh.")
    else:
        if baseline_needed:
            print("WARNING: the asymmetric baseline is incomplete.")
            print("submit_asymmetric.sh intentionally does NOT run the baseline.")

        missing_sources = []
        if statement_needed and not source_summaries["statement"]["complete"]:
            missing_sources.append("statement")
        if interactive_needed and not source_summaries["interactive"]["complete"]:
            missing_sources.append("interactive")

        if missing_sources:
            print("ASYMMETRIC JUDGE-ONLY RERUN IS BLOCKED BY INCOMPLETE SAVED DEBATES.")
            print(
                "Required exact source(s): %s"
                % ", ".join(missing_sources)
            )
            print("Do not regenerate debates inside the asymmetric scripts.")
        elif judge_only_needed:
            print("ASYMMETRIC STATEMENT/INTERACTIVE NEED ANOTHER JUDGE-ONLY ROUND.")
            print("The two exact full debate sources are available.")
            print("First ensure no asym_title array is running or pending:")
            print("  squeue -u \"$USER\" -n asym_title")
            print("If that command shows no jobs, restart safely with:")
            print("  sbatch submit_asymmetric.sh")
            print("This script does not run the baseline and does not touch 4B outputs.")
            print("Do not run overlapping copies; they write the same checkpoints.")
        else:
            print("Do not run submit_asymmetric.sh: statement and interactive are complete.")

    if unreadable:
        print("")
        print("WARNING: %d relevant JSON file(s) could not be read:" % len(unreadable))
        for path, error in unreadable:
            print("  - %s: %s" % (path, error))

    print("")
    if larger_complete:
        print("All four larger-judge baseline runs are complete.")
    else:
        print("One or more larger-judge baseline runs still need their own resume job.")
        print("submit_asymmetric.sh does not read, write, or resume those 4B outputs.")

    all_complete = larger_complete and asymmetric_complete and not unreadable
    if all_complete:
        print("ALL SEVEN TRACKED RUNS ARE COMPLETE.")
        return 0

    print("ONE OR MORE TRACKED RUNS ARE INCOMPLETE.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
