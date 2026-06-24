import json
import re
import os
import sys
import torch
import argparse
import tempfile
from pydantic import BaseModel, Field, ValidationError
from transformers import AutoModelForCausalLM, AutoTokenizer

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================
HF_TOKEN = os.environ.get("HF_TOKEN")
JUDGE_MODEL_ID = "./Qwen3.5-0.8B"
DATASET_PATH = "pubmed_xmlc_dataset.json"
MANUAL_PATH = "NLM_Indexing_manual.txt"

FILES_TO_FIX = [
    "pydantic_baseline_results_full.json",
    "pydantic_statement_results_full.json",
    "pydantic_interactive_results_full.json"
]

class JudgeResponse(BaseModel):
    thinking: str = Field(description="Step-by-step reasoning evaluating the candidate tag.")
    answer: str = Field(description="Final decision, strictly 'Yes' or 'No'.")

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task_id", type=int, default=0, help="ID of the file to fix (0, 1, or 2)")
    return parser.parse_args()

# ==============================================================================
# PROMPT BUILDERS
# ==============================================================================

def build_baseline_msg(abstract, assigned_tags, candidate_tag, manual_text):
    sys_p = "You are an expert judge for a medical indexing task. Your task is to determine whether a candidate Medical Subject Heading (MeSH) tag should be assigned to a biomedical article.\nCRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\nREQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"Step-by-step analysis...\",\n  \"answer\": \"Yes\" or \"No\"\n}"
    usr_p = f"Here is the NLM Indexing manual for your reference:\n<indexing_manual>\n{manual_text}\n</indexing_manual>\n\nAbstract: {abstract}\nAlready Assigned Tags: {', '.join(assigned_tags)}\nCandidate Tag: {candidate_tag}\n\nBased on the abstract, does the candidate tag belong? Follow the REQUIRED JSON SCHEMA exactly."
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}]

def build_statement_msg(abstract, assigned_tags, candidate_tag, arg1, arg2, manual_text):
    sys_p = "You are an impartial expert judge in a medical debate. Evaluate the abstract, assigned tags, candidate tag, and two arguments.\nCRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\nREQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"1. Evaluate arguments... 2. Final synthesis...\",\n  \"answer\": \"Yes\" or \"No\"\n}"
    usr_p = f"Here is the NLM Indexing manual for your reference:\n<indexing_manual>\n{manual_text}\n</indexing_manual>\n\nAbstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\nDebater A's Argument:\n{arg1}\n\nDebater B's Argument:\n{arg2}\n\nBased on the abstract and the debate, does the candidate tag belong? Follow the REQUIRED JSON SCHEMA exactly."
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}]

def build_interactive_msg(abstract, assigned_tags, candidate_tag, arg1, arg2, arg3, manual_text):
    sys_p = "You are an impartial expert judge in a medical debate evaluating if a candidate tag belongs to an abstract.\nCRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\nREQUIRED JSON SCHEMA:\n{\n  \"thinking\": \"1. Evaluate arguments... 2. Final synthesis...\",\n  \"answer\": \"Yes\" or \"No\"\n}"
    usr_p = f"Here is the NLM Indexing manual for your reference:\n<indexing_manual>\n{manual_text}\n</indexing_manual>\n\nAbstract:\n{abstract}\nCandidate Tag: {candidate_tag}\n\nDebater A: {arg1}\n\nDebater B: {arg2}\n\nDebater A Rebuttal: {arg3}\n\nDoes the tag belong?"
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}]

# ==============================================================================

def extract_pydantic(response):
    json_text = re.sub(r'```json\s*', '', response, flags=re.IGNORECASE)
    json_text = re.sub(r'```\s*', '', json_text)
    start = json_text.find('{')
    end = json_text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            parsed = JudgeResponse.model_validate_json(json_text[start:end+1])
            ans = parsed.answer.strip().capitalize()
            if ans in ["Yes", "No"]: return ans
        except ValidationError: pass
    
    matches = re.findall(r'"answer"\s*:\s*"(Yes|No)"', response, re.IGNORECASE)
    if matches: return matches[-1].capitalize()
    return "Unknown"

