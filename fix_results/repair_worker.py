#!/usr/bin/env python3
"""Crash-safe worker for one deterministic repair chunk.

Python 3.6 compatible. Intended to be launched by the supplied SLURM scripts.
"""

import argparse
import fcntl
import glob
import hashlib
import json
import os
import random
import signal
import sys
import tempfile
import time

import torch

HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

import debate_utils as U

STAGES = [
    ("Round 1: True Tag", "Yes"),
    ("Round 2: Unrelated Tag", "No"),
    ("Round 3: Similar Tag", "No"),
]

CONFIG = {
    "interactive_rejudge2b": {
        "source": "interactive_results_full.json",
        "final": "interactive_results_full_rejudge2B.json",
        "judge_model": "./Qwen3.5-2B",
    },
    "statement_rejudge2b": {
        "source": "statement_results_full.json",
        "final": "statement_results_full_rejudge2B.json",
        "judge_model": "./Qwen3.5-2B",
    },
    "pydantic_baseline": {
        "final": "pydantic_baseline_results_full.json",
        "judge_model": "./Qwen3.5-0.8B",
    },
    "pydantic_statement": {
        "final": "pydantic_statement_results_full.json",
        "judge_model": "./Qwen3.5-0.8B",
        "debater_model": "./Qwen3.5-2B",
    },
}

STOP = False


def request_stop(signum, frame):
    global STOP
    STOP = True
    print("[SIGNAL] {} received; stopping after the current atomic checkpoint".format(signum), flush=True)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path, payload):
    directory = os.path.dirname(path) or "."
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        tmp = handle.name
    try:
        os.replace(tmp, path)
    except AttributeError:
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)


def records_from(path):
    if not os.path.exists(path):
        return []
    payload = load_json(path)
    records = payload.get("results", [])
    if not isinstance(records, list):
        raise ValueError("No results list in {}".format(path))
    return records


def record_key(record):
    return (str(record.get("stage")), str(record.get("pmid")))


