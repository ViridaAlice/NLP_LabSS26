import json
import random
import re
import torch
import os
import sys
import argparse
import tempfile
from pydantic import BaseModel, Field, ValidationError
from transformers import AutoModelForCausalLM, AutoTokenizer

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================
HF_TOKEN = os.environ.get("HF_TOKEN")
MODEL_ID = "./Qwen3.5-0.8B" 
DATASET_PATH = "pubmed_xmlc_dataset.json" 
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "pydantic_baseline_results"

random.seed(42)

class JudgeResponse(BaseModel):
    thinking: str = Field(description="Step-by-step reasoning evaluating the candidate tag.")
    answer: str = Field(description="Final decision, strictly 'Yes' or 'No'.")

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--chunk_id", type=int, default=0)
    parser.add_argument("--total_chunks", type=int, default=1)
    return parser.parse_args()

def load_resources():
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    try:
        with open(MANUAL_PATH, "r", encoding="utf-8") as f:
            manual_text = f.read()
    except FileNotFoundError:
        manual_text = ""
    return dataset, manual_text

def build_messages(abstract, assigned_tags, candidate_tag, manual_text):
    system_prompt = (
        "You are an expert judge for a medical indexing task. Your task is to determine whether "
        "a candidate Medical Subject Heading (MeSH) tag should be assigned to a biomedical article.\n"
        "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
        "Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n"
        "{\n"
        "  \"thinking\": \"Step-by-step analysis of the abstract and tags.\",\n"
        "  \"answer\": \"Yes\" or \"No\"\n"
        "}"
    )
    user_prompt = f"""Here is the NLM Indexing manual for your reference:
<indexing_manual>\n{manual_text}\n</indexing_manual>

Abstract: {abstract}
Already Assigned Tags: {', '.join(assigned_tags)}
Candidate Tag: {candidate_tag}

Based on the abstract, does the candidate tag belong? Follow the REQUIRED JSON SCHEMA exactly."""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

def parse_output_pydantic(generation_text):
    cleaned_text = generation_text.strip()
    json_text = re.sub(r'```json\s*', '', cleaned_text, flags=re.IGNORECASE)
    json_text = re.sub(r'```\s*', '', json_text)
    start = json_text.find('{')
    end = json_text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_str = json_text[start:end+1]
        try:
            parsed = JudgeResponse.model_validate_json(json_str)
            ans = parsed.answer.strip().capitalize()
            if ans in ["Yes", "No"]: return ans
        except ValidationError:
            pass
            
    matches = re.findall(r'"answer"\s*:\s*"(Yes|No)"', cleaned_text, re.IGNORECASE)
    if matches: return matches[-1].capitalize()
    return "Unknown"

def save_results_atomically(file_path, data):
    dir_name = os.path.dirname(file_path) or "."
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
    try:
        os.replace(temp_name, file_path)
    except Exception as e:
        if os.path.exists(temp_name): os.remove(temp_name)
        raise e

def main():
    args = parse_args()
    if not torch.cuda.is_available(): sys.exit("CRITICAL ERROR: PyTorch cannot find a GPU!")

    dataset, manual_text = load_resources()
    
    # Precise Chunking Logic
    if args.total_chunks > 1:
        chunk_size = (len(dataset) + args.total_chunks - 1) // args.total_chunks
        start_idx = args.chunk_id * chunk_size
        end_idx = min(start_idx + chunk_size, len(dataset))
        dataset = dataset[start_idx:end_idx]
        output_file = f"{BASE_OUTPUT_PATH}_chunk{args.chunk_id}.json"
        print(f"\n[PARALLEL MODE] Processing Chunk {args.chunk_id+1}/{args.total_chunks} | Articles {start_idx} to {end_idx-1}")
    else:
        output_file = f"{BASE_OUTPUT_PATH}_full.json"
        
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file
        
    completed_evals = set()
    results = []
    
    # CRASH RECOVERY
    if os.path.exists(output_file):
        print(f"\n[RESUME] Found existing save file at {output_file}.")
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                results = saved_data.get("results", [])
                for r in results: completed_evals.add((r["stage"], r["pmid"]))
            print(f" -> Fast-forwarding {len(results)} previous evaluations. Resuming where left off...")
        except json.JSONDecodeError:
            print(" -> [WARNING] Existing file was corrupted. Restarting from scratch.")

    print(f"\nLoading {MODEL_ID} into memory...")
    auth_kwargs = {"token": HF_TOKEN} if HF_TOKEN else {}
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **auth_kwargs)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=torch.float16, device_map="cuda", **auth_kwargs)
    
    stages = [
        ("Round 1: True Tag", "EVALUATING POSITIVE CASES (Expected: Yes)", "Yes"),
        ("Round 2: Unrelated Tag", "EVALUATING NEGATIVE CASES (Expected: No)", "No"),
        ("Round 3: Similar Tag", "EVALUATING TRICKY/SIMILAR NEGATIVE CASES (Expected: No)", "No")
    ]
    
    for stage_name, stage_desc, expected in stages:
        print("\n" + "="*60 + f"\n{stage_name.upper()}: {stage_desc}\n" + "="*60)
            
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in completed_evals: continue
                
            correct_tags = article.get("mesh_tags", [])
            if not correct_tags: continue

            if stage_name == "Round 1: True Tag":
                candidate_tag = random.choice(correct_tags)
                assigned_tags = [t for t in correct_tags if t != candidate_tag]
            elif stage_name == "Round 2: Unrelated Tag":
                candidate_tag = article.get("unrelated_negative_test_tag", article.get("negative_test_tag", "Unknown"))
                assigned_tags = correct_tags
            else:
                candidate_tag = article.get("similar_negative_test_tag", "Unknown")
                assigned_tags = correct_tags
                
            messages = build_messages(article.get("abstract", ""), assigned_tags, candidate_tag, manual_text)
            
            prediction, response = "Unknown", ""
            for attempt in range(3):
                temp = 0.2 if attempt == 0 else 0.4
                text_input = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                model_inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
                generated_ids = model.generate(**model_inputs, max_new_tokens=512, temperature=temp, do_sample=True, pad_token_id=tokenizer.eos_token_id)
                response = tokenizer.batch_decode([g[len(i):] for i, g in zip(model_inputs.input_ids, generated_ids)], skip_special_tokens=True)[0]
                prediction = parse_output_pydantic(response)
                if prediction != "Unknown": break
            
            is_correct = (prediction == expected)
            status_icon = '✅' if is_correct else '❌'
            print(f"[{i+1}/{len(dataset)}] PMID: {pmid} | Target: {expected:3s} | Pred: {prediction:3s} -> {status_icon}")
            
            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate_tag, "ground_truth": expected,
                "model_prediction": prediction, "is_correct": is_correct, "full_model_output": response
            })
            completed_evals.add((stage_name, pmid))
            
            # ATOMIC SAVE
            total = len(results)
            accuracy = (sum(1 for r in results if r["is_correct"]) / total) * 100 if total > 0 else 0
            save_results_atomically(output_file, {"metadata": {"overall_accuracy": accuracy}, "results": results})

    print(f"\n================ EXPERIMENT COMPLETE ================\n")

if __name__ == "__main__":
    main()
