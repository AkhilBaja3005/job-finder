import asyncio
import os
import sys
import time
import json

sys.path.insert(0, os.path.abspath("backend"))

from services.job_searcher import find_matching_jobs
from mcp.tools.profile_tools import load_profile_data

async def run_profile_yield_benchmark():
    print("=" * 70)
    print("⏱️ PROFILING LIVE END-TO-END SEARCH: 48h | UK | CANDIDATE PROFILE")
    print("=" * 70)

    prof = load_profile_data() or {}
    target_roles = prof.get("search_preferences", {}).get("target_roles", [
        "Generative AI Engineer", "Machine Learning Engineer", "AI Systems Engineer"
    ])
    
    # Candidate resume context for scoring
    resume_data = {
        "candidate_name": "Akhil",
        "recent_roles": target_roles,
        "skills": ["Python", "Machine Learning", "PyTorch", "Generative AI", "LLMs", "FastAPI", "NLP", "LangChain", "Docker", "Cloud"],
        "experience": [
            {
                "title": "Machine Learning Engineer / AI Engineer",
                "description": "Developed and deployed LLM pipelines, RAG architectures, FastAPI microservices, and AI evaluation frameworks."
            }
        ]
    }

    start_time = time.time()
    first_chunk_time = None
    all_jobs = []
    logs = []

    print(f"\n🚀 Initiating stream with queries: {', '.join(target_roles[:3])}")
    print(f"📍 Location: UK | ⏳ Timeframe: 48h\n")

    try:
        async for chunk in find_matching_jobs(
            resume_data=resume_data,
            location="UK",
            keywords="AI Engineer, Machine Learning Engineer",
            timeframe="48h",
            target_platforms=["ashby", "greenhouse", "lever", "bamboohr", "jobserve"]
        ):
            if first_chunk_time is None:
                first_chunk_time = time.time()
                print(f"⚡ Time to First Stream Event: {round(first_chunk_time - start_time, 2)}s")

            try:
                msg = json.loads(chunk.strip())
                m_type = msg.get("type")
                if m_type == "log":
                    logs.append(msg.get("message"))
                    print(f"  [STREAM] {msg.get('message')[:90]}")
                elif m_type == "result":
                    all_jobs = msg.get("jobs", [])
            except Exception:
                pass

        total_elapsed = time.time() - start_time
        print("\n" + "=" * 70)
        print("🏁 SEARCH & ATS SCORING COMPLETE")
        print("=" * 70)
        print(f"⏱️ Total Time Elapsed: {round(total_elapsed, 2)} seconds")
        print(f"📊 Total Appropriate Jobs Found: {len(all_jobs)}")
        
        # Group by platform
        plat_counts = {}
        for j in all_jobs:
            p = j.get("platform", "Other")
            plat_counts[p] = plat_counts.get(p, 0) + 1
        
        print("\n📈 Jobs Grouped by Platform:")
        for p, count in plat_counts.items():
            print(f"  • {p:<15}: {count:>4} jobs")

        print("\n🌟 TOP 10 HIGHEST ATS RANKED JOBS FOR YOUR PROFILE:")
        for idx, j in enumerate(all_jobs[:10], 1):
            title = j.get("title", "Untitled")
            comp = j.get("company", "Unknown")
            loc = j.get("location", "UK")
            url = j.get("url", "")
            score = j.get("ats_score", 0)
            skills = j.get("matched_skills", [])
            print(f"\n{idx}. [{score}% Match] {title} @ {comp}")
            print(f"   📍 {loc} | Platform: {j.get('platform')}")
            print(f"   🎯 Key Skills: {', '.join(skills[:4]) if skills else 'Relevant Experience'}")
            print(f"   🔗 {url}")

    except Exception as e:
        print(f"❌ Error during execution: {e}")

if __name__ == "__main__":
    asyncio.run(run_profile_yield_benchmark())
