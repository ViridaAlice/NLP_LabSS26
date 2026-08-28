import json
import random
import time
from Bio import Entrez

# --- CONFIGURATION ---
Entrez.email = "your.email@uni-bonn.de"

# A list of generic MeSH tags that provide no specific scientific context.
# We want to avoid searching for these, and avoid picking them as distractors.
GENERIC_TAGS = {
    "Humans", "Male", "Female", "Adult", "Middle Aged", "Aged", "Animals", 
    "Adolescent", "Child", "Infant", "Pregnancy", "Young Adult", "Aged, 80 and over", 
    "Child, Preschool", "Infant, Newborn", "United States", "Australia", "Europe", 
    "Asia", "Africa", "Time Factors", "Risk Factors", "Models, Theoretical"
}

def get_connected_incorrect_tag(correct_tags):
    """
    Finds a highly related but incorrect tag by searching for the most specific 
    correct tags and harvesting peer tags from the exact same scientific niche.
    """
    # 1. Filter out generic tags to find the "Meat" of the paper
    meaningful_tags =[tag for tag in correct_tags if tag not in GENERIC_TAGS]
    
    # If a paper ONLY has generic tags (very rare), fall back to the generic list
    tags_to_sample_from = meaningful_tags if meaningful_tags else correct_tags
    
    # Try up to 3 meaningful tags
    tags_to_try = random.sample(tags_to_sample_from, min(3, len(tags_to_sample_from)))
    
    for exact_tag in tags_to_try:
        print(f"    * Searching niche for: '{exact_tag}'...")
        
        try:
            # 2. Search PUBMED using the EXACT full tag to ensure high relevance
            search_query = f'"{exact_tag}"[MeSH Terms] AND medline[sb]'
            search_handle = Entrez.esearch(db="pubmed", term=search_query, retmax=10)
            search_results = Entrez.read(search_handle)
            search_handle.close()
            time.sleep(0.35) # Polite API pause
            
            id_list = search_results.get("IdList",[])
            if not id_list:
                print(f"    * Result: No related papers found. Trying next...")
                continue
                
            # 3. Fetch the related articles from this specific scientific niche
            fetch_handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
            records = Entrez.read(fetch_handle)
            fetch_handle.close()
            time.sleep(0.35) # Polite API pause
            
            # 4. Harvest tags from these highly related papers
            candidates =[]
            for article in records.get('PubmedArticle', []):
                mesh_list = article['MedlineCitation'].get('MeshHeadingList', [])
                for mesh_heading in mesh_list:
                    candidates.append(str(mesh_heading['DescriptorName']))
            
            unique_candidates = list(set(candidates))
            
            # 5. Filter out original correct tags AND generic stoplist tags
            valid_candidates =[
                tag for tag in unique_candidates 
                if tag not in correct_tags and tag not in GENERIC_TAGS
            ]
            
            # 6. Pick a random, highly contextual distractor!
            if valid_candidates:
                chosen_tag = random.choice(valid_candidates)
                print(f"    * Result: Harvested {len(valid_candidates)} specific peer tags.")
                print(f"    * Selected 'Similar' Negative Tag -> '{chosen_tag}'")
                return chosen_tag
            else:
                print(f"    * Result: All harvested tags were generic or already present. Trying next...")
                
        except Exception as e:
            print(f"    * API Error encountered: {e}. Trying next...")
            pass
            
    # Fallback if the API fails entirely for this article
    fallbacks = ["Neoplasms", "Cardiovascular Diseases", "Bacterial Infections", "Metabolic Diseases"]
    valid_fallbacks = [t for t in fallbacks if t not in correct_tags]
    chosen_fallback = random.choice(valid_fallbacks)
    print(f"    * Exhausted searches. Using Fallback Tag -> '{chosen_fallback}'")
    return chosen_fallback

def main():
    # Load the file you generated in the previous step
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
    print("Starting targeted adversarial tag generation...")
    print("======================================================\n")
    
    for i, article in enumerate(dataset):
        pmid = article.get("pmid", "Unknown")
        print(f"[{i + 1} / {total_articles}] Processing PMID: {pmid}")
            
        correct_tags = article.get("mesh_tags",[])
        
        if not correct_tags:
            print("    * Warning: No correct tags found. Skipping.")
            article["similar_negative_test_tag"] = "Unknown"
            print("-" * 50)
            continue
            
        # Fetch the highly contextual negative tag
        similar_incorrect_tag = get_connected_incorrect_tag(correct_tags)
        
        # Append as the new key you requested
        article["similar_negative_test_tag"] = similar_incorrect_tag
        print("-" * 50) 
        
    print(f"\nSaving updated dataset with contextual tags to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
        
    print("Done! The new tags are saved under 'similar_negative_test_tag'.")

if __name__ == "__main__":
    main()
