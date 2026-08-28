#!/usr/bin/env python3

import glob
import hashlib
import json
import os
import re
import sys

EXPECTED = 3000
RESULTS_DIR = "results"
SOURCE_LAYOUT_VERSION = "full_source_contiguous_raw_chunks_v1"

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
        "Asymmetric statement: full saved 2B statements -> title-only 0.8B judge",
        "asymmetric_titleonly_statement",
    ),
    (
        "Asymmetric interactive ABA: full saved 2B ABA -> title-only 0.8B judge",
        "asymmetric_titleonly_interactive_aba",
    ),
]

SOURCE_RUNS = [
    (
        "Saved statement source required by asymmetric statement",
        "statement",
        os.path.join(RESULTS_DIR, "pydantic_statement_results_full.json"),
    ),
    (
        "Saved interactive source required by asymmetric ABA",
        "interactive",
        os.path.join(RESULTS_DIR, "interactive_results_full_rejudge2B.json"),
    ),
]

EXPERIMENT_SOURCE = {
    "asymmetric_titleonly_statement": (
        "statement",
        "pydantic_statement_results_full.json",
    ),
    "asymmetric_titleonly_interactive_aba": (
        "interactive",
        "interactive_results_full_rejudge2B.json",
    ),
}


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
    value = normalize(value)
    if value in ("true", "1", "yes", "pro", "pro_first"):
        return True
    if value in ("false", "0", "no", "con", "con_first"):
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


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    return stage, pmid, candidate, ground_truth


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


def asymmetric_record_is_valid(record, experiment_id):
    if not record_is_generated(record):
        return False
    if truth_value(record.get("judge_received_abstract")) is not False:
        return False
    if experiment_id == "asymmetric_titleonly_baseline":
        return True
    return (
        truth_value(record.get("debater_outputs_reused")) is True
        and truth_value(record.get("new_debater_generation")) is False
    )


