import hashlib
import streamlit as st
import google.generativeai as genai
from typing import Optional
from pydantic import BaseModel, Field
from playwright.sync_api import sync_playwright
import requests
from supabase import create_client

# =====================================================================
# 1. CONFIG
# =====================================================================

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# =====================================================================
# 2. SCHEMA
# =====================================================================

class SupplyChainInsight(BaseModel):
    topic: str
    impact_type: str
    author: str
    summary: str
    affected_keywords: list[str]

# =====================================================================
# 3. SCRAPER
# =====================================================================

def fetch_page_content(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, wait_until="domcontentloaded")
        content = page.locator("body").inner_text()

        browser.close()
        return content.strip()

# =====================================================================
# 4. CHANGE DETECTION (FIXED)
# =====================================================================

def check_for_changes(url: str, current_text: str) -> bool:
    """
    Proper hash-based change detection using Supabase storage.
    """

    current_hash = hashlib.md5(current_text.encode("utf-8")).hexdigest()

    # Create a simple tracking table approach (no broken ordering queries)
    result = (
        supabase
        .from_("page_state")
        .select("*")
        .eq("url", url)
        .execute()
    )

    data = result.data

    if not data:
        # first run → insert state
        supabase.from_("page_state").insert({
            "url": url,
            "hash": current_hash
        }).execute()
        return True

    last_hash = data[0]["hash"]

    if last_hash != current_hash:
        supabase.from_("page_state").update({
            "hash": current_hash
        }).eq("url", url).execute()
        return True

    return False

# =====================================================================
# 5. GEMINI ANALYSIS (FIXED ENV + SAFE PARSING)
# =====================================================================

def analyze_with_gemini(raw_text: str) -> SupplyChainInsight:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-1.5-flash:generateContent"
        f"?key={GEMINI_API_KEY}"
    )

    prompt = f"""
You are a supply chain intelligence system.

Return ONLY valid JSON matching this schema:
topic, impact_type, author, summary, affected_keywords

TEXT:
{raw_text}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    response = requests.post(url, json=payload)
    response.raise_for_status()

    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]

    return SupplyChainInsight.model_validate_json(text)

# =====================================================================
# 6. SAVE TO SUPABASE (FIXED .from_)
# =====================================================================

def save_to_cloud(insight: SupplyChainInsight, raw_text: str):
    supabase.from_("policy_updates").insert({
        "topic": insight.topic,
        "impact_type": insight.impact_type,
        "author": insight.author,
        "summary": insight.summary,
        "raw_diff": raw_text[:2000]
    }).execute()

# =====================================================================
# 7. PIPELINE
# =====================================================================

if __name__ == "__main__":

    TARGET_URLS = [
        "https://www.federalregister.gov/documents/current"
    ]

    for url in TARGET_URLS:
        try:
            content = fetch_page_content(url)

            if check_for_changes(url, content):
                insight = analyze_with_gemini(content)
                save_to_cloud(insight, content)
                print(f"Updated: {url}")
            else:
                print(f"No change: {url}")

        except Exception as e:
            print(f"Error on {url}: {str(e)}")