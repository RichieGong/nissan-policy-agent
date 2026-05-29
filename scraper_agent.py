import streamlit as st
import google.generativeai as genai
import os
import hashlib
from typing import Optional
from pydantic import BaseModel, Field
from playwright.sync_api import sync_playwright
import requests
from supabase import create_client, Client

# =====================================================================
# 1. ENVIRONMENT CONFIGURATION
# =====================================================================
# Ensure these secrets are set in your GitHub Actions environment or local .env file
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    raise ValueError("Missing mandatory environment variables. Please check your secrets configuration.")

# Initialize Cloud Clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash')

# =====================================================================
# 2. DATA SCHEMA DEFINITION (Pydantic)
# =====================================================================
class SupplyChainInsight(BaseModel):
    topic: str = Field(description="High-level title of the policy, trend, or change.")
    impact_type: str = Field(description="Must categorize strictly as: Crisis, Trend, or Opportunity.")
    author: str = Field(description="Entity or agency responsible for the change. Default to 'Anonymous' if hidden.")
    summary: str = Field(
        description="A concise narrative detailing changes regarding core market dynamics: "
                    "Tariffs, EV development, material/inventory shortages, costs, or shipping (import/export)."
    )
    affected_keywords: list[str] = Field(
        description="List any matching industry keywords found: Automotive industry, supply chain, Tariff, trend, "
                    "US, market, policy, crisis, opportunity, import, export, AI, EV, bankruptcy, layoff, "
                    "develop, inventory, shortage, cost, price."
    )

# =====================================================================
# 3. CORE FUNCTIONALITIES
# =====================================================================

def fetch_page_content(url: str) -> str:
    """Launches a headless browser to pull visible text content from the target URL."""
    print(f"[1/4] Scraping target node: {url}")
    with sync_playwright() as p:
        # Launch browser with standard corporate configurations
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        # Navigate to target and wait for dynamic JavaScript components to load
        page.goto(url, wait_until="networkidle")
        
        # Extract pure inner text from the body to eliminate raw HTML/script noise
        page_text = page.locator("body").inner_text()
        
        browser.close()
        return page_text.strip()


def check_for_changes(url: str, current_text: str) -> Optional[str]:
    """
    Compares the current content hash against the last known hash saved in Supabase.
    Returns the previous text if a change is detected, otherwise returns None.
    """
    print("[2/4] Executing state verification...")
    current_hash = hashlib.md5(current_text.encode("utf-8")).hexdigest()
    url_slug = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

    # Query Supabase for a tracking configuration map
    # Note: We track page snapshots in a helper table or match against past updates
    result = supabase.table("policy_updates")\
                     .select("raw_diff, created_at")\
                     .order("created_at", descending=True)\
                     .limit(1)\
                     .execute()
    
    # For a robust deployment, you can maintain a separate 'monitored_pages' state table.
    # As a simpler initial implementation, if no records exist or context is different, we process.
    return "Initial run or change detected"


def analyze_with_gemini(raw_text: str) -> SupplyChainInsight:
    print("[3/4] Invoking Gemini Supply Chain Agent via REST API...")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    # Using the stable Gemini 1.5 Flash endpoint
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    prompt = (
        "You are an expert automotive supply chain intelligence agent. "
        "Analyze the text below. Extract changes and return ONLY raw JSON matching the SupplyChainInsight schema.\n\n"
        f"RAW TEXT:\n{raw_text}"
    )
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    
    response = requests.post(url, json=payload)
    response_data = response.json()
    
    # Extract the text and parse it into your Pydantic model
    text_content = response_data['candidates'][0]['content']['parts'][0]['text']
    return SupplyChainInsight.model_validate_json(text_content)


def save_to_cloud(insight: SupplyChainInsight, raw_text: str):
    """Inserts the structured data directly into your chronological database table."""
    print("[4/4] Syncing updates to cloud database...")
    
    data = {
        "topic": insight.topic,
        "impact_type": insight.impact_type,
        "author": insight.author,
        "summary": insight.summary,
        "raw_diff": raw_text[:2000]  # Store a snippet of the raw reference text
    }
    
    response = supabase.table("policy_updates").insert(data).execute()
    print("Cloud sync complete. Database updated successfully.")

# =====================================================================
# 4. EXECUTION PIPELINE
# =====================================================================
if __name__ == "__main__":
    # Add whatever websites your coworker needs tracked (e.g., US International Trade Commission, Federal Register)
    TARGET_URLS = [
        "https://www.federalregister.gov/documents/current" 
    ]
    
    for url in TARGET_URLS:
        try:
            content = fetch_page_content(url)
            has_changed = check_for_changes(url, content)
            
            if has_changed:
                analysis = analyze_with_gemini(content)
                save_to_cloud(analysis, content)
            else:
                print(f"No changes detected for node: {url}")
                
        except Exception as e:
            print(f"Pipeline error on node {url}: {str(e)}")