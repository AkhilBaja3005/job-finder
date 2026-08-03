import asyncio
import sys
import os

import sys
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.scraper import scrape_job_description
from main import _extract_company_from_jd

async def test_indeed_url():
    test_url = "https://www.indeed.com/viewjob?jk=4c1018a1d2d2bf7e"
    print(f"Testing scraper on URL: {test_url}")
    scraped = await scrape_job_description(test_url)
    print("Title:", scraped.get("title"))
    print("Company:", _extract_company_from_jd(scraped.get("description"), test_url))
    print("Description length:", len(scraped.get("description", "")))

if __name__ == "__main__":
    asyncio.run(test_indeed_url())
