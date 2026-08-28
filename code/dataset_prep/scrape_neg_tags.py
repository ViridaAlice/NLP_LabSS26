import json
import random
import time
from Bio import Entrez

# --- CONFIGURATION ---
# NCBI requires you to identify yourself. Replace with your actual email!
Entrez.email = "your.email@uni-bonn.de"

def get_similar_incorrect_tag(correct_tags, article_num):
    """
    Finds a highly related but incorrect tag by searching for other 
    PubMed articles on the same topic and 'stealing' their MeSH tags.
    """
    fallbacks =[
        "Neoplasms", "Cardiovascular Diseases", "Bacterial Infections", 
        "Wounds and Injuries", "Nervous System Diseases", "Metabolic Diseases"
    ]
    
    tags_to_try = random.sample(correct_tags, min(3, len(correct_tags)))
    
    for base_tag in tags_to_try:
        search_word = base_tag.replace(",", "").split()[0]
        
        print(f"    * Searching for other papers related to: '{search_word}'...")
        
        try:
            # 1. Search PUBMED (not mesh) for other articles mentioning this concept
            search_query = f"{search_word}[MeSH Terms] AND medline[sb]"
            search_handle = Entrez.esearch(db="pubmed", term=search_query, retmax=5)
            search_results = Entrez.read(search_handle)
            search_handle.close()
            time.sleep(0.35) 
            
            id_list = search_results.get("IdList",[])
            if not id_list:
                print(f"    * Result: No related papers found. Trying next...")
                continue
                
            # 2. Fetch those related articles to look at their tags
            fetch_handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
            records = Entrez.read(fetch_handle)
            fetch_handle.close()
            time.sleep(0.35) 
            
            # 3. Harvest all the tags from these related papers
            candidates = []
            for article in records.get('PubmedArticle', []):
                mesh_list = article['MedlineCitation'].get('MeshHeadingList', [])
                for mesh_heading in mesh_list:
                    candidates.append(str(mesh_heading['DescriptorName']))
            
            # Remove duplicates from our harvested list
            unique_candidates = list(set(candidates))
            
            # 4. Filter out any tags that our original article already has
            incorrect_candidates =[tag for tag in unique_candidates if tag not in correct_tags]
            
            # 5. Pick a random distractor tag!
            if incorrect_candidates:
                chosen_tag = random.choice(incorrect_candidates)
                print(f"    * Result: Harvested {len(unique_candidates)} unique tags from related papers.")
                print(f"    * Selected Negative Tag -> '{chosen_tag}'")
                return chosen_tag
            else:
                print(f"    * Result: All harvested tags already belong to this article. Trying next...")
                
        except Exception as e:
            print(f"    * API Error encountered: {e}. Trying next...")
            pass
            
    # If all searches fail, pick a generic fallback tag
    valid_fallbacks =[t for t in fallbacks if t not in correct_tags]
    chosen_fallback = random.choice(valid_fallbacks)
    print(f"    * Exhausted API searches. Using Fallback Tag -> '{chosen_fallback}'")
    return chosen_fallback

def main():
    input_file = "pubmed_xmlc_dataset.json"
    output_file = "pubmed_xmlc_dataset_final.json"
    
    print("======================================================")
    print(f"Loading data from {input_file}...")
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {input_file}.")
        return

    total_articles = len(dataset)
    print(f"Successfully loaded {total_articles} articles.")
    print("Starting adversarial tag generation (Literature Co-occurrence)...")
    print("======================================================\n")
    
    for i, article in enumerate(dataset):
        pmid = article.get("pmid", "Unknown")
        print(f"[{i + 1} / {total_articles}] Processing PMID: {pmid}")
            
        correct_tags = article.get("mesh_tags",[])
        
        if not correct_tags:
            print("    * Warning: No correct tags found for this article. Skipping.")
            article["negative_test_tag"] = "Unknown"
            print("-" * 50)
            continue
            
        incorrect_tag = get_similar_incorrect_tag(correct_tags, i + 1)
        article["negative_test_tag"] = incorrect_tag
        print("-" * 50) 
        
    print(f"\nSaving final, updated dataset to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
        
    print("Done! Your dataset is now fully prepared for the AI Debate experiments.")

if __name__ == "__main__":
    main()
