import json
import random
import re
import torch
import os
import sys
import argparse
import tempfile
from transformers import AutoModelForCausalLM, AutoTokenizer

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================
HF_TOKEN = os.environ.get("HF_TOKEN")
JUDGE_MODEL_ID = "./Qwen3.5-0.8B"  
DEBATER_MODEL_ID = "./Qwen3.5-2B"  
DATASET_PATH = "pubmed_xmlc_dataset.json" 
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "statement_results"

# ==============================================================================

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_mode", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--chunk_id", type=int, default=0)
    parser.add_argument("--total_chunks", type=int, default=1)
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

def build_debater_messages(abstract, assigned_tags, candidate_tag, side, manual_text):
    system_prompt = (
        f"You are an expert medical debater participating in a competitive game. Your goal is to fiercely persuade the judge that the "
        f"candidate Medical Subject Heading (MeSH) tag {'BELONGS' if side == 'PRO' else 'DOES NOT BELONG'} "
        f"to the provided biomedical abstract.\n"
        f"CRITICAL RULE: You MUST NEVER concede to the opposing side or admit weakness, even if you secretly believe your assigned position is incorrect. "
        f"Always confidently defend your assigned position using the text provided.\n"
        f"To guide you, you are provided with excerpts from the NLM Indexing Manual.\n"
        f"Maintain a scholarly, assertive tone focused on evidence-based analysis.\n"
        f"Be concise. Your argument must be under 150 words."
    )
    user_prompt = f"""Here is the NLM Indexing manual for your reference:
<indexing_manual>
{manual_text}
</indexing_manual>

Abstract:
{abstract}

Already Assigned Tags:
{', '.join(assigned_tags)}

Candidate Tag: {candidate_tag}

Write your argument confidently {'supporting' if side == 'PRO' else 'opposing'} the assignment of this tag."""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def build_judge_messages(abstract, assigned_tags, candidate_tag, arg1, arg2, manual_text):
    system_prompt = (
        "You are an impartial expert judge in a medical debate. You will be shown an abstract, a set of already assigned tags, "
        "a candidate MeSH tag, and two arguments from expert debaters (Debater A and Debater B) arguing opposing sides.\n"
        "To guide you, you are provided with excerpts from the NLM Indexing Manual.\n"
        "Your objective is to evaluate both arguments and choose whether the candidate tag belongs to the article (Yes) or not (No).\n"
        "Do not automatically reject the tag just because there is a disagreement. Evaluate the evidence fairly.\n\n"
        "CRITICAL INSTRUCTION: You MUST think step-by-step FIRST inside <thinking> tags. Only AFTER you finish your reasoning, "
        "output your final decision on the very last line.\n\n"
        "REQUIRED FORMAT:\n"
        "<thinking>\n"
        "1. Strongest point for BELONGS: ...\n"
        "2. Strongest point for DOES NOT BELONG: ...\n"
        "3. My evaluation: ...\n"
        "</thinking>\n"
        "Answer: [Yes/No]"
    )
    user_prompt = f"""Here is the NLM Indexing manual for your reference:
<indexing_manual>
{manual_text}
</indexing_manual>

Abstract:
{abstract}

Already Assigned Tags:
{', '.join(assigned_tags)}

Candidate Tag: {candidate_tag}

Debater A's Argument:
{arg1}

Debater B's Argument:
{arg2}

Based on the abstract and the debate, does the candidate tag belong? Follow the REQUIRED FORMAT exactly."""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

def parse_output(generation_text, pmid, stage_name, verbose=False):
    cleaned_text = generation_text.strip()
    if verbose:
        print(f"\n      [JUDGE OUTPUT for PMID {pmid}]:\n{cleaned_text}\n")
    
    matches = re.findall(r"Answer:\s*(Yes|No)", cleaned_text, re.IGNORECASE)
    if matches: 
        return matches[-1].capitalize()
        
    if "</thinking>" in cleaned_text:
        after_thinking = cleaned_text.split("</thinking>")[-1].strip()
        for word in re.sub(r'[^\w\s]', '', after_thinking).strip().split():
            if word.capitalize() in ["Yes", "No"]: return word.capitalize()

    lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
    if lines:
        if re.search(r"\b(yes)\b", lines[-1], re.IGNORECASE): return "Yes"
        if re.search(r"\b(no)\b", lines[-1], re.IGNORECASE): return "No"

    end_words = re.sub(r'[^\w\s]', '', cleaned_text).strip().split()
    if end_words and end_words[-1].capitalize() in ["Yes", "No"]:
        return end_words[-1].capitalize()
            
    return "Unknown"

def generate_text(messages, model, tokenizer, max_tokens=256, temperature=0.2):
    text_input = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
    generated_ids = model.generate(
        **model_inputs, max_new_tokens=max_tokens, temperature=temperature, do_sample=True, pad_token_id=tokenizer.eos_token_id
    )
    generated_ids = [output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)]
    return tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

def save_results_atomically(file_path, data):
    """Writes data to a temporary file first, then atomically renames it to prevent corruption."""
    dir_name = os.path.dirname(file_path) or "."
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
    try:
        os.replace(temp_name, file_path)
    except Exception as e:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise e

