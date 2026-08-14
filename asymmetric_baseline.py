#!/usr/bin/env python3

from pydantic import BaseModel, Field

from asymmetric_common import (
    all_cases_complete,
    base_metadata,
    build_cases,
    case_key,
    ensure_cuda,
    generate_structured,
    load_checkpoint,
    load_dataset,
    load_model_and_tokenizer,
    output_path,
    parse_args,
    print_case_result,
    save_checkpoint,
    select_chunk,
)

JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
EXPERIMENT_ID = "asymmetric_titleonly_baseline"


class JudgeResponse(BaseModel):
    thinking: str = Field(description="Brief reasoning based only on the paper title.")
    answer: str = Field(description="Final decision, strictly Yes or No.")


def build_judge_messages(title, candidate_tag):
    system_prompt = (
        "You are an expert judge for a biomedical MeSH indexing task. Decide whether "
        "the candidate MeSH tag belongs to the paper. You receive ONLY the paper title "
        "and candidate tag: you do not have the abstract, assigned tags, an indexing "
        "manual, or debater input. Base the decision only on the supplied title.\n\n"
        "Return one valid JSON object with the 'thinking' key first and the 'answer' "
        "key last. The answer must be exactly 'Yes' or 'No'.\n"
        "REQUIRED JSON SCHEMA:\n"
        "{\n"
        "  \"thinking\": \"Brief title-based reasoning.\",\n"
        "  \"answer\": \"Yes\" or \"No\"\n"
        "}"
    )
    user_prompt = (
        "Paper Title:\n%s\n\nCandidate MeSH Tag: %s\n\n"
        "Based only on the paper title, should the candidate tag be assigned?"
        % (title, candidate_tag)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def main():
    args = parse_args("Asymmetric title-only baseline with a 0.8B judge")
    dataset = load_dataset()
    dataset, _, _ = select_chunk(
        dataset, args.chunk_id, args.total_chunks, args.test_mode
    )
    cases = build_cases(dataset)
    path = output_path(EXPERIMENT_ID, args.chunk_id, args.test_mode)
    records_by_key, completed = load_checkpoint(path)

    metadata = base_metadata(
        EXPERIMENT_ID,
        "baseline",
        args,
        judge_model=JUDGE_MODEL_ID,
    )
    metadata["judge_information"] = ["title", "candidate_tag"]

    if all_cases_complete(cases, completed):
        print("[COMPLETE] Baseline chunk already contains all records; no model load needed.")
        save_checkpoint(path, metadata, records_by_key, len(cases))
        return

    ensure_cuda()
    print("Loading Judge Model (%s)..." % JUDGE_MODEL_ID, flush=True)
    judge_model, judge_tokenizer = load_model_and_tokenizer(JUDGE_MODEL_ID)

    for index, case in enumerate(cases, start=1):
        key = case_key(case)
        if key in completed:
            continue

        messages = build_judge_messages(case["title"], case["candidate_tag"])
        prediction, raw_judge = generate_structured(
            messages,
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

    print("[COMPLETE] Baseline chunk %d finished." % args.chunk_id, flush=True)


if __name__ == "__main__":
    main()
