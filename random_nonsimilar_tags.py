import json
import random
import time
import re
from Bio import Entrez

# --- CONFIGURATION ---
Entrez.email = "s27erahn@uni-bonn.de"

# Technical seed domains from non-medical branches
ALIEN_DOMAINS = [
    "Aerospace Engineering", "Quantum Theory", "Social Media", 
    "Acoustics", "Artificial Intelligence", "Nuclear Physics",
    "Architecture", "Library Science", "Automobile Driving",
    "Robotics", "Forensic Anthropology", "Information Technology",
    "Music Theory", "Agriculture", "Philosophy of Science"
]

# Blacklist of generic metadata and historical tags
GENERIC_OR_HISTORICAL_PATTERNS = [
    r"history", r"century", r"ancient", r"medieval", r"modern", 
    r"humans", r"male", r"female", r"animals", r"adult", 
    r"united states", r"time factors", r"risk factors", 
    r"aged", r"infant", r"child", r"pregnancy"
]

def is_valid_jargon(tag):
    """
    Checks if a tag is a specific technical concept and NOT historical metadata.
    """
    # 1. Reject if too short (usually generic)
    if len(tag) < 5:
        return False
    
    # 2. Reject if it matches any blacklisted patterns (case insensitive)
    tag_lower = tag.lower()
    for pattern in GENERIC_OR_HISTORICAL_PATTERNS:
        if re.search(pattern, tag_lower):
            return False
            
    return True

def get_unrelated_jargon_tag(correct_tags):
    """
    Finds a highly specific technical tag from an unrelated branch.
    Sorts by string length to find complex 'leaf' concepts.
    """
    random.shuffle(ALIEN_DOMAINS)
    
    for domain in ALIEN_DOMAINS:
        try:
            # 1. Search PubMed for articles about this alien topic
            search_query = f'"{domain}"[MeSH Terms] AND medline[sb]'
            search_handle = Entrez.esearch(db="pubmed", term=search_query, retmax=10)
            res = Entrez.read(search_handle)
            search_handle.close()
            time.sleep(0.3)
            
            id_list = res.get("IdList", [])
            if not id_list:
                continue
                
            # 2. Fetch those articles
            fetch_handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
            records = Entrez.read(fetch_handle)
            fetch_handle.close()
            time.sleep(0.3)
            
            # 3. Harvest tags
            harvested_tags = set()
            for article in records.get('PubmedArticle', []):
                mesh_list = article['MedlineCitation'].get('MeshHeadingList', [])
                for mh in mesh_list:
                    harvested_tags.add(str(mh['DescriptorName']))
                    
            # 4. Filter: Must be unrelated, not generic, and NOT historical
            valid_candidates = [
                tag for tag in harvested_tags 
                if tag not in correct_tags and is_valid_jargon(tag) and tag != domain
            ]
            
            if valid_candidates:
                # 5. Sort by length (Longest = Most specific Leaf Node)
                valid_candidates.sort(key=len, reverse=True)
                
                # Pick from top 3 to keep it specific
                chosen_tag = random.choice(valid_candidates[:3])
                
                print(f"    * Result: Found {len(valid_candidates)} technical leaf nodes.")
                print(f"    * Success! Selected Unrelated Jargon -> '{chosen_tag}'")
                return chosen_tag
                
        except Exception as e:
            continue
            
    return "Microscopy, Acoustic" # Final technical fallback

def main():
    input_file = "pubmed_xmlc_dataset.json"
    output_file = "pubmed_xmlc_dataset_v2.json"
    
    print("======================================================")
    print("STARTING TECHNICAL LEAF-NODE GENERATION")
    print(" (Historical & Generic Tags Explicitly Excluded)")
    print("======================================================")

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
        return

    total = len(dataset)
    for i, article in enumerate(dataset):
        pmid = article.get("pmid", "???")
        print(f"\n[{i + 1} / {total}] Processing PMID: {pmid}")
        
        # Get jargon from unrelated technical fields
        unrelated_tag = get_unrelated_jargon_tag(article.get("mesh_tags", []))
        
        article["unrelated_negative_test_tag"] = unrelated_tag
        
        # Periodic Save
        if (i + 1) % 20 == 0:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(dataset, f, indent=4, ensure_ascii=False)
            print(f"    >> Progress checkpoint saved.")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
    print("\nDONE! Dataset v3 saved with technical, non-historical unrelated tags.")

if __name__ == "__main__":
    main()
