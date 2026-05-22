import json
import random
import re
import torch
import os
import argparse
from transformers import AutoModelForCausalLM, AutoTokenizer

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================

# Securely fetch the HuggingFace token from the cluster environment
HF_TOKEN = os.environ.get("HF_TOKEN")

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
DATASET_PATH = "pubmed_xmlc_dataset_final.json" # Ensure your dataset is named this
OUTPUT_PATH = "baseline_experiment_results.json"

random.seed(42)
# ==============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Judge Baseline Evaluation")
    parser.add_argument("--test_mode", action="store_true", 
                        help="If set, only evaluates 5 articles to test the pipeline.")
    return parser.parse_args()

def load_resources():
    print(f"Loading dataset from {DATASET_PATH}...")
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    return dataset

def build_messages(abstract, assigned_tags, candidate_tag):
    system_prompt = (
        "You are an expert judge for a medical indexing task. Your task is to determine whether "
        "a candidate Medical Subject Heading (MeSH) tag should be assigned to a biomedical article "
        "based on its abstract and a set of already assigned tags.\n"
        "Your main objective is to choose whether the candidate tag belongs to the article (Yes) or not (No).\n"
        "You should maintain a scholarly yet assertive tone focused on evidence-based analysis.\n"
        "Structure your output as follows:\n"
        "<thinking>[THINKING]</thinking>\n"
        "Answer: [Yes|No]\n"
        "The automated system only reads the final line, so focus on strictly formatting your final answer."
    )

    user_prompt = f"""Here is the abstract of the article:
<abstract>
{abstract}
</abstract>

Here are the tags that have already been assigned to this article:
<assigned_tags>
{', '.join(assigned_tags)}
</assigned_tags>

Candidate tag to evaluate:
<candidate_tag>
{candidate_tag}
</candidate_tag>

Think step by step about whether the candidate tag correctly describes the article and fits with the existing tags. Put your reasoning inside <thinking></thinking> tags. Then, on a new line, give your final answer formatted exactly as "Answer: Yes" or "Answer: No"."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

def parse_output(generation_text):
    match = re.search(r"Answer:\s*(Yes|No)", generation_text, re.IGNORECASE)
    if match:
        return match.group(1).capitalize()
    return "Unknown"

def run_evaluation(article, stage_name, tokenizer, model):
    """Handles the extraction, prompting, and generation for a single test case."""
    pmid = article.get("pmid", "Unknown")
    abstract = article.get("abstract", "")
    correct_tags = article.get("mesh_tags", [])
    
    similar_tag = article.get("similar_negative_test_tag", "Unknown")
    unrelated_tag = article.get("unrelated_negative_test_tag", article.get("negative_test_tag", "Unknown"))
    
    if not correct_tags:
        return None

    # Define logic for the 3 distinct rounds
    if stage_name == "Round 1: True Tag":
        candidate_tag = random.choice(correct_tags)
        assigned_tags = [t for t in correct_tags if t != candidate_tag]
        ground_truth = "Yes"
    elif stage_name == "Round 2: Unrelated Tag":
        candidate_tag = unrelated_tag
        assigned_tags = correct_tags
        ground_truth = "No"
    elif stage_name == "Round 3: Similar Tag":
        candidate_tag = similar_tag
        assigned_tags = correct_tags
        ground_truth = "No"
    else:
        return None
        
    messages = build_messages(abstract, assigned_tags, candidate_tag)
    text_input = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
    
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=256,
        temperature=0.2, 
        do_sample=True,
        pad_token_id=tokenizer.eos_token_id
    )
    
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    
    prediction = parse_output(response)
    is_correct = (prediction == ground_truth)
    
    return {
        "pmid": pmid,
        "stage": stage_name,
        "candidate_tag": candidate_tag,
        "ground_truth": ground_truth,
        "model_prediction": prediction,
        "is_correct": is_correct,
        "full_model_output": response
    }

def main():
    args = parse_args()
    if not HF_TOKEN:
        print("WARNING: HF_TOKEN environment variable not set! Model loading may fail.")

    dataset = load_resources()
    
    # Toggle for testing vs full run
    if args.test_mode:
        print("\n>>> RUNNING IN TEST MODE: Only evaluating 5 articles <<<")
        dataset = dataset[:5]
        output_file = "test_" + OUTPUT_PATH
    else:
        print(f"\n>>> RUNNING IN FULL MODE: Evaluating all {len(dataset)} articles <<<")
        output_file = OUTPUT_PATH
        
    print(f"Loading {MODEL_ID} into memory...")
    
    auth_kwargs = {"token": HF_TOKEN} if HF_TOKEN else {}
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **auth_kwargs)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.float16,
        device_map="auto",
        **auth_kwargs
    )
    
    # Define our 3 evaluation rounds
    stages = [
        ("Round 1: True Tag", "Asking if a withheld True Tag belongs (Expected: Yes)"),
        ("Round 2: Unrelated Tag", "Asking if a completely Unrelated Tag belongs (Expected: No)"),
        ("Round 3: Similar Tag", "Asking if a highly Similar but incorrect Tag belongs (Expected: No)")
    ]
    
    results = []
    summary_stats = {}
    
    # Loop over stages, then over articles
    for stage_name, stage_desc in stages:
        print("\n" + "="*60)
        print(f"{stage_name.upper()}: {stage_desc}")
        print("="*60)
        
        correct_count = 0
        valid_articles = 0
        
        for i, article in enumerate(dataset):
            result = run_evaluation(article, stage_name, tokenizer, model)
            if result:
                valid_articles += 1
                if result["is_correct"]: 
                    correct_count += 1
                results.append(result)
                
                status_icon = '✅' if result['is_correct'] else '❌'
                print(f"[{i+1}/{len(dataset)}] PMID: {result['pmid']} | Target: {result['ground_truth']:3s} | Pred: {result['model_prediction']:3s} -> {status_icon}")
                
        accuracy = (correct_count / valid_articles) * 100 if valid_articles > 0 else 0
        summary_stats[stage_name] = {
            "accuracy": accuracy,
            "correct": correct_count,
            "total": valid_articles
        }
        
    total_evals = sum(stat["total"] for stat in summary_stats.values())
    total_correct = sum(stat["correct"] for stat in summary_stats.values())
    overall_accuracy = (total_correct / total_evals) * 100 if total_evals > 0 else 0

    print(f"\n======================================================")
    print(f"EXPERIMENT COMPLETE")
    print(f"Total Evaluations: {total_evals}")
    for stage_name, stats in summary_stats.items():
        print(f" - {stage_name} Accuracy: {stats['accuracy']:.2f}% ({stats['correct']}/{stats['total']})")
    print(f"\nOVERALL BASELINE ACCURACY: {overall_accuracy:.2f}%")
    print(f"======================================================\n")

    output_data = {
        "metadata": {
            "model": MODEL_ID,
            "test_mode": args.test_mode,
            "total_evaluations": total_evals,
            "summary_stats": summary_stats,
            "overall_accuracy": overall_accuracy
        },
        "results": results
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
        
    print(f"Data saved successfully. You can find the output file at:\n -> {os.path.abspath(output_file)}\n")

if __name__ == "__main__":
    main()
