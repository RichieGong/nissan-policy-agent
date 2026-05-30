import hashlib
import requests
from playwright.sync_api import sync_playwright
from supabase import create_client
import google.generativeai as genai
import os

from sources import SOURCES, KEYWORDS
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# =========================
# CONFIG
# =========================

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"]
)

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# =========================
# SCRAPER
# =========================

def fetch_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        text = page.locator("body").inner_text()
        browser.close()
        return text

# =========================
# FILTER
# =========================

def is_relevant(text: str) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in KEYWORDS)

# =========================
# HASH
# =========================

def hash_text(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

# =========================
# STATE CHECK
# =========================

def has_changed(url: str, new_hash: str) -> bool:
    res = supabase.from_("page_state").select("*").eq("url", url).execute()

    if not res.data:
        supabase.from_("page_state").insert({
            "url": url,
            "hash": new_hash
        }).execute()
        return True

    old_hash = res.data[0]["hash"]

    if old_hash != new_hash:
        supabase.from_("page_state").update({
            "hash": new_hash
        }).eq("url", url).execute()
        return True

    return False

# =========================
# GEMINI ANALYSIS
# =========================

def analyze(text: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}"

    prompt = f"""
Return JSON only:
topic, impact_type, author, summary, affected_keywords

TEXT:
{text}
"""

    res = requests.post(url, json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    })

    return res.json()["candidates"][0]["content"]["parts"][0]["text"]

# =========================
# PIPELINE
# =========================

def run():
    for source in SOURCES:
        print("Checking:", source["name"])

        text = fetch_text(source["url"])

        if not is_relevant(text):
            continue

        h = hash_text(text)

        if has_changed(source["url"], h):
            insight = analyze(text)

            supabase.from_("policy_updates").insert({
                "topic": source["name"],
                "impact_type": "Trend",
                "author": "System",
                "summary": insight,
                "raw_diff": text[:2000]
            }).execute()

            print("Updated:", source["name"])
        else:
            print("No change")

if __name__ == "__main__":
    run()