def main():
    args = parse_args()
    random.seed(42 + args.chunk_id)
    
    if not torch.cuda.is_available():
        print("CRITICAL ERROR: PyTorch cannot find a GPU!")
        sys.exit(1)

    dataset, manual_text = load_resources()
    
    if args.total_chunks > 1:
        chunk_size = len(dataset) // args.total_chunks
        start_idx = args.chunk_id * chunk_size
        end_idx = start_idx + chunk_size if args.chunk_id < args.total_chunks - 1 else len(dataset)
        dataset = dataset[start_idx:end_idx]
        output_file = f"{BASE_OUTPUT_PATH}_chunk{args.chunk_id}.json"
        print(f"\n[PARALLEL] Chunk {args.chunk_id} | Articles {start_idx} to {end_idx-1}")
    else:
        output_file = f"{BASE_OUTPUT_PATH}_full.json"
        
    if args.test_mode:
        dataset = dataset[:5]
        output_file = "test_" + output_file
        
    completed_evals = set()
    results = []
    
    # CRASH-PROOF LOAD
    if os.path.exists(output_file):
        print(f"\n[RESUME] Found existing save file at {output_file}.")
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                results = saved_data.get("results", [])
                for r in results: completed_evals.add((r["stage"], r["pmid"]))
            print(f" -> Fast-forwarding {len(results)} previous evaluations.")
        except json.JSONDecodeError: 
            print(" -> [WARNING] Existing file was corrupted. Restarting from scratch.")
            pass

    print(f"\nLoading Debater Model ({DEBATER_MODEL_ID})...")
    debater_tokenizer = AutoTokenizer.from_pretrained(DEBATER_MODEL_ID)
    debater_model = AutoModelForCausalLM.from_pretrained(DEBATER_MODEL_ID, torch_dtype=torch.float16, device_map="cuda")
    
    print(f"Loading Judge Model ({JUDGE_MODEL_ID})...")
    judge_tokenizer = AutoTokenizer.from_pretrained(JUDGE_MODEL_ID)
    judge_model = AutoModelForCausalLM.from_pretrained(JUDGE_MODEL_ID, torch_dtype=torch.float16, device_map="cuda")

    stages = [
        ("Round 1: True Tag", "EVALUATING POSITIVE CASES (Expected: Yes)"),
        ("Round 2: Unrelated Tag", "EVALUATING NEGATIVE CASES (Expected: No)"),
        ("Round 3: Similar Tag", "EVALUATING TRICKY NEGATIVE CASES (Expected: No)")
    ]
    
    for stage_name, stage_desc in stages:
        print("\n" + "="*60 + f"\n{stage_name.upper()}\n" + "="*60)
            
        for i, article in enumerate(dataset):
            pmid = article.get("pmid", "Unknown")
            if (stage_name, pmid) in completed_evals: continue
            
            correct_tags = article.get("mesh_tags", [])
            if not correct_tags: continue

            if stage_name == "Round 1: True Tag":
                candidate_tag = random.choice(correct_tags)
                assigned_tags = [t for t in correct_tags if t != candidate_tag]
                ground_truth = "Yes"
            elif stage_name == "Round 2: Unrelated Tag":
                candidate_tag = article.get("unrelated_negative_test_tag", article.get("negative_test_tag", "Unknown"))
                assigned_tags = correct_tags
                ground_truth = "No"
            elif stage_name == "Round 3: Similar Tag":
                candidate_tag = article.get("similar_negative_test_tag", "Unknown")
                assigned_tags = correct_tags
                ground_truth = "No"

            abstract = article.get("abstract", "")

            pro_msgs = build_debater_messages(abstract, assigned_tags, candidate_tag, side="PRO", manual_text=manual_text)
            pro_arg = generate_text(pro_msgs, debater_model, debater_tokenizer, max_tokens=256)

            con_msgs = build_debater_messages(abstract, assigned_tags, candidate_tag, side="CON", manual_text=manual_text)
            con_arg = generate_text(con_msgs, debater_model, debater_tokenizer, max_tokens=256)

            pro_is_first = random.choice([True, False])
            if pro_is_first:
                arg1, arg2 = pro_arg, con_arg
            else:
                arg1, arg2 = con_arg, pro_arg

            judge_msgs = build_judge_messages(abstract, assigned_tags, candidate_tag, arg1, arg2, manual_text=manual_text)
            
            # Retry Logic for the Judge
            prediction = "Unknown"
            judge_output = ""
            for attempt in range(3):
                temp = 0.2 if attempt == 0 else 0.4
                judge_output = generate_text(judge_msgs, judge_model, judge_tokenizer, max_tokens=512, temperature=temp)
                prediction = parse_output(judge_output, pmid, stage_name, verbose=args.verbose)
                
                if prediction != "Unknown":
                    break
                else:
                    print(f"      -> [RETRY] PMID {pmid} output was Unknown. Retrying (Attempt {attempt+1}/3)...")
            
            is_correct = (prediction == ground_truth)
            
            status_icon = '✅' if is_correct else '❌'
            print(f"[{i+1}/{len(dataset)}] PMID: {pmid} | Target: {ground_truth:3s} | Pred: {prediction:3s} -> {status_icon} (Pro First: {pro_is_first})")

            results.append({
                "pmid": pmid,
                "stage": stage_name,
                "candidate_tag": candidate_tag,
                "ground_truth": ground_truth,
                "pro_first": pro_is_first,
                "pro_argument": pro_arg,
                "con_argument": con_arg,
                "model_prediction": prediction,
                "is_correct": is_correct,
                "judge_output": judge_output
            })
            completed_evals.add((stage_name, pmid))

            # Atomic save on every step
            total_evals = len(results)
            total_correct = sum(1 for r in results if r["is_correct"])
            output_data = {
                "metadata": {
                    "overall_accuracy": (total_correct / total_evals) * 100 if total_evals > 0 else 0
                }, 
                "results": results
            }
            save_results_atomically(output_file, output_data)

    print(f"\nCHUNK {args.chunk_id} EXPERIMENT COMPLETE\n")

if __name__ == "__main__":
    main()
