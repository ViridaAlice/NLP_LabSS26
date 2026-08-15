#!/usr/bin/env python3

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

import torch
from pydantic import ValidationError
from transformers import AutoModelForCausalLM, AutoTokenizer

HF_TOKEN = os.environ.get("HF_TOKEN")
DATASET_PATH = "pubmed_xmlc_dataset.json"
RESULTS_DIR = "results"

STAGES = [
    ("Round 1: True Tag", "Yes"),
    ("Round 2: Unrelated Tag", "No"),
    ("Round 3: Similar Tag", "No"),
]

# These are the two existing full-result files whose saved 2B debater text is
# reused by the asymmetric statement and interactive judge-only runs.
SOURCE_BASENAMES = {
    "statement": "pydantic_statement_results_full.json",
    "interactive": "interactive_results_full_rejudge2B.json",
}


def parse_args(description, allow_source=False):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--chunk_id", type=int, default=0)
    parser.add_argument("--total_chunks", type=int, default=1)
    if allow_source:
        parser.add_argument(
            "--source_file",
            default=None,
            help=(
                "Exact earlier full-result debate JSON to reuse. If omitted, the "
                "script finds the expected full-result file in results/."
            ),
        )
    return parser.parse_args()


def stringify(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(
            part for part in (stringify(item) for item in value) if part
        ).strip()
    if isinstance(value, dict):
        for key in ("#text", "text", "value", "content"):
            if key in value:
                text = stringify(value[key])
                if text:
                    return text
        return " ".join(
            part for part in (stringify(item) for item in value.values()) if part
        ).strip()
    return str(value).strip()


def article_title(article):
    for key in ("title", "article_title", "ArticleTitle", "paper_title"):
        if key in article:
            title = stringify(article.get(key))
            if title:
                return title
    return ""


def load_dataset(path=DATASET_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("The dataset JSON must contain a top-level list of articles.")
    return payload


def build_title_index(dataset):
    titles = {}
    for article_index, article in enumerate(dataset):
        if not isinstance(article, dict):
            raise ValueError("Article %d is not a JSON object" % article_index)
        pmid = stringify(article.get("pmid"))
        title = article_title(article)
        if not pmid:
            raise ValueError("Article %d has no PMID" % article_index)
        if not title:
            raise ValueError("PMID %s has no usable title" % pmid)
        if pmid in titles and titles[pmid] != title:
            raise ValueError("Duplicate PMID with conflicting titles: %s" % pmid)
        titles[pmid] = title
    return titles


def validate_chunk(chunk_id, total_chunks):
    if total_chunks < 1:
        raise ValueError("--total_chunks must be at least 1")
    if chunk_id < 0 or chunk_id >= total_chunks:
        raise ValueError("--chunk_id must satisfy 0 <= chunk_id < total_chunks")


def chunk_bounds(length, chunk_id, total_chunks):
    validate_chunk(chunk_id, total_chunks)
    chunk_size = (length + total_chunks - 1) // total_chunks
    start_idx = chunk_id * chunk_size
    end_idx = min(start_idx + chunk_size, length)
    return start_idx, end_idx


def select_chunk(dataset, chunk_id, total_chunks, test_mode=False):
    start_idx, end_idx = chunk_bounds(len(dataset), chunk_id, total_chunks)
    selected = dataset[start_idx:end_idx]

    if test_mode:
        selected = selected[:5]

    print(
        "[CHUNK] %d/%d | global article rows %d:%d | selected articles: %d"
        % (chunk_id + 1, total_chunks, start_idx, end_idx, len(selected)),
        flush=True,
    )
    return selected, start_idx, end_idx


def stable_index(length, *parts):
    if length < 1:
        raise ValueError("Cannot select from an empty sequence")
    joined = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % length


def build_cases(dataset):
    """Build title-only baseline cases. Debate rejudging does not use this function."""
    cases = []
    seen_pmids = set()

    for article_index, article in enumerate(dataset):
        if not isinstance(article, dict):
            raise ValueError("Article %d is not a JSON object" % article_index)

        pmid = stringify(article.get("pmid"))
        if not pmid:
            raise ValueError("Article %d has no PMID" % article_index)
        if pmid in seen_pmids:
            raise ValueError("Duplicate PMID in the selected chunk: %s" % pmid)
        seen_pmids.add(pmid)

        title = article_title(article)
        if not title:
            raise ValueError("PMID %s has no usable title" % pmid)

        correct_tags_raw = article.get("mesh_tags", [])
        if not isinstance(correct_tags_raw, list) or not correct_tags_raw:
            raise ValueError("PMID %s has no non-empty mesh_tags list" % pmid)
        correct_tags = [stringify(tag) for tag in correct_tags_raw if stringify(tag)]
        if not correct_tags:
            raise ValueError("PMID %s has no usable MeSH tags" % pmid)

        for stage_name, ground_truth in STAGES:
            if stage_name == "Round 1: True Tag":
                candidate_tag = correct_tags[
                    stable_index(len(correct_tags), "candidate", stage_name, pmid)
                ]
            elif stage_name == "Round 2: Unrelated Tag":
                candidate_tag = stringify(
                    article.get(
                        "unrelated_negative_test_tag",
                        article.get("negative_test_tag", ""),
                    )
                )
            else:
                candidate_tag = stringify(article.get("similar_negative_test_tag", ""))

            if not candidate_tag or candidate_tag.lower() == "unknown":
                raise ValueError(
                    "PMID %s is missing a candidate tag for %s" % (pmid, stage_name)
                )

            cases.append(
                {
                    "pmid": pmid,
                    "stage": stage_name,
                    "ground_truth": ground_truth,
                    "title": title,
                    "candidate_tag": candidate_tag,
                }
            )

    return cases


def extract_results(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "records", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def first_value(record, names):
    if not isinstance(record, dict):
        return None
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = stringify(value).lower()
    if text in ("true", "1", "yes", "pro", "pro_first"):
        return True
    if text in ("false", "0", "no", "con", "con_first"):
        return False
    return None


def normalize_yes_no(value, stage=""):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = stringify(value).lower()
    if text in ("yes", "true", "1", "positive", "belongs"):
        return "Yes"
    if text in ("no", "false", "0", "negative", "does not belong"):
        return "No"

    stage_text = stringify(stage).lower()
    if "true tag" in stage_text or "round 1" in stage_text:
        return "Yes"
    if (
        "unrelated" in stage_text
        or "similar tag" in stage_text
        or "round 2" in stage_text
        or "round 3" in stage_text
    ):
        return "No"
    return ""


def locate_source_file(kind, explicit_path=None):
    if explicit_path:
        path = os.path.abspath(explicit_path)
        if not os.path.isfile(path):
            raise FileNotFoundError("Source debate file does not exist: %s" % path)
        return path

    if kind not in SOURCE_BASENAMES:
        raise ValueError("Unknown source debate kind: %s" % kind)

    basename = SOURCE_BASENAMES[kind]
    candidates = set()
    for path in (basename, os.path.join(RESULTS_DIR, basename)):
        if os.path.isfile(path):
            candidates.add(os.path.abspath(path))

    recursive_pattern = os.path.join(RESULTS_DIR, "**", basename)
    for path in glob.glob(recursive_pattern, recursive=True):
        if os.path.isfile(path):
            candidates.add(os.path.abspath(path))

    candidates = sorted(candidates)
    if not candidates:
        raise FileNotFoundError(
            "Could not find the earlier %s debate file %s. Expected it in %s/ "
            "or pass --source_file PATH."
            % (kind, basename, RESULTS_DIR)
        )
    if len(candidates) > 1:
        raise RuntimeError(
            "Multiple source files match %s; use --source_file to choose exactly one:\n  %s"
            % (basename, "\n  ".join(candidates))
        )
    return candidates[0]


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_identity(record):
    pmid = stringify(first_value(record, ("pmid", "PMID", "article_id")))
    stage = stringify(
        first_value(record, ("stage", "round", "round_name", "evaluation_stage"))
    )
    candidate_tag = stringify(
        first_value(
            record,
            ("candidate_tag", "candidate_mesh_tag", "mesh_tag", "tag"),
        )
    )
    ground_truth = normalize_yes_no(
        first_value(
            record,
            ("ground_truth", "target", "expected_answer", "correct_answer", "label"),
        ),
        stage,
    )
    return pmid, stage, candidate_tag, ground_truth


def _source_pro_first(record):
    value = first_value(record, ("pro_first", "pro_is_a", "pro_goes_first"))
    parsed = parse_bool(value)
    if parsed is not None:
        return parsed

    a_side = stringify(first_value(record, ("a_side", "debater_a_side"))).upper()
    if a_side == "PRO":
        return True
    if a_side == "CON":
        return False
    return None


def argument_is_valid(argument):
    text = stringify(argument)
    return bool(text and text.lower() not in ("unknown", "none", "null"))


def _test_subset(cases, number_of_pmids=5):
    selected_pmids = []
    selected_set = set()
    for case in cases:
        pmid = case["pmid"]
        if pmid not in selected_set:
            if len(selected_pmids) >= number_of_pmids:
                continue
            selected_pmids.append(pmid)
            selected_set.add(pmid)
    return [case for case in cases if case["pmid"] in selected_set]


def load_source_debate_cases(
    kind,
    title_index,
    chunk_id,
    total_chunks,
    explicit_path=None,
    test_mode=False,
):
    """
    Load saved 2B debate text from one full-result JSON and select this task's
    disjoint chunk. This function never loads or invokes a debater model.
    """
    validate_chunk(chunk_id, total_chunks)
    source_path = locate_source_file(kind, explicit_path)
    with open(source_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = extract_results(payload)
    if records is None:
        raise RuntimeError(
            "Source file has no results/records/data/items list: %s" % source_path
        )

    all_cases = []
    seen = {}
    skipped = []

    for source_index, record in enumerate(records):
        if not isinstance(record, dict):
            skipped.append((source_index, "record is not a JSON object"))
            continue

        pmid, stage, candidate_tag, ground_truth = _source_identity(record)
        missing = []
        if not pmid:
            missing.append("pmid")
        if not stage:
            missing.append("stage")
        if not candidate_tag:
            missing.append("candidate_tag")
        if ground_truth not in ("Yes", "No"):
            missing.append("ground_truth")
        if missing:
            skipped.append((source_index, "missing/invalid " + ", ".join(missing)))
            continue
        if pmid not in title_index:
            skipped.append((source_index, "PMID %s not found in dataset" % pmid))
            continue

        pro_first = _source_pro_first(record)
        if pro_first is None:
            skipped.append((source_index, "missing/invalid pro_first"))
            continue

        case = {
            "pmid": pmid,
            "stage": stage,
            "candidate_tag": candidate_tag,
            "ground_truth": ground_truth,
            "title": title_index[pmid],
            "pro_first": pro_first,
            "source_record_index": source_index,
        }

        if kind == "statement":
            pro_argument = stringify(
                first_value(
                    record,
                    ("pro_argument", "pro_statement", "argument_pro", "pro_output"),
                )
            )
            con_argument = stringify(
                first_value(
                    record,
                    ("con_argument", "con_statement", "argument_con", "con_output"),
                )
            )
            if not argument_is_valid(pro_argument) or not argument_is_valid(con_argument):
                skipped.append(
                    (source_index, "missing/invalid saved PRO or CON argument")
                )
                continue
            case["pro_argument"] = pro_argument
            case["con_argument"] = con_argument
        elif kind == "interactive":
            a_turn1 = stringify(
                first_value(record, ("a_turn1", "a_opening", "debater_a_turn1"))
            )
            b_turn1 = stringify(
                first_value(record, ("b_turn1", "b_response", "debater_b_turn1"))
            )
            a_turn2 = stringify(
                first_value(record, ("a_turn2", "a_rebuttal", "debater_a_turn2"))
            )
            if not all(
                argument_is_valid(value) for value in (a_turn1, b_turn1, a_turn2)
            ):
                skipped.append((source_index, "missing/invalid saved ABA turn"))
                continue
            case["a_turn1"] = a_turn1
            case["b_turn1"] = b_turn1
            case["a_turn2"] = a_turn2
        else:
            raise ValueError("Unknown source debate kind: %s" % kind)

        key = case_key(case)
        previous = seen.get(key)
        if previous is not None:
            if (
                previous["candidate_tag"] != candidate_tag
                or previous["ground_truth"] != ground_truth
            ):
                raise RuntimeError(
                    "Conflicting duplicate source records for stage=%r PMID=%r"
                    % (stage, pmid)
                )
            skipped.append((source_index, "duplicate of an earlier source record"))
            continue

        seen[key] = case
        all_cases.append(case)

    if not all_cases:
        raise RuntimeError("No usable saved debates found in %s" % source_path)

    # Both source files are full 3,000-record outputs. Partition the reusable
    # cases here so the four Slurm tasks do not each judge all 3,000 records.
    start_idx, end_idx = chunk_bounds(len(all_cases), chunk_id, total_chunks)
    cases = all_cases[start_idx:end_idx]
    if test_mode:
        cases = _test_subset(cases, number_of_pmids=5)

    print("[SOURCE] Reusing saved %s debates: %s" % (kind, source_path), flush=True)
    print(
        "[SOURCE] %d raw records | %d usable total | %d skipped"
        % (len(records), len(all_cases), len(skipped)),
        flush=True,
    )
    print(
        "[SOURCE CHUNK] %d/%d | usable rows %d:%d | selected debates: %d"
        % (chunk_id + 1, total_chunks, start_idx, end_idx, len(cases)),
        flush=True,
    )
    for source_index, reason in skipped[:10]:
        print("[SOURCE WARNING] record %d: %s" % (source_index, reason), flush=True)
    if len(skipped) > 10:
        print("[SOURCE WARNING] ... and %d more" % (len(skipped) - 10), flush=True)
    if not cases:
        raise RuntimeError(
            "No usable saved debates selected for chunk %d/%d from %s"
            % (chunk_id, total_chunks, source_path)
        )

    return cases, source_path, len(records), len(skipped)


def case_key(case):
    return (str(case["stage"]), str(case["pmid"]))


def record_key(record):
    if not isinstance(record, dict):
        return None
    stage = stringify(record.get("stage"))
    pmid = stringify(record.get("pmid"))
    if not stage or not pmid:
        return None
    return (stage, pmid)


def normalized_prediction(record):
    if not isinstance(record, dict):
        return ""
    value = record.get("model_prediction", record.get("prediction", ""))
    return stringify(value).lower()


def record_is_complete(record):
    if not isinstance(record, dict):
        return False
    if record.get("generation_complete") is False:
        return False
    return normalized_prediction(record) in ("yes", "no")


def load_checkpoint(path):
    records_by_key = {}

    if not os.path.exists(path):
        return records_by_key, set()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise RuntimeError("Cannot safely read checkpoint %s: %s" % (path, exc)) from exc

    records = extract_results(payload)
    if records is None:
        raise RuntimeError("Checkpoint %s does not contain a results list" % path)

    for record in records:
        key = record_key(record)
        if key is None:
            continue
        previous = records_by_key.get(key)
        if previous is None or record_is_complete(record) or not record_is_complete(previous):
            records_by_key[key] = record

    completed = {
        key for key, record in records_by_key.items() if record_is_complete(record)
    }
    print(
        "[RESUME] %s | %d stored records | %d complete Yes/No records"
        % (path, len(records_by_key), len(completed)),
        flush=True,
    )
    return records_by_key, completed


def save_json_atomically(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=directory, delete=False, encoding="utf-8"
        ) as temp_handle:
            json.dump(payload, temp_handle, indent=2, ensure_ascii=False)
            temp_handle.flush()
            os.fsync(temp_handle.fileno())
            temp_name = temp_handle.name
        os.replace(temp_name, path)
    except Exception:
        if temp_name and os.path.exists(temp_name):
            os.remove(temp_name)
        raise


def save_checkpoint(path, metadata, records_by_key, expected_records):
    records = list(records_by_key.values())
    complete_records = [record for record in records if record_is_complete(record)]
    correct = sum(1 for record in complete_records if bool(record.get("is_correct")))
    accuracy = (100.0 * correct / len(complete_records)) if complete_records else 0.0

    current_metadata = dict(metadata)
    current_metadata.update(
        {
            "expected_records_in_chunk": expected_records,
            "generated_yes_no_records": len(complete_records),
            "chunk_complete": len(complete_records) == expected_records,
            "overall_accuracy": accuracy,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_json_atomically(path, {"metadata": current_metadata, "results": records})


def output_path(experiment_id, chunk_id, test_mode=False):
    prefix = "test_" if test_mode else ""
    return os.path.join(
        RESULTS_DIR, "%s%s_chunk%d.json" % (prefix, experiment_id, chunk_id)
    )


def base_metadata(
    experiment_id,
    condition,
    args,
    judge_model,
    debater_model=None,
):
    return {
        "experiment_id": experiment_id,
        "design": "asymmetric_title_only_judge",
        "condition": condition,
        "judge_model": judge_model,
        "debater_model": debater_model,
        "judge_receives_abstract": False,
        "judge_receives_assigned_tags": False,
        "judge_receives_manual": False,
        "debater_outputs_reused": debater_model is not None,
        "new_debater_generation": False,
        "chunk_id": args.chunk_id,
        "total_chunks": args.total_chunks,
        "test_mode": bool(args.test_mode),
    }


def ensure_cuda():
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: PyTorch cannot find a CUDA GPU")


def load_model_and_tokenizer(model_id):
    auth_kwargs = {"token": HF_TOKEN} if HF_TOKEN else {}
    tokenizer = AutoTokenizer.from_pretrained(model_id, **auth_kwargs)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float16,
        device_map="cuda",
        **auth_kwargs,
    )
    model.eval()
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    return model, tokenizer


def extract_schema(response, schema_class):
    cleaned = re.sub(r"```json\s*", "", response, flags=re.IGNORECASE)
    cleaned = re.sub(r"```\s*", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return schema_class.model_validate_json(cleaned[start : end + 1])
    except (ValidationError, ValueError):
        return None


def generate_structured(
    messages,
    model,
    tokenizer,
    schema_class,
    text_field,
    max_new_tokens,
    temperature=0.2,
    attempts=3,
):
    last_response = ""

    for attempt in range(attempts):
        current_temperature = temperature + (0.2 * attempt)
        chat_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        model_inputs = tokenizer([chat_text], return_tensors="pt").to(model.device)

        with torch.inference_mode():
            output_ids = model.generate(
                **model_inputs,
                max_new_tokens=max_new_tokens,
                temperature=current_temperature,
                do_sample=True,
                pad_token_id=tokenizer.pad_token_id,
            )

        generated = output_ids[0][model_inputs.input_ids.shape[1] :]
        last_response = tokenizer.decode(generated, skip_special_tokens=True).strip()
        parsed = extract_schema(last_response, schema_class)

        if parsed is not None:
            value = stringify(getattr(parsed, text_field, ""))
            normalized = value.capitalize()
            if normalized in ("Yes", "No"):
                return normalized, last_response

    fallback = re.findall(
        r'"%s"\s*:\s*"(.*?)"' % re.escape(text_field),
        last_response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fallback:
        normalized = fallback[-1].strip().capitalize()
        if normalized in ("Yes", "No"):
            return normalized, last_response

    return "Unknown", last_response


def all_cases_complete(cases, completed_keys):
    return all(case_key(case) in completed_keys for case in cases)


def print_case_result(index, total, case, prediction, complete):
    correct = complete and prediction == case["ground_truth"]
    marker = "OK" if correct else ("WRONG" if complete else "INCOMPLETE")
    print(
        "[%d/%d] %s | PMID %s | target %s | pred %s -> %s"
        % (
            index,
            total,
            case["stage"],
            case["pmid"],
            case["ground_truth"],
            prediction,
            marker,
        ),
        flush=True,
    )
