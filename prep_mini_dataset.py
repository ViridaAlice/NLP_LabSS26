import json
import random

def main():
    # Load your generated PubMed dataset
    with open("pubmed_xmlc_dataset_final.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Shuffle to ensure randomness
    random.shuffle(data)
    
    positive_cases = []
    negative_cases =[]
    
    for article in data:
        abstract = article.get("abstract", "")
        correct_tags = article.get("mesh_tags",[])
        negative_tag = article.get("similar_negative_test_tag", "Unknown")
        
        # Skip invalid data
        if not abstract or not correct_tags or negative_tag == "Unknown":
            continue
            
        # Build 10 Positive Cases
        if len(positive_cases) < 10:
            target_tag = random.choice(correct_tags)
            positive_cases.append({
                "article": abstract,
                "questions":[{
                    "question": f"Does the MeSH tag '{target_tag}' accurately describe this article?",
                    "options": ["Yes, the tag belongs.", "No, the tag does not belong."],
                    "gold_label": 0  # 0 maps to 'Yes'
                }]
            })
            
        # Build 10 Negative Cases
        elif len(negative_cases) < 10:
            negative_cases.append({
                "article": abstract,
                "questions":[{
                    "question": f"Does the MeSH tag '{negative_tag}' accurately describe this article?",
                    "options":["Yes, the tag belongs.", "No, the tag does not belong."],
                    "gold_label": 1  # 1 maps to 'No'
                }]
            })
            
        if len(positive_cases) == 10 and len(negative_cases) == 10:
            break
            
    # Combine and save as a JSONL (JSON Lines) file, which the repo expects
    combined = positive_cases + negative_cases
    random.shuffle(combined) # Mix positive and negative cases
    
    with open("pubmed_mini_test.jsonl", "w", encoding="utf-8") as f:
        for case in combined:
            f.write(json.dumps(case) + "\n")
            
    print("Created pubmed_mini_test.jsonl with 10 positive and 10 negative cases!")

if __name__ == "__main__":
    main()
