import json
import random
import re
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================

# >>> INSERT YOUR HUGGING FACE TOKEN HERE <<<
# Example: HF_TOKEN = "hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
# You can generate a token at https://huggingface.co/settings/tokens
HF_TOKEN = "" 

MODEL_ID = "Qwen/Qwen1.5-1.8B-Chat"
DATASET_PATH = "pubmed_xmlc_dataset_final.json" # Ensure this matches your final output filename
MANUAL_PATH = "NLM_Indexing_manual.txt"
OUTPUT_PATH = "baseline_experiment_results_2000.json"
SAMPLE_SIZE = 1000 # Set to 1000 to process the full file

# Set a random seed for reproducibility
random.seed(42)
# ==============================================================================

def load_resources():
    print(f"Loading dataset from {DATASET_PATH}...")
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print(f"Loading NLM Indexing Manual from {MANUAL_PATH}...")
    try:
        with open(MANUAL_PATH, "r", encoding="utf-8") as f:
            manual_text = f.read()
    except FileNotFoundError:
        print(f"Warning: {MANUAL_PATH} not found. Using an empty string for the manual.")
        manual_text = ""
        
    return dataset, manual_text

def build_messages(abstract, assigned_tags, candidate_tag, manual_text):
    system_prompt = (
        "You are an expert judge for a medical indexing task. Your task is to determine whether "
        "a candidate Medical Subject Heading (MeSH) tag should be assigned to a biomedical article "
        "based on its abstract and a set of already assigned tags.\n"
        "To guide you, you are provided with excerpts from the NLM Indexing Manual.\n"
        "Your main objective is to choose whether the candidate tag belongs to the article (Yes) or not (No).\n"
        "You should maintain a scholarly yet assertive tone focused on evidence-based analysis.\n"
        "Structure your output as follows:\n"
        "<thinking>[THINKING]</thinking>\n"
        "Answer:[Yes|No]\n"
        "The automated system only reads the final line, so focus on strictly formatting your final answer."
    )

    user_prompt = f"""Here is the NLM Indexing manual for your reference:
<indexing_manual>
{manual_text}
</indexing_manual>

Here is the abstract of the article:
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

Think step by step about whether the candidate tag correctly describes the article and fits with the existing tags, keeping the indexing manual in mind. Put your reasoning inside <thinking></thinking> tags. Then, on a new line, give your final answer formatted exactly as "Answer: Yes" or "Answer: No"."""

    return[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

def parse_output(generation_text):
    match = re.search(r"Answer:\s*(Yes|No)", generation_text, re.IGNORECASE)
    if match:
        return match.group(1).capitalize()
    return "Unknown"

def run_evaluation(article, is_true_case, tokenizer, model, manual_text):
    """Handles the extraction, prompting, and generation for a single test case."""
    pmid = article.get("pmid", "Unknown")
    abstract = article.get("abstract", "")
    correct_tags = article.get("mesh_tags",[])
    incorrect_tag = article.get("similar_negative_test_tag", article.get("negative_test_tag", ""))
    
    if not correct_tags or not incorrect_tag:
        return None
        
    if is_true_case:
        candidate_tag = random.choice(correct_tags)
        assigned_tags = [t for t in correct_tags if t != candidate_tag]
        ground_truth = "Yes"
    else:
        candidate_tag = incorrect_tag
        assigned_tags = correct_tags
        ground_truth = "No"
        
    messages = build_messages(abstract, assigned_tags, candidate_tag, manual_text)
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
        "is_true_case": is_true_case,
        "candidate_tag": candidate_tag,
        "ground_truth": ground_truth,
        "model_prediction": prediction,
        "is_correct": is_correct,
        "full_model_output": response
    }

def main():
    dataset, manual_text = load_resources()
    test_set = dataset[:SAMPLE_SIZE]
    
    print(f"\nLoading {MODEL_ID} into memory...")
    
    # We pass the HF_TOKEN to avoid rate-limiting warnings
    # We also use dtype instead of the deprecated torch_dtype
    auth_kwargs = {"token": HF_TOKEN} if HF_TOKEN else {}
    
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **auth_kwargs)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.float16,
        device_map="auto",
        **auth_kwargs
    )
    
    results =[]
    correct_positives = 0
    correct_negatives = 0
    valid_articles = 0
    
    print("\n" + "="*50)
    print("PASS 1: EVALUATING POSITIVE CASES (True Tags)")
    print("="*50)
    
    for i, article in enumerate(test_set):
        result = run_evaluation(article, is_true_case=True, tokenizer=tokenizer, model=model, manual_text=manual_text)
        if result:
            valid_articles += 1
            if result["is_correct"]: correct_positives += 1
            results.append(result)
            
            print(f"[{i+1}/{len(test_set)}] PMID: {result['pmid']} | Target: YES | Pred: {result['model_prediction']} -> {'✅' if result['is_correct'] else '❌'}")
    
    print("\n" + "="*50)
    print("PASS 2: EVALUATING NEGATIVE CASES (Tricky/Similar Tags)")
    print("="*50)
    
    for i, article in enumerate(test_set):
        result = run_evaluation(article, is_true_case=False, tokenizer=tokenizer, model=model, manual_text=manual_text)
        if result:
            if result["is_correct"]: correct_negatives += 1
            results.append(result)
            
            print(f"[{i+1}/{len(test_set)}] PMID: {result['pmid']} | Target: NO  | Pred: {result['model_prediction']} -> {'✅' if result['is_correct'] else '❌'}")

    # --- CALCULATE METRICS & SAVE ---
    total_evaluations = valid_articles * 2
    pos_accuracy = (correct_positives / valid_articles) * 100 if valid_articles > 0 else 0
    neg_accuracy = (correct_negatives / valid_articles) * 100 if valid_articles > 0 else 0
    overall_accuracy = ((correct_positives + correct_negatives) / total_evaluations) * 100 if total_evaluations > 0 else 0

    print(f"\n======================================================")
    print(f"EXPERIMENT COMPLETE")
    print(f"Total Evaluations: {total_evaluations} (Across {valid_articles} valid articles)")
    print(f"Positive Case Accuracy (True Tags)   : {pos_accuracy:.2f}%")
    print(f"Negative Case Accuracy (Tricky Tags) : {neg_accuracy:.2f}%")
    print(f"Overall Baseline Accuracy            : {overall_accuracy:.2f}%")
    print(f"======================================================\n")

    output_data = {
        "metadata": {
            "model": MODEL_ID,
            "total_evaluations": total_evaluations,
            "positive_accuracy": pos_accuracy,
            "negative_accuracy": neg_accuracy,
            "overall_accuracy": overall_accuracy
        },
        "results": results
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
        
    print(f"Detailed baseline results saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
