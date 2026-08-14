#!/usr/bin/env python3

import argparse
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


def parse_args(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--chunk_id", type=int, default=0)
    parser.add_argument("--total_chunks", type=int, default=1)
    return parser.parse_args()


def stringify(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(part for part in (stringify(item) for item in value) if part).strip()
    if isinstance(value, dict):
        for key in ("#text", "text", "value", "content"):
            if key in value:
                text = stringify(value[key])
                if text:
                    return text
        return " ".join(part for part in (stringify(item) for item in value.values()) if part).strip()
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


def select_chunk(dataset, chunk_id, total_chunks, test_mode=False):
    if total_chunks < 1:
        raise ValueError("--total_chunks must be at least 1")
    if chunk_id < 0 or chunk_id >= total_chunks:
        raise ValueError("--chunk_id must satisfy 0 <= chunk_id < total_chunks")

    chunk_size = (len(dataset) + total_chunks - 1) // total_chunks
    start_idx = chunk_id * chunk_size
    end_idx = min(start_idx + chunk_size, len(dataset))
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


def stable_bool(*parts):
    return bool(stable_index(2, *parts))


def build_cases(dataset):
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
            raise ValueError(
                "PMID %s has no usable title. Checked title, article_title, "
                "ArticleTitle, and paper_title." % pmid
            )

        correct_tags_raw = article.get("mesh_tags", [])
        if not isinstance(correct_tags_raw, list) or not correct_tags_raw:
            raise ValueError("PMID %s has no non-empty mesh_tags list" % pmid)
        correct_tags = [stringify(tag) for tag in correct_tags_raw if stringify(tag)]
        if not correct_tags:
            raise ValueError("PMID %s has no usable MeSH tags" % pmid)

        abstract = stringify(article.get("abstract", ""))

        for stage_name, ground_truth in STAGES:
            if stage_name == "Round 1: True Tag":
                candidate_tag = correct_tags[
                    stable_index(len(correct_tags), "candidate", stage_name, pmid)
                ]
                assigned_tags = [tag for tag in correct_tags if tag != candidate_tag]
            elif stage_name == "Round 2: Unrelated Tag":
                candidate_tag = stringify(
                    article.get(
                        "unrelated_negative_test_tag",
                        article.get("negative_test_tag", ""),
                    )
                )
                assigned_tags = list(correct_tags)
            else:
                candidate_tag = stringify(article.get("similar_negative_test_tag", ""))
                assigned_tags = list(correct_tags)

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
                    "abstract": abstract,
                    "assigned_tags": assigned_tags,
                    "candidate_tag": candidate_tag,
                }
            )

    return cases


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

    if isinstance(payload, dict):
        records = payload.get("results", [])
    elif isinstance(payload, list):
        records = payload
    else:
        raise RuntimeError("Checkpoint %s has an unsupported JSON structure" % path)

    if not isinstance(records, list):
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
    metadata = {
        "experiment_id": experiment_id,
        "design": "asymmetric_title_only_judge",
        "condition": condition,
        "judge_model": judge_model,
        "debater_model": debater_model,
        "judge_receives_abstract": False,
        "judge_receives_assigned_tags": False,
        "judge_receives_manual": False,
        "debater_receives_title": debater_model is not None,
        "debater_receives_abstract": debater_model is not None,
        "debater_receives_assigned_tags": debater_model is not None,
        "debater_receives_manual": False,
        "chunk_id": args.chunk_id,
        "total_chunks": args.total_chunks,
        "test_mode": bool(args.test_mode),
    }
    return metadata


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
            if text_field == "answer":
                normalized = value.capitalize()
                if normalized in ("Yes", "No"):
                    return normalized, last_response
            elif value:
                return value, last_response

    fallback = re.findall(
        r'"%s"\s*:\s*"(.*?)"' % re.escape(text_field),
        last_response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fallback:
        value = fallback[-1].strip()
        if text_field == "answer":
            normalized = value.capitalize()
            if normalized in ("Yes", "No"):
                return normalized, last_response
        elif value:
            return value, last_response

    return "Unknown", last_response


def argument_is_valid(argument):
    return bool(argument and argument.strip() and argument.strip() != "Unknown")


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
