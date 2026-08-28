#!/usr/bin/env python3

import os

from pydantic import BaseModel, Field

from asymmetric_common import (
    SOURCE_LAYOUT_VERSION,
    all_cases_complete,
    base_metadata,
    build_title_index,
    case_key,
    ensure_cuda,
    file_sha256,
    generate_structured,
    load_checkpoint,
    load_dataset,
    load_model_and_tokenizer,
    load_source_debate_cases,
    output_path,
    parse_args,
    print_case_result,
    save_checkpoint,
)

JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
SOURCE_DEBATER_MODEL_ID = "./Qwen3.5-2B"
SOURCE_BASENAME = "pydantic_statement_results_full.json"
EXPERIMENT_ID = "asymmetric_titleonly_statement"


class JudgeResponse(BaseModel):
    thinking: str = Field(description="Reasoning based on the title and saved arguments.")
    answer: str = Field(description="Final decision, strictly Yes or No.")


def build_judge_messages(title, candidate_tag, pro_first, pro_argument, con_argument):
    system_prompt = (
        "You are an impartial biomedical MeSH judge. You receive only the paper title, "
        "candidate tag, and two previously saved debater statements. You do NOT receive "
        "the abstract, assigned tags, or indexing manual. Evaluate the competing claims "
        "and decide whether the candidate tag belongs.\n\n"
        "Return one valid JSON object with 'thinking' first and 'answer' last. The "
        "answer must be exactly 'Yes' or 'No'.\n"
        "REQUIRED JSON SCHEMA:\n"
        "{\n"
        "  \"thinking\": \"Evaluate both statements and synthesize a decision.\",\n"
        "  \"answer\": \"Yes\" or \"No\"\n"
        "}"
    )

    if pro_first:
        first_side, first_argument = "PRO", pro_argument
        second_side, second_argument = "CON", con_argument
    else:
        first_side, first_argument = "CON", con_argument
        second_side, second_argument = "PRO", pro_argument

    user_prompt = (
        "Paper Title:\n%s\n\nCandidate MeSH Tag: %s\n\n"
        "First statement (%s):\n%s\n\nSecond statement (%s):\n%s\n\n"
        "Should the candidate tag be assigned?"
        % (
            title,
            candidate_tag,
            first_side,
            first_argument,
            second_side,
            second_argument,
        )
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def main():
    args = parse_args(
        "Judge-only asymmetric statement re-evaluation using the full saved 2B file",
        allow_source=True,
    )

    title_index = build_title_index(load_dataset())
    cases, source_path, source_stats = load_source_debate_cases(
        "statement",
        title_index,
        args.chunk_id,
        args.total_chunks,
        explicit_path=args.source_file,
        test_mode=args.test_mode,
    )
    source_sha256 = file_sha256(source_path)

    path = output_path(EXPERIMENT_ID, args.chunk_id, args.test_mode)
    compatibility = {
        "experiment_id": EXPERIMENT_ID,
        "source_layout_version": SOURCE_LAYOUT_VERSION,
        "debate_source_sha256": source_sha256,
        "source_chunk_start": source_stats["source_chunk_start"],
        "source_chunk_end": source_stats["source_chunk_end"],
    }
    records_by_key, completed = load_checkpoint(
        path, required_metadata=compatibility
    )

    metadata = base_metadata(
        EXPERIMENT_ID,
        "statement",
        args,
        judge_model=JUDGE_MODEL_ID,
        debater_model=SOURCE_DEBATER_MODEL_ID,
    )
    metadata.update(source_stats)
    metadata.update(
        {
            "judge_information": [
                "title",
                "candidate_tag",
                "saved_pro_argument",
                "saved_con_argument",
                "saved_pro_first",
            ],
            "debate_source_file": source_path,
            "debate_source_basename": os.path.basename(source_path),
            "debate_source_sha256": source_sha256,
            "debater_outputs_reused": True,
            "new_debater_generation": False,
            "loaded_models": [JUDGE_MODEL_ID],
        }
    )

    if os.path.basename(source_path) != SOURCE_BASENAME and args.source_file is None:
        raise RuntimeError("Unexpected default statement source: %s" % source_path)

    if all_cases_complete(cases, completed):
        print(
            "[COMPLETE] Statement chunk already contains judgments for every saved "
            "debate in its full-file slice; no model load needed."
        )
        save_checkpoint(path, metadata, records_by_key, len(cases))
        return

    ensure_cuda()
    print("[REUSE] No debater model will be loaded or called.", flush=True)
    print("Loading Judge Model (%s)..." % JUDGE_MODEL_ID, flush=True)
    judge_model, judge_tokenizer = load_model_and_tokenizer(JUDGE_MODEL_ID)

    for index, case in enumerate(cases, start=1):
        key = case_key(case)
        if key in completed:
            continue

        prediction, raw_judge = generate_structured(
            build_judge_messages(
                case["title"],
                case["candidate_tag"],
                case["pro_first"],
                case["pro_argument"],
                case["con_argument"],
            ),
            judge_model,
            judge_tokenizer,
            JudgeResponse,
            "answer",
            max_new_tokens=512,
        )

        generation_complete = prediction in ("Yes", "No")
        is_correct = generation_complete and prediction == case["ground_truth"]
        record = {
            "pmid": case["pmid"],
            "stage": case["stage"],
            "title": case["title"],
            "candidate_tag": case["candidate_tag"],
            "ground_truth": case["ground_truth"],
            "pro_first": case["pro_first"],
            "pro_argument": case["pro_argument"],
            "con_argument": case["con_argument"],
            "source_debate_file": source_path,
            "source_record_index": case["source_record_index"],
            "debater_outputs_reused": True,
            "new_debater_generation": False,
            "model_prediction": prediction,
            "is_correct": is_correct,
            "generation_complete": generation_complete,
            "judge_received_abstract": False,
            "judge_output": raw_judge,
        }
        records_by_key[key] = record
        if generation_complete:
            completed.add(key)

        save_checkpoint(path, metadata, records_by_key, len(cases))
        print_case_result(index, len(cases), case, prediction, generation_complete)

    print(
        "[COMPLETE] Statement chunk %d judged using the saved full source only."
        % args.chunk_id,
        flush=True,
    )


if __name__ == "__main__":
    main()
