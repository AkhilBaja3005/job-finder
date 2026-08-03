import asyncio
import sys
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.job_searcher import search_indeed_jobs, search_linkedin_jobs

async def test_job_searchers():
    os.environ["FRONTEND_URL"] = "http://localhost:5173"
    print("\n" + "=" * 70)
    print("🧪 TESTING JOB SEARCHER PIPELINE LOCAL VALIDATION")
    print("=" * 70)
    
    # 1. Test LinkedIn Search
    print("\n[1] Testing LinkedIn Search ('Data Scientist', 'UK')...")
    linkedin_jobs = search_linkedin_jobs("Data Scientist", "UK", "24h")
    print(f"    ✓ LinkedIn Search complete. Returned {len(linkedin_jobs)} jobs.")
    if linkedin_jobs:
        print(f"    Sample: '{linkedin_jobs[0].title}' at '{linkedin_jobs[0].company}'")

    # 2. Test Indeed Search
    print("\n[2] Testing Indeed Search ('Data Scientist', 'UK')...")
    indeed_jobs = await search_indeed_jobs("Data Scientist", "UK", "24h")
    print(f"    ✓ Indeed Search complete. Returned {len(indeed_jobs)} jobs.")
    if indeed_jobs:
        print(f"    Sample: '{indeed_jobs[0].title}' at '{indeed_jobs[0].company}'")

    print("\n" + "=" * 70 + "\n")

if __name__ == "__main__":
    asyncio.run(test_job_searchers())
