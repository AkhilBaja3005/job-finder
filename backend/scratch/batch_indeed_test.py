import asyncio
import sys
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.scraper import scrape_job_description
from main import _extract_company_from_jd

async def test_indeed_links():
    urls = [
        "https://www.indeed.com/viewjob?jk=bc648143fe26ee4f",
        "https://www.indeed.com/viewjob?jk=059945040a6a3e85",
        "https://www.indeed.com/viewjob?jk=472525ccef9e96fd",
        "https://www.indeed.com/viewjob?jk=ea2c5e32ab039b3c"
    ]
    
    print("\n" + "=" * 65)
    print("🔎 TESTING INDEED COMPANY NAME & TITLE EXTRACTION")
    print("=" * 65)
    
    # pyrefly: ignore [missing-import]
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for idx, url in enumerate(urls, 1):
            print(f"\n[{idx}] URL: {url}")
            try:
                data = await scrape_job_description(url, browser=browser)
                title = data.get("title", "Unknown")
                company = _extract_company_from_jd(data.get("description", ""), url)
                print(f"    🏷️ Title:   {title}")
                print(f"    🏢 Company: {company}")
            except Exception as e:
                print(f"    ⚠️ Error scraping {url}: {e}")
        await browser.close()
    print("=" * 65 + "\n")

if __name__ == "__main__":
    asyncio.run(test_indeed_links())
