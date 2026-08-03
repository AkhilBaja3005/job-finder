#!/usr/bin/env python3
"""
Test script to run live search fallback for Indeed jobs using multiple search engines.
"""

import sys
import os
import urllib.parse
import re
from bs4 import BeautifulSoup

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

def fetch_live_indeed_fallback_jobs(keyword: str = "Data Scientist", location: str = "UK"):
    print("\n" + "=" * 75)
    print(f"🔎 RUNNING LIVE INDEED SEARCH FALLBACK FOR: '{keyword}' in '{location}'")
    print("=" * 75)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    results = []

    try:
        g_url = f"https://www.google.com/search?q=site:indeed.com/viewjob+{urllib.parse.quote(keyword)}&hl=en"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
        }
        resp = requests.get(g_url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        for a_tag in soup.find_all("a"):
            href = a_tag.get("href", "")
            if "/url?q=" in href:
                href = href.split("/url?q=")[1].split("&")[0]
            
            if "indeed.com" in href and "jk=" in href:
                text = a_tag.get_text(strip=True)
                if text and len(text) > 3:
                    clean_title = text.split(" - ")[0].split(" | ")[0]
                    comp_name = text.split(" - ")[1].strip() if (" - " in text and len(text.split(" - ")) > 1) else "Indeed Employer"
                    results.append({"title": clean_title, "company": comp_name, "url": href})
    except Exception as e:
        print(f"  Notice: {e}")

    # Deduplicate results by URL
    unique_results = []
    seen = set()
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique_results.append(r)

    print(f"\n✓ Found {len(unique_results)} Indeed Job Postings via Search Index:\n")
    for idx, job in enumerate(unique_results[:10], 1):
        print(f"[{idx}] 🏷️ Title:   {job['title']}")
        print(f"    🏢 Company: {job['company']}")
        print(f"    🔗 URL:     {job['url']}\n")

    print("=" * 75 + "\n")

if __name__ == "__main__":
    fetch_live_indeed_fallback_jobs()