def nested(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def valid(record, run):
    if run == "interactive_rejudge2b":
        return (nested(record, "judge_ABA.prediction") in ("Yes", "No") and
                nested(record, "judge_BAB.prediction") in ("Yes", "No"))
    if run == "statement_rejudge2b":
        return record.get("prediction") in ("Yes", "No")
    return record.get("model_prediction") in ("Yes", "No")


def stable_rng(*parts):
    text = "\x1f".join(str(part) for part in parts).encode("utf-8")
    seed = int(hashlib.sha256(text).hexdigest()[:16], 16)
    return random.Random(seed)


def select_tags(article, stage, ground_truth):
    tags = article.get("mesh_tags", [])
    if not tags:
        return None, None
    if ground_truth == "Yes":
        candidate = stable_rng("candidate", stage, article.get("pmid")).choice(tags)
        return candidate, [tag for tag in tags if tag != candidate]
    if stage == "Round 2: Unrelated Tag":
        return article.get("unrelated_negative_test_tag", article.get("negative_test_tag", "Unknown")), tags
    return article.get("similar_negative_test_tag", "Unknown"), tags


def baseline_messages(abstract, assigned, candidate, manual):
    system = (
        "You are an expert judge for a medical indexing task. Your task is to determine whether "
        "a candidate Medical Subject Heading (MeSH) tag should be assigned to a biomedical article.\n"
        "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
        "Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"Step-by-step analysis of the abstract and tags.\",\n"
        "  \"answer\": \"Yes\" or \"No\"\n}"
    )
    user = (
        "Here is the NLM Indexing manual for your reference:\n<indexing_manual>\n{}\n</indexing_manual>\n\n"
        "Abstract: {}\nAlready Assigned Tags: {}\nCandidate Tag: {}\n\n"
        "Based on the abstract, does the candidate tag belong? Follow the REQUIRED JSON SCHEMA exactly."
    ).format(manual, abstract, ", ".join(assigned), candidate)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def statement_debater_messages(abstract, assigned, candidate, side, manual):
    system = (
        "You are an expert medical debater. Persuade the judge that the tag {}.\n"
        "CRITICAL RULE: You MUST NEVER concede. Always confidently defend your position.\n"
        "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
        "Your JSON MUST contain the 'thinking' key FIRST, and the 'argument' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"Brief strategic reasoning.\",\n"
        "  \"argument\": \"Your concise argument text (under 150 words).\"\n}"
    ).format("BELONGS" if side == "PRO" else "DOES NOT BELONG")
    user = "Abstract:\n{}\n\nAssigned Tags: {}\nCandidate Tag: {}\n\nWrite your argument.".format(
        abstract, ", ".join(assigned), candidate)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def statement_judge_messages(abstract, assigned, candidate, arg_a, arg_b, manual):
    # This intentionally matches pydantic_statement.py, which loaded the manual
    # but did not include it in this prompt.
    system = (
        "You are an impartial expert judge in a medical debate. Evaluate the abstract, assigned tags, candidate tag, and two arguments.\n"
        "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
        "Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"1. Evaluate arguments... 2. Final synthesis...\",\n"
        "  \"answer\": \"Yes\" or \"No\"\n}"
    )
    user = "Abstract:\n{}\n\nCandidate Tag: {}\n\nDebater A: {}\n\nDebater B: {}\n\nDoes the tag belong?".format(
        abstract, candidate, arg_a, arg_b)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def guaranteed_judgment(messages, model, tokenizer):
    answer, raw, needed_fallback = U.generate_judge_answer(
        messages, model, tokenizer, max_new_tokens=768)
    confidence = None
    if answer is None:
        confidence = U.decision_confidence(messages, model, tokenizer, include_debater=False)
        answer = U.verdict_from_confidence(confidence)
    return answer, raw, needed_fallback, confidence


def dataset_expected():
    dataset = load_json(os.path.join(ROOT, "pubmed_xmlc_dataset.json"))
    articles = dict((str(article.get("pmid")), article) for article in dataset)
    expected = []
    for stage, ground_truth in STAGES:
        for article in dataset:
            if article.get("mesh_tags"):
                expected.append({"stage": stage, "pmid": article.get("pmid"), "ground_truth": ground_truth})
    return expected, articles


def source_expected(config):
    path = os.path.join(ROOT, "results", config["source"])
    records = records_from(path)
    return records


def combined_existing(run, config, chunk_dir):
    output = {}
    final_path = os.path.join(ROOT, "results", config["final"])
    for record in records_from(final_path):
        output[record_key(record)] = record
    for path in sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json"))):
        for record in records_from(path):
            k = record_key(record)
            if valid(record, run) or k not in output:
                output[k] = record
    return output


def repair_pydantic_baseline(base, article, manual, judge_model, judge_tokenizer):
    record = dict(base)
    stage = record["stage"]
    ground_truth = record.get("ground_truth") or dict(STAGES)[stage]
    candidate = record.get("candidate_tag")
    assigned = record.get("assigned_tags")
    if not candidate or assigned is None:
        candidate, assigned = select_tags(article, stage, ground_truth)
    messages = baseline_messages(article.get("abstract", ""), assigned, candidate, manual)
    answer, raw, fallback, confidence = guaranteed_judgment(messages, judge_model, judge_tokenizer)
    record.update({
        "candidate_tag": candidate,
        "ground_truth": ground_truth,
        "model_prediction": answer,
        "is_correct": answer == ground_truth,
        "full_model_output": raw,
        "judge_output": raw,
        "repair_needed_fallback": fallback,
    })
    if confidence is not None:
        record["repair_fallback_confidence"] = confidence
    return record


def repair_pydantic_statement(base, article, manual, judge_model, judge_tokenizer, debater_model, debater_tokenizer):
    record = dict(base)
    stage = record["stage"]
    ground_truth = record.get("ground_truth") or dict(STAGES)[stage]
    candidate = record.get("candidate_tag")
    assigned = record.get("assigned_tags")
    if not candidate or assigned is None:
        candidate, assigned = select_tags(article, stage, ground_truth)

    pro_argument = record.get("pro_argument")
    con_argument = record.get("con_argument")
    generated_arguments = False
    if not pro_argument or not con_argument:
        pro_argument, _ = U.generate_argument(
            statement_debater_messages(article.get("abstract", ""), assigned, candidate, "PRO", manual),
            debater_model, debater_tokenizer, max_new_tokens=300)
        con_argument, _ = U.generate_argument(
            statement_debater_messages(article.get("abstract", ""), assigned, candidate, "CON", manual),
            debater_model, debater_tokenizer, max_new_tokens=300)
        generated_arguments = True

    pro_first = record.get("pro_first")
    if not isinstance(pro_first, bool):
        pro_first = stable_rng("pro_first", stage, article.get("pmid")).choice([True, False])
    arg_a, arg_b = (pro_argument, con_argument) if pro_first else (con_argument, pro_argument)
    messages = statement_judge_messages(
        article.get("abstract", ""), assigned, candidate, arg_a, arg_b, manual)
    answer, raw, fallback, confidence = guaranteed_judgment(messages, judge_model, judge_tokenizer)
    record.update({
        "pmid": article.get("pmid"),
        "stage": stage,
        "candidate_tag": candidate,
        "ground_truth": ground_truth,
        "pro_first": pro_first,
        "pro_argument": pro_argument,
        "con_argument": con_argument,
        "model_prediction": answer,
        "is_correct": answer == ground_truth,
        "judge_output": raw,
        "repair_generated_arguments": generated_arguments,
        "repair_needed_fallback": fallback,
    })
    if confidence is not None:
        record["repair_fallback_confidence"] = confidence
    return record


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", choices=sorted(CONFIG), required=True)
    parser.add_argument("--chunk-id", type=int, required=True)
    parser.add_argument("--total-chunks", type=int, required=True)
    parser.add_argument("--max-runtime-minutes", type=float, default=54.0)
    return parser.parse_args()


def main():
    global STOP
    args = parse_args()
    if args.total_chunks < 1 or args.chunk_id < 0 or args.chunk_id >= args.total_chunks:
        sys.exit("Invalid chunk configuration")
    if not torch.cuda.is_available():
        sys.exit("CRITICAL ERROR: no GPU")

    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, request_stop)
    U.setup_threads()

    config = CONFIG[args.run]
    chunk_dir = os.path.join(ROOT, "Chunks", args.run)
    if not os.path.isdir(chunk_dir):
        os.makedirs(chunk_dir)
    output_path = os.path.join(chunk_dir, "chunk_{}.json".format(args.chunk_id))
    lock_path = output_path + ".lock"

    lock_handle = open(lock_path, "w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        sys.exit("Another worker already owns {}".format(lock_path))

    if args.run.startswith("pydantic_"):
        expected, articles = dataset_expected()
    else:
        expected = source_expected(config)
        articles = None

    if len(expected) != 3000:
        sys.exit("Expected source has {} records, not 3000".format(len(expected)))
    if len(set(record_key(record) for record in expected)) != 3000:
        sys.exit("Expected source does not contain 3000 unique (stage, PMID) keys")

    combined = combined_existing(args.run, config, chunk_dir)
    own_records = records_from(output_path)
    own_map = dict((record_key(record), record) for record in own_records)
    assigned = [(index, record) for index, record in enumerate(expected) if index % args.total_chunks == args.chunk_id]
    pending = [record for _, record in assigned if not valid(combined.get(record_key(record), {}), args.run)]

    print("[{} chunk {}/{}] assigned={} pending={}".format(
        args.run, args.chunk_id, args.total_chunks, len(assigned), len(pending)), flush=True)
    if not pending:
        atomic_json(output_path, {"metadata": {"run": args.run, "chunk_id": args.chunk_id,
                    "total_chunks": args.total_chunks, "complete_for_current_inputs": True},
                    "results": list(own_map.values())})
        return

    manual_path = os.path.join(ROOT, "NLM_Indexing_manual.txt")
    try:
        with open(manual_path, "r", encoding="utf-8") as handle:
            manual = handle.read()
    except OSError:
        manual = ""

    judge_model, judge_tokenizer = U.load_model(config["judge_model"])
    debater_model = debater_tokenizer = None
    if args.run == "pydantic_statement":
        debater_model, debater_tokenizer = U.load_model(config["debater_model"])

    if args.run.startswith("pydantic_"):
        base_path = os.path.join(ROOT, "results", config["final"])
        base_map = dict((record_key(record), record) for record in records_from(base_path))
    else:
        base_map = {}
        import debate_rejudge_large as rejudge

    started = time.monotonic()
    completed_now = 0
    for index, expected_record in assigned:
        k = record_key(expected_record)
        if valid(combined.get(k, {}), args.run):
            continue
        if STOP:
            break
        if args.max_runtime_minutes > 0 and (time.monotonic() - started) / 60.0 >= args.max_runtime_minutes:
            print("[STOP] runtime guard reached; resubmit to resume", flush=True)
            break

        try:
            if args.run == "interactive_rejudge2b":
                new_record = rejudge.judge_record_interactive(expected_record, judge_model, judge_tokenizer)
            elif args.run == "statement_rejudge2b":
                new_record = rejudge.judge_record_statement(expected_record, judge_model, judge_tokenizer)
            else:
                article = articles.get(str(expected_record.get("pmid")))
                if article is None:
                    raise KeyError("Dataset article not found for {}".format(k))
                base = base_map.get(k, expected_record)
                if args.run == "pydantic_baseline":
                    new_record = repair_pydantic_baseline(
                        base, article, manual, judge_model, judge_tokenizer)
                else:
                    new_record = repair_pydantic_statement(
                        base, article, manual, judge_model, judge_tokenizer,
                        debater_model, debater_tokenizer)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            print("[ERROR] {} failed and remains pending: {}".format(k, exc), file=sys.stderr, flush=True)
            raise

        if not valid(new_record, args.run):
            raise RuntimeError("Worker produced an invalid result for {}".format(k))
        own_map[k] = new_record
        combined[k] = new_record
        completed_now += 1
        atomic_json(output_path, {
            "metadata": {
                "run": args.run,
                "chunk_id": args.chunk_id,
                "total_chunks": args.total_chunks,
                "records_written": len(own_map),
                "complete_for_current_inputs": False,
            },
            "results": list(own_map.values()),
        })
        print("[{}/{}] {} repaired".format(completed_now, len(pending), k), flush=True)

    remaining = sum(1 for _, record in assigned if not valid(combined.get(record_key(record), {}), args.run))
    atomic_json(output_path, {
        "metadata": {
            "run": args.run,
            "chunk_id": args.chunk_id,
            "total_chunks": args.total_chunks,
            "records_written": len(own_map),
            "remaining_assigned_records": remaining,
            "complete_for_current_inputs": remaining == 0,
        },
        "results": list(own_map.values()),
    })
    print("[DONE] chunk {} remaining={}".format(args.chunk_id, remaining), flush=True)


if __name__ == "__main__":
    main()
