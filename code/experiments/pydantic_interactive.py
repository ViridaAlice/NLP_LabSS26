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

HF_TOKEN = os.environ.get("HF_TOKEN")
JUDGE_MODEL_ID = "./Qwen3.5-0.8B"   
DEBATER_MODEL_ID = "./Qwen3.5-2B"  
DATASET_PATH = "pubmed_xmlc_dataset.json" 
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "pydantic_interactive_results"  

class JudgeResponse(BaseModel):
    thinking: str = Field(description="Step-by-step reasoning evaluating the debate.")
    answer: str = Field(description="Final decision, strictly 'Yes' or 'No'.")

class DebaterResponse(BaseModel):
    thinking: str = Field(description="Brief internal strategic reasoning.")
    argument: str = Field(description="The final argument presented to the judge, under 150 words.")

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--chunk_id", type=int, default=0)
    parser.add_argument("--total_chunks", type=int, default=1)
    return parser.parse_args()

def load_resources():
    with open(DATASET_PATH, "r", encoding="utf-8") as f: dataset = json.load(f)
    try:
        with open(MANUAL_PATH, "r", encoding="utf-8") as f: manual_text = f.read()
    except FileNotFoundError: manual_text = ""
    return dataset, manual_text

def get_debater_system_prompt(side):
    return (
        f"You are an expert medical debater. Persuade the judge that the tag {'BELONGS' if side == 'PRO' else 'DOES NOT BELONG'}.\n"
        f"CRITICAL RULE: NEVER concede. Always confidently defend your assigned position and critique your opponent.\n"
        f"CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
        "Your JSON MUST contain the 'thinking' key FIRST, and the 'argument' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n"
        "{\n  \"thinking\": \"Brief strategic reasoning.\",\n  \"argument\": \"Your concise argument text (under 150 words).\"\n}"
    )

def build_debater_messages(abstract, assigned_tags, candidate_tag, side, manual_text, previous_turns=""):
    system_prompt = get_debater_system_prompt(side)
    user_prompt = f"Abstract:\n{abstract}\n\nCandidate Tag: {candidate_tag}\n\n{previous_turns}\n\nWrite your argument."
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

def build_judge_messages(abstract, assigned_tags, candidate_tag, arg1, arg2, arg3, manual_text):
    system_prompt = (
        "You are an impartial expert judge in a medical debate evaluating if a candidate tag belongs to an abstract.\n"
        "CRITICAL INSTRUCTION: You MUST output your response as a valid JSON object. "
        "Your JSON MUST contain the 'thinking' key FIRST, and the 'answer' key AT THE VERY END.\n\n"
        "REQUIRED JSON SCHEMA:\n"
        "{\n  \"thinking\": \"1. Evaluate arguments... 2. Final synthesis...\",\n  \"answer\": \"Yes\" or \"No\"\n}"
    )
    user_prompt = f"Abstract:\n{abstract}\nCandidate Tag: {candidate_tag}\n\nDebater A: {arg1}\n\nDebater B: {arg2}\n\nDebater A Rebuttal: {arg3}\n\nDoes the tag belong?"
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

def extract_pydantic(response, schema_class):
    json_text = re.sub(r'```json\s*', '', response, flags=re.IGNORECASE)
    json_text = re.sub(r'```\s*', '', json_text)
    start = json_text.find('{')
    end = json_text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try: return schema_class.model_validate_json(json_text[start:end+1])
        except ValidationError: pass
    return None

def generate_text(messages, model, tokenizer, schema_class, text_field, max_tokens=350, temperature=0.2):
    for attempt in range(3):
        temp = temperature if attempt == 0 else temperature + 0.2
        inputs = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([inputs], return_tensors="pt").to(model.device)
        out_ids = model.generate(**inputs, max_new_tokens=max_tokens, temperature=temp, do_sample=True, pad_token_id=tokenizer.eos_token_id)
        response = tokenizer.batch_decode([out_ids[0][len(inputs.input_ids[0]):]], skip_special_tokens=True)[0].strip()
        
        parsed = extract_pydantic(response, schema_class)
        if parsed: 
            val = getattr(parsed, text_field).strip()
            if text_field == "argument" or val.capitalize() in ["Yes", "No"]:
                return val.capitalize() if text_field == "answer" else val, response
    
    fallback_match = re.findall(rf'"{text_field}"\s*:\s*"(.*?)"', response, re.IGNORECASE | re.DOTALL)
    if fallback_match: return fallback_match[-1].strip().capitalize() if text_field == "answer" else fallback_match[-1].strip(), response
    return "Unknown", response

def save_results_atomically(file_path, data):
    dir_name = os.path.dirname(file_path) or "."
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
    try: os.replace(temp_name, file_path)
    except: 
        if os.path.exists(temp_name): os.remove(temp_name)