def summarize_files(files, expected=EXPECTED, record_validator=record_is_generated):
    keys = set()
    raw_count = 0
    invalid_count = 0
    duplicate_count = 0

    for _, records in files:
        for record in records:
            raw_count += 1
            if not record_validator(record):
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
    return {
        "complete": unique_count == expected,
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
    return stage, pmid, candidate, ground


def source_pro_first(record):
    value = first_value(
        record,
        ("pro_first", "a_is_pro", "pro_is_a", "pro_goes_first"),
    )
    parsed = truth_value(value)
    if parsed is not None:
        return parsed
    a_side = normalize(first_value(record, ("a_side", "debater_a_side")))
    if a_side == "pro":
        return True
    if a_side == "con":
        return False
    return None


def saved_text_present(value):
    # Literal "Unknown" is a saved output and must be reused, not regenerated.
    return bool(text_value(value))


def interactive_debate(record):
    value = first_value(record, ("debate_ABA", "debate_aba", "aba_debate"))
    return value if isinstance(value, dict) else {}


def interactive_turns(record):
    debate = interactive_debate(record)

    a_turn1 = first_value(record, ("a_turn1", "a_opening", "debater_a_turn1"))
    if a_turn1 is None:
        a_turn1 = first_value(debate, ("a_turn1", "a_opening", "debater_a_turn1"))

    b_turn1 = first_value(record, ("b_turn1", "b_response", "b_rebuttal", "debater_b_turn1"))
    if b_turn1 is None:
        b_turn1 = first_value(
            debate,
            ("b_turn1", "b_response", "b_rebuttal", "debater_b_turn1"),
        )

    a_turn2 = first_value(record, ("a_turn2", "a_rebuttal", "a_closing", "debater_a_turn2"))
    if a_turn2 is None:
        a_turn2 = first_value(
            debate,
            ("a_turn2", "a_rebuttal", "a_closing", "debater_a_turn2"),
        )

    return text_value(a_turn1), text_value(b_turn1), text_value(a_turn2)


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
        return saved_text_present(pro_argument) and saved_text_present(con_argument)

    if kind == "interactive":
        return all(saved_text_present(value) for value in interactive_turns(record))

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


def print_run(label, files, summary, incompatible=None):
    incompatible = incompatible or []
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
    print("  Compatible files:  %d" % len(files))
    print("  Raw records:       %d" % summary["raw"])
    print("  Invalid records:   %d" % summary["invalid"])
    print("  Duplicate records: %d" % summary["duplicates"])

    if not files:
        print("  Warning: no compatible result files found")
    else:
        for path, records in files:
            print("    - %s (%d records)" % (path, len(records)))

    if incompatible:
        print("  Incompatible old asymmetric files (not counted):")
        for path, reason in incompatible:
            print("    - %s: %s" % (path, reason))


def print_source_run(label, files, summary, expected_path):
    if summary["complete"]:
        status = "AVAILABLE AND COMPLETE"
    elif summary["unique"] < EXPECTED:
        status = "SOURCE INCOMPLETE (%d usable debates missing)" % summary["missing"]
    else:
        status = "CHECK SOURCE (%d unexpected extra debates)" % summary["extra"]

    print("")
    print(label)
    print("  Exact source:      %s" % expected_path)
    print("  Status:            %s" % status)
    print("  Unique usable:     %d / %d" % (summary["unique"], EXPECTED))
    print("  Raw source records:%d" % summary["raw"])
    print("  Invalid debates:   %d" % summary["invalid"])
    print("  Duplicate debates: %d" % summary["duplicates"])
    if not files:
        print("  Warning: exact saved debate file not found/readable")


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


def asymmetric_compatibility(experiment_id, path, payload, source_info):
    if experiment_id == "asymmetric_titleonly_baseline":
        return None

    metadata = metadata_dict(payload)
    source_kind, expected_basename = EXPERIMENT_SOURCE[experiment_id]
    reasons = []

    if metadata.get("source_layout_version") != SOURCE_LAYOUT_VERSION:
        reasons.append("old or missing full-source layout version")

    source_file = metadata.get(
        "debate_source_basename", metadata.get("debate_source_file", "")
    )
    if os.path.basename(str(source_file)) != expected_basename:
        reasons.append("wrong debate source filename")

    if truth_value(metadata.get("debater_outputs_reused")) is not True:
        reasons.append("debater_outputs_reused is not true")
    if truth_value(metadata.get("new_debater_generation")) is not False:
        reasons.append("new_debater_generation is not false")
    if truth_value(metadata.get("judge_receives_abstract")) is not False:
        reasons.append("judge_receives_abstract is not false")

    loaded_models = metadata.get("loaded_models")
    if not isinstance(loaded_models, list) or len(loaded_models) != 1:
        reasons.append("loaded_models does not contain exactly one judge")
    else:
        loaded = normalize(loaded_models[0])
        if "qwen3.5-0.8b" not in loaded:
            reasons.append("loaded model is not the 0.8B judge")

    actual_sha = source_info.get(source_kind, {}).get("sha256")
    if actual_sha and metadata.get("debate_source_sha256") != actual_sha:
        reasons.append("source SHA-256 does not match the exact current full source")

    chunk_id = metadata.get("chunk_id")
    total_chunks = metadata.get("total_chunks")
    if not isinstance(chunk_id, int) or chunk_id not in range(4):
        reasons.append("invalid chunk_id")
    if total_chunks != 4:
        reasons.append("total_chunks is not 4")

    source_count = source_info.get(source_kind, {}).get("raw_count")
    if isinstance(chunk_id, int) and chunk_id in range(4) and source_count is not None:
        chunk_size = (source_count + 3) // 4
        expected_start = chunk_id * chunk_size
        expected_end = min(expected_start + chunk_size, source_count)
        if metadata.get("source_chunk_start") != expected_start:
            reasons.append("wrong source_chunk_start")
        if metadata.get("source_chunk_end") != expected_end:
            reasons.append("wrong source_chunk_end")

    return "; ".join(reasons) if reasons else None


def load_exact_sources(unreadable):
    grouped = {}
    info = {}

    for _, kind, path in SOURCE_RUNS:
        grouped[kind] = []
        info[kind] = {"path": path, "sha256": None, "raw_count": None}
        if not os.path.isfile(path):
            continue
        payload, error = load_json(path)
        if error is not None:
            unreadable.append((path, error))
            continue
        records = extract_results(payload)
        if records is None:
            unreadable.append((path, "no results/records/data/items list"))
            continue
        grouped[kind].append((path, records))
        info[kind]["sha256"] = file_sha256(path)
        info[kind]["raw_count"] = len(records)

    return grouped, info


def main():
    larger_grouped = {}
    asymmetric_grouped = {}
    asymmetric_incompatible = {}
    unreadable = []

    source_grouped, source_info = load_exact_sources(unreadable)
    exact_source_paths = {
        os.path.abspath(path) for _, _, path in SOURCE_RUNS
    }

    for path in discover_results():
        if os.path.abspath(path) in exact_source_paths:
            continue

        filename = normalize(os.path.basename(path))
        if filename.startswith("test_"):
            continue
        if "baseline" not in filename and "asymmetric_titleonly" not in filename:
            continue

        payload, error = load_json(path)
        if error is not None:
            unreadable.append((path, error))
            continue

        records = extract_results(payload)
        if records is None:
            continue

        asymmetric_id = detect_asymmetric_experiment(path, payload)
        if asymmetric_id is not None:
            reason = asymmetric_compatibility(
                asymmetric_id, path, payload, source_info
            )
            if reason:
                asymmetric_incompatible.setdefault(asymmetric_id, []).append(
                    (path, reason)
                )
            else:
                asymmetric_grouped.setdefault(asymmetric_id, []).append(
                    (path, records)
                )
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
    print("LARGER-JUDGE BASELINE COMPLETION CHECK (READ-ONLY)")
    print("The asymmetric submission script never writes any 2B or 4B result.")
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
    print("EXACT FULL 2B DEBATE SOURCE CHECK")
    print("No pydantic_*_results_chunkN.json files are searched or counted.")
    print("=" * 78)

    source_summaries = {}
    for label, kind, expected_path in SOURCE_RUNS:
        files = source_grouped.get(kind, [])
        summary = summarize_source_files(files, kind)
        source_summaries[kind] = summary
        print_source_run(label, files, summary, expected_path)

    print("")
    print("=" * 78)
    print("ASYMMETRIC TITLE-ONLY JUDGE COMPLETION CHECK")
    print("Statement and ABA load only the 0.8B judge and reuse full saved 2B text.")
    print("=" * 78)

    asymmetric_summaries = {}
    for label, experiment_id in ASYMMETRIC_RUNS:
        files = asymmetric_grouped.get(experiment_id, [])
        validator = lambda record, exp=experiment_id: asymmetric_record_is_valid(
            record, exp
        )
        summary = summarize_files(files, record_validator=validator)
        asymmetric_summaries[experiment_id] = summary
        print_run(
            label,
            files,
            summary,
            asymmetric_incompatible.get(experiment_id, []),
        )

    baseline_complete = asymmetric_summaries[
        "asymmetric_titleonly_baseline"
    ]["complete"]
    statement_complete = asymmetric_summaries[
        "asymmetric_titleonly_statement"
    ]["complete"]
    interactive_complete = asymmetric_summaries[
        "asymmetric_titleonly_interactive_aba"
    ]["complete"]
    asymmetric_complete = (
        baseline_complete and statement_complete and interactive_complete
    )

    print("")
    print("=" * 78)
    if baseline_complete:
        print("Asymmetric baseline is complete: do not rerun it.")
    else:
        print("Asymmetric baseline is incomplete, but submit_asymmetric.sh excludes it.")

    needed = []
    if not statement_complete:
        needed.append(("statement", "0-3"))
    if not interactive_complete:
        needed.append(("interactive", "4-7"))

    if not needed:
        print("Statement and interactive are complete: do not restart submit_asymmetric.sh.")
    else:
        blocked = [
            kind for kind, _ in needed if not source_summaries[kind]["complete"]
        ]
        if blocked:
            print(
                "JUDGE-ONLY RERUN BLOCKED: exact full %s source is incomplete."
                % " and ".join(blocked)
            )
            print("Do not regenerate debaters inside the asymmetric scripts.")
        else:
            print("Statement/interactive need another judge-only resume round.")
            print("First ensure no asym_title job is running or pending:")
            print('  squeue -u "$USER" -n asym_title')
            if len(needed) == 2:
                command = "sbatch --array=0-7%4 submit_asymmetric.sh"
            else:
                command = "sbatch --array=%s%%4 submit_asymmetric.sh" % needed[0][1]
            print("If none is present, submit only the required phase(s):")
            print("  %s" % command)
            print("Array 0-3 = statement; array 4-7 = interactive.")
            print("The baseline and all 4B results are excluded from this script.")

    if unreadable:
        print("")
        print("WARNING: %d relevant JSON file(s) could not be read:" % len(unreadable))
        for path, error in unreadable:
            print("  - %s: %s" % (path, error))

    print("")
    if larger_complete:
        print("All four larger-judge baseline runs are complete.")
    else:
        print(
            "One or more larger-judge baseline runs remain incomplete; this is a "
            "read-only report and submit_asymmetric.sh will not modify them."
        )

    all_complete = larger_complete and asymmetric_complete and not unreadable
    if all_complete:
        print("ALL SEVEN TRACKED RUNS ARE COMPLETE.")
        return 0

    print("ONE OR MORE TRACKED RUNS ARE INCOMPLETE.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
