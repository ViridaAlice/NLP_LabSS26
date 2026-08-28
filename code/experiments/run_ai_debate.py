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

JUDGE_MODEL_ID = "./Qwen2.5-0.5B-Instruct"  
DEBATER_MODEL_ID = "./Qwen2.5-3B-Instruct"  
DATASET_PATH = "pubmed_xmlc_dataset.json" 
MANUAL_PATH = "NLM_Indexing_manual.txt"
BASE_OUTPUT_PATH = "debate_experiment_results"

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

# ----------------- PROMPT BUILDERS -----------------
def build_debater_messages(abstract, assigned_tags, candidate_tag, side, manual_text):
    """Side is either 'PRO' or 'CON'"""
    system_prompt = (
        f"You are an expert medical debater. Your goal is to persuade the judge that the "
        f"candidate Medical Subject Heading (MeSH) tag {'BELONGS' if side == 'PRO' else 'DOES NOT BELONG'} "
        f"to the provided biomedical abstract.\n"
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

Write your argument {'supporting' if side == 'PRO' else 'opposing'} the assignment of this tag."""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def build_judge_messages(abstract, assigned_tags, candidate_tag, arg1, arg2, manual_text):
    system_prompt = (
        "You are an expert judge in a debate. You will be shown an abstract, a set of already assigned tags, "
        "a candidate MeSH tag, and two arguments from expert debaters (Debater A and Debater B) arguing opposing sides.\n"
        "To guide you, you are provided with excerpts from the NLM Indexing Manual.\n"
        "Your objective is to choose whether the candidate tag belongs to the article (Yes) or not (No) based on the arguments.\n"
        "Structure your output as follows:\n"
        "<thinking>[THINKING]</thinking>\n"
        "Answer: [Yes|No]\n"
        "Focus on strictly formatting your final answer on the last line."
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

Think step by step to determine which debater is correct. Put your reasoning inside <thinking></thinking> tags. Then, on a new line, give your final answer formatted exactly as "Answer: Yes" or "Answer: No"."""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

# ----------------- PARSER & INFERENCE -----------------
def parse_output(generation_text, pmid, stage_name, verbose=False):
    cleaned_text = generation_text.strip()
    if verbose:
        print(f"\n      [JUDGE OUTPUT for PMID {pmid}]:\n{cleaned_text}\n")
    
    match = re.search(r"Answer:\s*(Yes|No)", cleaned_text, re.IGNORECASE)
    if match: return match.group(1).capitalize()
        
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

def generate_text(messages, model, tokenizer, max_tokens=256):
    text_input = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
    generated_ids = model.generate(
        **model_inputs, max_new_tokens=max_tokens, temperature=0.2, do_sample=True, pad_token_id=tokenizer.eos_token_id
    )
    generated_ids = [output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)]
    return tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

# ----------------- MAIN LOGIC -----------------
def main():
    args = parse_args()
    
    # Give each chunk a UNIQUE random seed so pro_first distributions are balanced across the whole dataset
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
    
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                results = saved_data.get("results", [])
                for r in results: completed_evals.add((r["stage"], r["pmid"]))
        except json.JSONDecodeError: pass

    # Load 3B Debater Model
    print(f"\nLoading Debater Model ({DEBATER_MODEL_ID})...")
    debater_tokenizer = AutoTokenizer.from_pretrained(DEBATER_MODEL_ID)
    debater_model = AutoModelForCausalLM.from_pretrained(DEBATER_MODEL_ID, torch_dtype=torch.float16, device_map="cuda")
    
    # Load 0.5B Judge Model
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

            # Stage Assignment
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

            # 1. Debater PRO generates argument
            pro_msgs = build_debater_messages(abstract, assigned_tags, candidate_tag, side="PRO", manual_text=manual_text)
            pro_arg = generate_text(pro_msgs, debater_model, debater_tokenizer, max_tokens=256)

            # 2. Debater CON generates argument
            con_msgs = build_debater_messages(abstract, assigned_tags, candidate_tag, side="CON", manual_text=manual_text)
            con_arg = generate_text(con_msgs, debater_model, debater_tokenizer, max_tokens=256)

            # 3. Randomize Presentation Order (To prevent positional bias!)
            pro_is_first = random.choice([True, False])
            if pro_is_first:
                arg1, arg2 = pro_arg, con_arg
            else:
                arg1, arg2 = con_arg, pro_arg

            # 4. Judge generates verdict
            judge_msgs = build_judge_messages(abstract, assigned_tags, candidate_tag, arg1, arg2, manual_text=manual_text)
            judge_output = generate_text(judge_msgs, judge_model, judge_tokenizer, max_tokens=512)

            # 5. Parse and Record
            prediction = parse_output(judge_output, pmid, stage_name, verbose=args.verbose)
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

            # Incremental Save
            total_evals = len(results)
            total_correct = sum(1 for r in results if r["is_correct"])
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump({"metadata": {"overall_accuracy": (total_correct / total_evals) * 100}, "results": results}, f, indent=4)

    print(f"\nCHUNK {args.chunk_id} EXPERIMENT COMPLETE\n")

if __name__ == "__main__":
    main()
