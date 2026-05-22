import random
import time
import json
from Bio import Entrez

# --- CONFIGURATION ---
# NCBI requires you to identify yourself. Replace with your actual email!
Entrez.email = "s27erahn@uni-bonn.de" 

# How many articles we want in the end
TARGET_ARTICLE_COUNT = 1000 
# We fetch a larger pool first so we can randomly sample from it
POOL_SIZE = 10000 

def main():
    print("Step 1: Searching for articles published after Jan 1st, 2026...")
    
    # The search query: 
    # 1. Date range: Jan 1 2026 to present
    # 2. Must have an abstract
    # 3. Must have MeSH (Medical Subject Headings) tags assigned
    search_query = '("2025/01/01"[Date - Create] : "3000"[Date - Create]) AND hasabstract AND medline[sb]'
    
    # Execute the search to get the IDs
    search_handle = Entrez.esearch(db="pubmed", term=search_query, retmax=POOL_SIZE)
    search_results = Entrez.read(search_handle)
    search_handle.close()
    
    id_list = search_results["IdList"]
    print(f"Found {len(id_list)} matching articles. Randomly selecting {TARGET_ARTICLE_COUNT}...")
    
    # Make sure we don't try to sample more articles than exist
    sample_size = min(TARGET_ARTICLE_COUNT, len(id_list))
    selected_ids = random.sample(id_list, sample_size)
    
    print("Step 2: Downloading abstracts and MeSH tags (this may take a few minutes)...")
    
    dataset =[]
    batch_size = 100 # We download in batches of 100 so we don't overload the server
    
    for i in range(0, len(selected_ids), batch_size):
        batch_ids = selected_ids[i:i + batch_size]
        print(f"  Downloading batch {i // batch_size + 1}...")
        
        # Fetch the detailed XML data for this batch of IDs
        fetch_handle = Entrez.efetch(db="pubmed", id=batch_ids, retmode="xml")
        records = Entrez.read(fetch_handle)
        fetch_handle.close()
        
        # Parse the records
        for article in records['PubmedArticle']:
            medline_citation = article['MedlineCitation']
            article_data = medline_citation['Article']
            
            # 1. Get the PubMed ID
            pmid = str(medline_citation['PMID'])
            
            # 2. Get the Title
            title = str(article_data.get('ArticleTitle', 'No Title'))
            
            # 3. Get the Abstract
            # Abstracts are sometimes split into sections (Background, Methods, etc.), so we join them into one string
            abstract_list = article_data.get('Abstract', {}).get('AbstractText', [])
            abstract = " ".join([str(text) for text in abstract_list])
            
            # 4. Get the MeSH Tags
            mesh_list = medline_citation.get('MeshHeadingList', [])
            mesh_tags =[]
            for mesh_heading in mesh_list:
                # We just want the name of the tag, not the sub-qualifiers
                tag_name = str(mesh_heading['DescriptorName'])
                mesh_tags.append(tag_name)
            
            # Only save articles that successfully parsed both an abstract and tags
            if abstract and mesh_tags:
                dataset.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "mesh_tags": mesh_tags
                })
        
        # Be polite to the NCBI servers by pausing for 1 second between batches
        time.sleep(1)

    print(f"Step 3: Saving {len(dataset)} articles to JSON file...")
    
    # Save to a well-parsable JSON file
    output_filename = "pubmed_xmlc_dataset.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
        
    print(f"Done! Data saved to {output_filename}")

if __name__ == "__main__":
    main()
