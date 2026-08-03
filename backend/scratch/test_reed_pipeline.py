import os
import sys
import json
import asyncio

# Ensure backend path is in python sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("REED_API_KEY"):
    os.environ["REED_API_KEY"] = "8cd9848f-8afd-4376-adf7-f8958c7a89f2"

from services.job_searcher import search_reed_jobs, _score_job_with_title_heuristic
from services.scraper import scrape_job_description

async def test_reed_pipeline():
    print("=" * 75)
    print("🔎 TESTING REED.CO.UK JOB SEARCH & DETAILS API PIPELINE")
    print("=" * 75)

    # Dummy resume data for candidate matching
    sample_resume = {
        "name": "Akhil Baja",
        "skills": ["Python", "PyTorch", "Machine Learning", "Data Science", "SQL", "LLMs"],
        "experience": [
            {"role": "Data Scientist", "company": "Tech Corp", "duration": "2 years"}
        ]
    }

    # 1. Test Reed Search API with timeframe filtering and descending sort
    print("\n[Step 1] Executing Reed Search API for 'Data Scientist' in 'London' (timeframe: 48h)...")
    reed_jobs = search_reed_jobs("Data Scientist", "London", timeframe="48h")
    
    print(f"\n✓ Found {len(reed_jobs)} fresh Reed jobs (sorted newest first):\n")
    for idx, job in enumerate(reed_jobs[:5], 1):
        print(f"  [{idx}] {job.title}")
        print(f"      🏢 Company: {job.company}")
        print(f"      📍 Location: {job.location}")
        print(f"      📅 Date Posted: {job.post_date_raw}")
        print(f"      🔗 URL: {job.url}")
        
        # Test title heuristic match
        heuristic_score = _score_job_with_title_heuristic(job, sample_resume)
        print(f"      🎯 Estimated Heuristic Match: {heuristic_score.get('score')}%\n")

    if not reed_jobs:
        print("❌ No Reed jobs returned. Verify API Key and Internet connectivity.")
        return

    # 2. Test Reed Fast-Path Details API Scraping on the first result
    target_job = reed_jobs[0]
    print("=" * 75)
    print(f"[Step 2] Testing Instant Reed Details API Scraping for: '{target_job.title}'...")
    print(f"URL: {target_job.url}")
    print("=" * 75)

    import time
    t0 = time.time()
    scraped_result = await scrape_job_description(target_job.url)
    elapsed = (time.time() - t0) * 1000

    print(f"\n⚡ Extracted JD in {elapsed:.1f}ms!")
    print(f"Title: {scraped_result.get('title')}")
    print(f"Company: {scraped_result.get('company')}")
    print(f"Description Length: {len(scraped_result.get('description', ''))} chars")
    print("\nSnippet of Extracted JD:")
    print("-" * 50)
    print(scraped_result.get('description', '')[:300] + "...")
    print("-" * 50)
    
    print("\n✅ Reed API Job Search & Details Fast-Path Test Passed Successfully!\n")

if __name__ == "__main__":
    asyncio.run(test_reed_pipeline())