def main():
    args = parse_args()
    random.seed(42 + args.chunk_id)
    if not torch.cuda.is_available(): sys.exit("CRITICAL ERROR: No GPU!")

    dataset, manual_text = load_resources()
    
    if args.total_chunks > 1:
        chunk_size = (len(dataset) + args.total_chunks - 1) // args.total_chunks
        start_idx = args.chunk_id * chunk_size
        end_idx = min(start_idx + chunk_size, len(dataset))
        dataset = dataset[start_idx:end_idx]
        output_file = f"{BASE_OUTPUT_PATH}_chunk{args.chunk_id}.json"
    else:
        output_file = f"{BASE_OUTPUT_PATH}_full.json"
        
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file
        
    completed_evals = set()
    results = []
    
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                results = saved_data.get("results", [])
                for r in results: completed_evals.add((r["stage"], r["pmid"]))
        except json.JSONDecodeError: pass

    print(f"\nLoading Debater Model ({DEBATER_MODEL_ID})...")
    deb_tok = AutoTokenizer.from_pretrained(DEBATER_MODEL_ID)
    deb_mod = AutoModelForCausalLM.from_pretrained(DEBATER_MODEL_ID, torch_dtype=torch.float16, device_map="cuda")
    
    print(f"Loading Judge Model ({JUDGE_MODEL_ID})...")
    jud_tok = AutoTokenizer.from_pretrained(JUDGE_MODEL_ID)
    jud_mod = AutoModelForCausalLM.from_pretrained(JUDGE_MODEL_ID, torch_dtype=torch.float16, device_map="cuda")

    stages = [
        ("Round 1: True Tag", "EVALUATING POSITIVE CASES", "Yes"),
        ("Round 2: Unrelated Tag", "EVALUATING NEGATIVE CASES", "No"),
        ("Round 3: Similar Tag", "EVALUATING TRICKY NEGATIVE CASES", "No")
    ]
    
    for stage_name, stage_desc, ground_truth in stages:
        print("\n" + "="*60 + f"\n{stage_name.upper()}\n" + "="*60)
            
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in completed_evals: continue
            
            correct_tags = article.get("mesh_tags", [])
            if not correct_tags: continue

            if ground_truth == "Yes":
                candidate_tag = random.choice(correct_tags)
                assigned_tags = [t for t in correct_tags if t != candidate_tag]
            elif stage_name == "Round 2: Unrelated Tag":
                candidate_tag = article.get("unrelated_negative_test_tag", article.get("negative_test_tag", "Unknown"))
                assigned_tags = correct_tags
            else:
                candidate_tag = article.get("similar_negative_test_tag", "Unknown")
                assigned_tags = correct_tags

            abstract = article.get("abstract", "")
            pro_is_a = random.choice([True, False])
            a_side = "PRO" if pro_is_a else "CON"
            b_side = "CON" if pro_is_a else "PRO"

            msgs_a1 = build_debater_messages(abstract, assigned_tags, candidate_tag, a_side, manual_text, "You are Debater A. Write your opening statement.")
            a_turn1, _ = generate_text(msgs_a1, deb_mod, deb_tok, DebaterResponse, "argument", max_tokens=300)

            prev_b = f"Debater A stated:\n\"{a_turn1}\"\nYou are Debater B. Write your response and critique."
            msgs_b1 = build_debater_messages(abstract, assigned_tags, candidate_tag, b_side, manual_text, prev_b)
            b_turn1, _ = generate_text(msgs_b1, deb_mod, deb_tok, DebaterResponse, "argument", max_tokens=300)

            prev_a = f"Your opening: \"{a_turn1}\"\nDebater B responded: \"{b_turn1}\"\nYou are Debater A. Write your final rebuttal."
            msgs_a2 = build_debater_messages(abstract, assigned_tags, candidate_tag, a_side, manual_text, prev_a)
            a_turn2, _ = generate_text(msgs_a2, deb_mod, deb_tok, DebaterResponse, "argument", max_tokens=300)

            arg1, arg2 = (a_turn1, b_turn1) if pro_is_a else (b_turn1, a_turn1)

            msgs_judge = build_judge_messages(abstract, assigned_tags, candidate_tag, arg1, arg2, a_turn2, manual_text)
            prediction, raw_judge = generate_text(msgs_judge, jud_mod, jud_tok, JudgeResponse, "answer", max_tokens=512)
            
            is_correct = (prediction == ground_truth)
            print(f"[{i+1}/{len(dataset)}] PMID: {pmid} | Target: {ground_truth:3s} | Pred: {prediction:3s} -> {'✅' if is_correct else '❌'}")

            results.append({
                "pmid": pmid, "stage": stage_name, "candidate_tag": candidate_tag, "ground_truth": ground_truth,
                "pro_first": pro_is_a, "a_turn1": a_turn1, "b_turn1": b_turn1, "a_turn2": a_turn2,
                "model_prediction": prediction, "is_correct": is_correct, "judge_output": raw_judge
            })
            completed_evals.add((stage_name, pmid))

            total = len(results)
            save_results_atomically(output_file, {
                "metadata": {"overall_accuracy": (sum(1 for r in results if r["is_correct"]) / total) * 100 if total > 0 else 0}, 
                "results": results
            })

    print(f"\nCHUNK {args.chunk_id} EXPERIMENT COMPLETE\n")

if __name__ == "__main__":
    main()