def get_assigned_tags(dataset_dict, pmid, stage_name, candidate_tag):
    article = dataset_dict.get(pmid, {})
    correct_tags = article.get("mesh_tags", [])
    if stage_name == "Round 1: True Tag":
        return [t for t in correct_tags if t != candidate_tag]
    return correct_tags

def save_results_atomically(file_path, data):
    dir_name = os.path.dirname(file_path) or "."
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
    try: os.replace(temp_name, file_path)
    except Exception as e:
        if os.path.exists(temp_name): os.remove(temp_name)
        raise e

def main():
    args = parse_args()
    
    # Ensure the task ID is within bounds (0, 1, or 2)
    if args.task_id < 0 or args.task_id >= len(FILES_TO_FIX):
        sys.exit(f"Invalid task_id: {args.task_id}. Must be 0, 1, or 2.")
        
    filepath = FILES_TO_FIX[args.task_id]

    if not torch.cuda.is_available(): sys.exit("CRITICAL ERROR: No GPU!")

    print("Loading dataset for abstract references...")
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset_list = json.load(f)
    dataset_dict = {item["pmid"]: item for item in dataset_list}
    
    try:
        with open(MANUAL_PATH, "r", encoding="utf-8") as f: manual_text = f.read()
    except: manual_text = ""

    print(f"Loading Judge Model ({JUDGE_MODEL_ID})...")
    tokenizer = AutoTokenizer.from_pretrained(JUDGE_MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(JUDGE_MODEL_ID, torch_dtype=torch.float16, device_map="cuda")

    if not os.path.exists(filepath):
        sys.exit(f"File {filepath} not found. Exiting...")
        
    print(f"\n======================================")
    print(f" Scanning {filepath} for 'Unknowns'")
    print(f"======================================")
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    results = data.get("results", [])
    unknowns_fixed = 0

    for idx, r in enumerate(results):
        # Crash-Proofing: It skips any entry that isn't 'Unknown'
        if r.get("model_prediction") == "Unknown":
            pmid = r["pmid"]
            stage = r["stage"]
            candidate = r["candidate_tag"]
            abstract = dataset_dict[pmid].get("abstract", "")
            assigned = get_assigned_tags(dataset_dict, pmid, stage, candidate)
            
            if "baseline" in filepath:
                msgs = build_baseline_msg(abstract, assigned, candidate, manual_text)
            elif "statement" in filepath:
                pro_a = r.get("pro_first", True)
                arg1 = r["pro_argument"] if pro_a else r["con_argument"]
                arg2 = r["con_argument"] if pro_a else r["pro_argument"]
                msgs = build_statement_msg(abstract, assigned, candidate, arg1, arg2, manual_text)
            elif "interactive" in filepath:
                msgs = build_interactive_msg(abstract, assigned, candidate, r["a_turn1"], r["b_turn1"], r["a_turn2"], manual_text)
            
            print(f" -> Fixing PMID {pmid} ({stage})...")
            
            prediction = "Unknown"
            raw_response = ""
            for attempt in range(10):
                temp = 0.3 + (attempt * 0.1) 
                text_input = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
                model_inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
                
                out_ids = model.generate(**model_inputs, max_new_tokens=512, temperature=temp, do_sample=True, pad_token_id=tokenizer.eos_token_id)
                raw_response = tokenizer.batch_decode([out_ids[0][len(model_inputs.input_ids[0]):]], skip_special_tokens=True)[0].strip()
                
                prediction = extract_pydantic(raw_response)
                if prediction != "Unknown":
                    break
                print(f"    [Retry {attempt+1}/10] Still Unknown. Increasing temp to {temp:.1f}...")

            r["model_prediction"] = prediction
            r["is_correct"] = (prediction == r["ground_truth"])
            r["judge_output"] = raw_response
            unknowns_fixed += 1
            
            status_icon = '✅' if r["is_correct"] else '❌'
            print(f"    [SUCCESS] New Prediction: {prediction:3s} | Target: {r['ground_truth']:3s} -> {status_icon}")

            # Atomically save after every single fix
            total_evals = len(results)
            data["metadata"]["overall_accuracy"] = (sum(1 for res in results if res["is_correct"]) / total_evals) * 100 if total_evals > 0 else 0
            save_results_atomically(filepath, data)

    print(f"Finished {filepath}. Successfully fixed {unknowns_fixed} Unknowns.")

if __name__ == "__main__":
    main()
