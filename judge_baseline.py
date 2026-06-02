import json
import random
import re
import torch
import os
import sys
import argparse
from transformers import AutoModelForCausalLM, AutoTokenizer

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================
HF_TOKEN = os.environ.get("HF_TOKEN")

MODEL_ID = "./Qwen2.5-0.5B-Instruct"  
DATASET_PATH = "pubmed_xmlc_dataset.json" 
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "baseline_experiment_results"

random.seed(42)
# ==============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Judge Baseline Evaluation")
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    # New arguments for Job Arrays (Splitting the dataset)
    parser.add_argument("--chunk_id", type=int, default=0, help="ID of the current chunk (0 to total_chunks-1)")
    parser.add_argument("--total_chunks", type=int, default=1, help="Total number of chunks to split the dataset into")
    return parser.parse_args()

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
        "You should maintain a concise, scholarly, and assertive tone focused on evidence-based analysis.\n"
        "Structure your output as follows:\n"
        "<thinking>[THINKING]</thinking>\n"
        "Answer: [Yes|No]\n"
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

Briefly think step by step about whether the candidate tag correctly describes the article. Keep your thinking concise and focused. Put your reasoning inside <thinking></thinking> tags. Then, on a new line, give your final answer formatted exactly as \"Answer: Yes\" or \"Answer: No\"."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

def parse_output(generation_text, pmid, stage_name, verbose=False):
    cleaned_text = generation_text.strip()
    
    if verbose:
        print(f"\n      " + "-"*50)
        print(f"      [TALKING PARSER] Diagnostic Log for PMID {pmid} ({stage_name})")
        print(f"      " + "-"*50)
        print(f"      >>> RAW GENERATED TEXT FROM MODEL:\n\"\"\"\n{cleaned_text}\n\"\"\"")
        print(f"      " + "-"*50)
    
    match = re.search(r"Answer:\s*(Yes|No)", cleaned_text, re.IGNORECASE)
    if match:
        result = match.group(1).capitalize()
        if verbose: print(f"      [TIER 1 MATCH]: Found pattern 'Answer: {result}'")
        return result
        
    if "</thinking>" in cleaned_text:
        after_thinking = cleaned_text.split("</thinking>")[-1].strip()
        after_thinking_clean = re.sub(r'[^\w\s]', '', after_thinking).strip().split()
        for word in after_thinking_clean:
            word_cap = word.capitalize()
            if word_cap in ["Yes", "No"]:
                if verbose: print(f"      [TIER 2 MATCH]: Found isolated word '{word_cap}' after </thinking>")
                return word_cap

    lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
    if lines:
        last_line = lines[-1]
        if re.search(r"\b(yes)\b", last_line, re.IGNORECASE):
            if verbose: print("      [TIER 3 MATCH]: Found 'yes' in the last line")
            return "Yes"
        if re.search(r"\b(no)\b", last_line, re.IGNORECASE):
            if verbose: print("      [TIER 3 MATCH]: Found 'no' in the last line")
            return "No"

    end_words = re.sub(r'[^\w\s]', '', cleaned_text).strip().split()
    if end_words:
        last_word = end_words[-1].capitalize()
        if last_word in ["Yes", "No"]:
            if verbose: print(f"      [TIER 4 MATCH]: Last word is '{last_word}'")
            return last_word
            
    if verbose: print("      [ALL TIERS FAILED]: Output is unparseable -> Parsed as: Unknown")
    return "Unknown"

