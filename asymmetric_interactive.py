#!/usr/bin/env python3

from pydantic import BaseModel, Field

from asymmetric_common import (
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
REUSED_DEBATER_MODEL_ID = "./Qwen3.5-2B"
EXPERIMENT_ID = "asymmetric_titleonly_interactive_aba"


class JudgeResponse(BaseModel):
    thinking: str = Field(description="Reasoning based on the title and saved ABA transcript.")
    answer: str = Field(description="Final decision, strictly Yes or No.")


def build_judge_messages(
    title,
    candidate_tag,
    pro_first,
    a_turn1,
    b_turn1,
    a_turn2,
):
    system_prompt = (
        "You are an impartial biomedical MeSH judge. You receive only the paper title, "
        "candidate tag, and a previously saved ABA debate transcript. You do NOT receive "
        "the abstract, assigned tags, or indexing manual. Evaluate the arguments and "
        "decide whether the candidate tag belongs.\n\n"
        "Return one valid JSON object with 'thinking' first and 'answer' last. The "
        "answer must be exactly 'Yes' or 'No'.\n"
        "REQUIRED JSON SCHEMA:\n"
        "{\n"
        "  \"thinking\": \"Evaluate the saved ABA transcript and decide.\",\n"
        "  \"answer\": \"Yes\" or \"No\"\n"
        "}"
    )

    a_side = "PRO" if pro_first else "CON"
    b_side = "CON" if pro_first else "PRO"
    user_prompt = (
        "Paper Title:\n%s\n\nCandidate MeSH Tag: %s\n\n"
        "Turn 1 - Debater A (%s):\n%s\n\n"
        "Turn 2 - Debater B (%s):\n%s\n\n"
        "Turn 3 - Debater A (%s) rebuttal:\n%s\n\n"
        "Should the candidate tag be assigned?"
        % (
            title,
            candidate_tag,
            a_side,
            a_turn1,
            b_side,
            b_turn1,
            a_side,
            a_turn2,
        )
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def main():
    args = parse_args(
        "Judge-only asymmetric ABA re-evaluation using saved 2B debates",
        allow_source=True,
    )

    # The dataset contributes only the title associated with each saved PMID.
    title_index = build_title_index(load_dataset())
    cases, source_path, source_raw_count, source_skipped = load_source_debate_cases(
        "interactive",
        title_index,
        args.chunk_id,
        args.total_chunks,
        explicit_path=args.source_file,
        test_mode=args.test_mode,
    )

    path = output_path(EXPERIMENT_ID, args.chunk_id, args.test_mode)
    records_by_key, completed = load_checkpoint(path)

    metadata = base_metadata(
        EXPERIMENT_ID,
        "interactive_aba",
        args,
        judge_model=JUDGE_MODEL_ID,
        debater_model=REUSED_DEBATER_MODEL_ID,
    )
    metadata.update(
        {
            "judge_information": [
                "title",
                "candidate_tag",
                "saved_a_turn1",
                "saved_b_turn1",
                "saved_a_turn2",
                "saved_pro_first",
            ],
            "turn_order": "ABA",
            "debate_source_file": source_path,
            "debate_source_sha256": file_sha256(source_path),
            "source_raw_records": source_raw_count,
            "source_skipped_records": source_skipped,
            "debater_outputs_reused": True,
            "new_debater_generation": False,
            "loaded_models": [JUDGE_MODEL_ID],
        }
    )

    if all_cases_complete(cases, completed):
        print(
            "[COMPLETE] Interactive chunk already contains judgments for every available "
            "saved debate; no model load needed."
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
                case["a_turn1"],
                case["b_turn1"],
                case["a_turn2"],
            ),
            judge_model,
            judge_tokenizer,
            JudgeResponse,
            "answer",
            max_new_tokens=512,
        )

        generation_complete = prediction in ("Yes", "No")
        is_correct = generation_complete and prediction == case["ground_truth"]
        a_side = "PRO" if case["pro_first"] else "CON"
        b_side = "CON" if case["pro_first"] else "PRO"
        record = {
            "pmid": case["pmid"],
            "stage": case["stage"],
            "title": case["title"],
            "candidate_tag": case["candidate_tag"],
            "ground_truth": case["ground_truth"],
            "turn_order": "ABA",
            "pro_first": case["pro_first"],
            "a_side": a_side,
            "b_side": b_side,
            "a_turn1": case["a_turn1"],
            "b_turn1": case["b_turn1"],
            "a_turn2": case["a_turn2"],
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
        "[COMPLETE] Interactive ABA chunk %d judged using saved debates only."
        % args.chunk_id,
        flush=True,
    )


if __name__ == "__main__":
    main()
