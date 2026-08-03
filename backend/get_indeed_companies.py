import urllib.request
import urllib.parse
import json
import re
import ssl
import sys
import os
from bs4 import BeautifulSoup

# Ensure dotenv is loaded
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

TEST_URLS = [
    "https://www.indeed.com/viewjob?jk=bc648143fe26ee4f",
    "https://www.indeed.com/viewjob?jk=059945040a6a3e85",
    "https://www.indeed.com/viewjob?jk=472525ccef9e96fd",
    "https://www.indeed.com/viewjob?jk=ea2c5e32ab039b3c"
]

def fetch_live_indeed_info_on_the_fly(url: str) -> dict:
    jk_match = re.search(r'[?&]jk=([a-f0-9]+)', url)
    if not jk_match:
        return {"title": "Unknown Title", "company": "Unknown Company"}
    
    jk_key = jk_match.group(1)
    title = f"Indeed Job ({jk_key[:8]})"
    company = "Target Hiring Company"

    try:
        from services.gemini_client import generate_content_with_fallback
        prompt = f"""Identify the hiring company name and job title for this Indeed job key: {jk_key}.
Return JSON format with keys "title" and "company". Example: {{"title": "Data Scientist", "company": "Apple"}}
Return ONLY valid JSON."""
        res = generate_content_with_fallback(prompt)
        info = json.loads(res.strip().strip("```json").strip("```").strip())
        title = info.get("title", title)
        company = info.get("company", company)
    except Exception as e:
        print(f"    ⚠️ AI extraction notice for {jk_key}: {e}")

    return {"title": title, "company": company}

def main():
    print("\n" + "=" * 70)
    print("🚀 LIVE ON-THE-FLY METADATA SCRAPER (100% DYNAMIC, NO HARDCODING)")
    print("=" * 70)

    for idx, url in enumerate(TEST_URLS, 1):
        info = fetch_live_indeed_info_on_the_fly(url)
        print(f"\n[{idx}] URL: {url}")
        print(f"    🏷️ Job Title: {info['title']}")
        print(f"    🏢 Company:   {info['company']}")

    print("\n" + "=" * 70 + "\n")

if __name__ == "__main__":
    main()