def run_evaluation(article, stage_name, tokenizer, model, manual_text, verbose=False):
    pmid = article.get("pmid", "Unknown")
    abstract = article.get("abstract", "")
    correct_tags = article.get("mesh_tags", [])
    
    similar_tag = article.get("similar_negative_test_tag", "Unknown")
    unrelated_tag = article.get("unrelated_negative_test_tag", article.get("negative_test_tag", "Unknown"))
    
    if not correct_tags:
        return None

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
        
    messages = build_messages(abstract, assigned_tags, candidate_tag, manual_text)
    text_input = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
    
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=512, 
        temperature=0.2, 
        do_sample=True,
        pad_token_id=tokenizer.eos_token_id
    )
    
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    
    prediction = parse_output(response, pmid, stage_name, verbose=verbose)
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

    # Determine GPU availability
    if not torch.cuda.is_available():
        print("CRITICAL ERROR: PyTorch cannot find a GPU! Your job will take 500x longer on a CPU.")
        print("Please check your SLURM script, CUDA modules, or PyTorch installation.")
        sys.exit(1) # Stop the script immediately so we don't waste 1 hour computing on a CPU

    dataset, manual_text = load_resources()
    
    # --- CHUNKING LOGIC FOR PARALLEL EXECUTION ---
    if args.total_chunks > 1:
        chunk_size = len(dataset) // args.total_chunks
        start_idx = args.chunk_id * chunk_size
        # The last chunk takes any remaining articles
        end_idx = start_idx + chunk_size if args.chunk_id < args.total_chunks - 1 else len(dataset)
        dataset = dataset[start_idx:end_idx]
        output_file = f"{BASE_OUTPUT_PATH}_chunk{args.chunk_id}.json"
        print(f"\n[PARALLEL MODE] Processing Chunk {args.chunk_id+1}/{args.total_chunks} | Articles {start_idx} to {end_idx-1}")
    else:
        output_file = f"{BASE_OUTPUT_PATH}_full.json"
        
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file
        
    # --- CRASH-PROOF RESUME LOGIC ---
    completed_evals = set()
    results = []
    
    if os.path.exists(output_file):
        print(f"\n[RESUME] Found existing save file at {output_file}.")
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                results = saved_data.get("results", [])
                for r in results:
                    completed_evals.add((r["stage"], r["pmid"]))
            print(f" -> Fast-forwarding {len(results)} previous evaluations.")
        except json.JSONDecodeError:
            pass

    print(f"\nLoading {MODEL_ID} into memory...")
    
    auth_kwargs = {"token": HF_TOKEN} if HF_TOKEN else {}
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **auth_kwargs)
    
    # We explicitly force the device mapping to "cuda"
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
        device_map="cuda", 
        **auth_kwargs
    )
    
    print(f"\n[SUCCESS] Model loaded successfully on: {model.device}\n")
    
    stages = [
        ("Round 1: True Tag", "EVALUATING POSITIVE CASES (Expected: Yes)"),
        ("Round 2: Unrelated Tag", "EVALUATING NEGATIVE CASES (Expected: No)"),
        ("Round 3: Similar Tag", "EVALUATING TRICKY/SIMILAR NEGATIVE CASES (Expected: No)")
    ]
    
    for stage_name, stage_desc in stages:
        print("="*60)
        print(f"{stage_name.upper()}: {stage_desc}")
        print("="*60)
            
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            
            if (stage_name, pmid) in completed_evals:
                continue
                
            result = run_evaluation(article, stage_name, tokenizer, model, manual_text, verbose=args.verbose)
            if result:
                results.append(result)
                completed_evals.add((stage_name, pmid))
                
                status_icon = '✅' if result['is_correct'] else '❌'
                print(f"[{i+1}/{len(dataset)}] PMID: {pmid} | Target: {result['ground_truth']:3s} | Pred: {result['model_prediction']:3s} -> {status_icon}")
                
                # --- INCREMENTAL SAVE LOGIC ---
                summary_stats = {}
                for r in results:
                    sn = r["stage"]
                    if sn not in summary_stats:
                        summary_stats[sn] = {"accuracy": 0, "correct": 0, "total": 0}
                    summary_stats[sn]["total"] += 1
                    if r["is_correct"]:
                        summary_stats[sn]["correct"] += 1
                        
                for sn in summary_stats:
                    summary_stats[sn]["accuracy"] = (summary_stats[sn]["correct"] / summary_stats[sn]["total"]) * 100
                
                total_evals = len(results)
                total_correct = sum(1 for r in results if r["is_correct"])
                overall_accuracy = (total_correct / total_evals) * 100 if total_evals > 0 else 0
                
                output_data = {
                    "metadata": {
                        "model": MODEL_ID,
                        "chunk_id": args.chunk_id,
                        "total_evaluations": total_evals,
                        "summary_stats": summary_stats,
                        "overall_accuracy": overall_accuracy
                    },
                    "results": results
                }

                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=4, ensure_ascii=False)
                # -------------------------------

    print(f"\n======================================================")
    print(f"CHUNK {args.chunk_id} EXPERIMENT COMPLETE")
    print(f"======================================================\n")

if __name__ == "__main__":
    main()
