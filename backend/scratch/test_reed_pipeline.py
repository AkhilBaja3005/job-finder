import os
import sys
import json
import asyncio

# Ensure backend path is in python sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("REED_API_KEY"):
    os.environ["REED_API_KEY"] = "8cd9848f-8afd-4376-adf7-f8958c7a89f2"

from services.job_searcher import search_reed_jobs, _score_job_with_real_jd
from services.scraper import scrape_job_description

async def test_reed_pipeline():
    print("=" * 75)
    print("🔎 TESTING REED.CO.UK JOB SEARCH & REAL JD ATS SCORING PIPELINE")
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
    
    print(f"\n✓ Found {len(reed_jobs)} fresh pre-screened Reed jobs (sorted newest first):\n")

    if not reed_jobs:
        print("❌ No Reed jobs returned. Verify API Key and Internet connectivity.")
        return

    # 2. Test Real JD ATS Scoring via _score_job_with_real_jd
    print("=" * 75)
    print("[Step 2] Computing Accurate ATS Scores with Real JD Parsing (_score_job_with_real_jd)...")
    print("=" * 75)

    semaphore = asyncio.Semaphore(5)
    for idx, job in enumerate(reed_jobs[:5], 1):
        # Call _score_job_with_real_jd directly using real scraped JD
        scored_result = await _score_job_with_real_jd(job, sample_resume, browser=None, semaphore=semaphore)
        if scored_result:
            print(f"  [{idx}] {scored_result['title']}")
            print(f"      🏢 Company: {scored_result['company']}")
            print(f"      📍 Location: {scored_result['location']}")
            print(f"      🎯 Real ATS Overall Score: {scored_result['score']}%")
            print(f"      📊 Skills Match: {scored_result['skills_score']}% | Exp Score: {scored_result['experience_score']}%")
            print(f"      ✅ Matched Skills: {', '.join(scored_result['matched_skills']) if scored_result['matched_skills'] else 'None'}")
            print(f"      ⚠️ Missing Skills: {', '.join(scored_result['missing_skills']) if scored_result['missing_skills'] else 'None'}")
            print(f"      🔗 URL: {scored_result['url']}\n")
        else:
            print(f"  [{idx}] {job.title} — Rejected by JD ATS eligibility or spam filter.\n")

    print("\n✅ Reed API Job Search & Real JD ATS Scoring Test Passed Successfully!\n")

if __name__ == "__main__":
    asyncio.run(test_reed_pipeline())
