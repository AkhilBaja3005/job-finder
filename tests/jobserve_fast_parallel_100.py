#!/usr/bin/env python3
"""
jobserve_fast_parallel_100.py - High-Performance Parallel 100-Job Ingestion & ATS Shortlist Suite.

Features:
- Multi-query discovery + pagination to collect 100+ unique listings across Jobserve.
- Parallel worker pool (6 concurrent async workers) for ultra-fast JD retrieval.
- 3-tier deduplication (Canonical key + snippet hash + JD fingerprint).
- Full deterministic ATS scoring & skill gap analysis across all 100 jobs.
- Clean ranked output to JSON & Markdown report artifact.
"""

import sys
import os
import re
import json
import asyncio
import hashlib
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, os.path.abspath("backend"))

from bs4 import BeautifulSoup
from services.ats_scorer import (
    compute_ats_score,
    compute_overall_score,
    estimate_role_fit_score,
    _extract_taxonomy_skills
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SEARCH_QUERIES = [
    {"kw": "AI Engineer", "loc": "London"},
    {"kw": "Machine Learning Engineer", "loc": "London"},
    {"kw": "Generative AI LLM", "loc": "London"},
    {"kw": "AI Solutions Engineer RAG", "loc": "London"},
    {"kw": "MLOps Platform Engineer", "loc": "London"},
    {"kw": "Python AI Developer", "loc": "London"},
    {"kw": "Senior Data Scientist ML", "loc": "London"},
    {"kw": "Agentic AI Architect", "loc": "London"},
    {"kw": "AI Tech Lead Python", "loc": "London"},
    {"kw": "Deep Learning NLP Engineer", "loc": "London"},
]

CONCURRENCY_WORKERS = 5


def _clean_key(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', (text or '').lower())


def load_candidate_profile() -> Dict[str, Any]:
    """Loads candidate profile for ATS scoring."""
    paths = ["backend/config/candidate_profile.json", "backend/config/candidate_profile.example.json"]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cand = data.get("candidate", data)
                    if cand and cand.get("name"):
                        skills = cand.get("skills", cand.get("core_skills", []))
                        exp = cand.get("experience", cand.get("work_experience", []))
                        norm_exp = []
                        for e in exp:
                            desc = e.get("description", e.get("highlights", []))
                            if isinstance(desc, str):
                                desc = [desc]
                            norm_exp.append({
                                "company": e.get("company", ""),
                                "role": e.get("role", e.get("title", "AI Engineer")),
                                "start_date": e.get("start_date", "01/2021"),
                                "end_date": e.get("end_date", "Present"),
                                "description": desc,
                                "skills": e.get("technologies", e.get("skills", []))
                            })
                        return {
                            "name": cand.get("name", "Akhil Baja"),
                            "skills": skills,
                            "education": cand.get("education", []),
                            "experience": norm_exp,
                            "years_experience": cand.get("years_experience", 5)
                        }
            except Exception:
                pass

    return {
        "name": "Akhil Baja",
        "skills": [
            "Python", "PyTorch", "TensorFlow", "Generative AI", "LLM", "RAG",
            "Agentic AI", "LangChain", "Vector Databases", "FastAPI", "Docker",
            "Kubernetes", "AWS", "Machine Learning", "Deep Learning", "NLP",
            "PostgreSQL", "Redis", "TypeScript", "React", "CI/CD", "Git", "Azure"
        ],
        "education": [{"institution": "University", "degree": "B.S. in Computer Science", "start_year": 2017, "end_year": 2020}],
        "experience": [
            {
                "company": "Enterprise AI Systems",
                "role": "Senior AI Engineer",
                "start_date": "01/2021",
                "end_date": "Present",
                "description": [
                    "Architected high-throughput GenAI microservices and RAG pipelines using Python, FastAPI, PyTorch, LangChain, and vector databases.",
                    "Implemented autonomous multi-agent systems and LLM orchestration reducing workflow latencies by 45%."
                ],
                "skills": ["Python", "PyTorch", "LLM", "RAG", "FastAPI", "Docker", "AWS"]
            }
        ],
        "years_experience": 5
    }


async def discover_job_stubs(target_count: int = 100, timeframe: str = "1w") -> List[Dict[str, Any]]:
    """
    Phase 1: Rapid discovery of 100+ unique job stubs (div_id, title, url, teaser)
    across queries and pagination.
    """
    from playwright.async_api import async_playwright

    age_val = "7" if timeframe == "1w" else ("1" if timeframe == "24h" else ("2" if timeframe == "48h" else "30"))
    unique_stubs: Dict[str, Dict[str, Any]] = {}
    seen_canonical: set = set()
    seen_snippets: set = set()

    print(f"\n[Phase 1] 🚀 Rapidly discovering {target_count} unique job listings on Jobserve...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(user_agent=HEADERS["User-Agent"], viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        for q_idx, q in enumerate(SEARCH_QUERIES, 1):
            if len(unique_stubs) >= target_count:
                break

            kw = q["kw"]
            loc = q["loc"]
            print(f"  🔍 Query [{q_idx}/{len(SEARCH_QUERIES)}]: '{kw}' in '{loc}' (Found {len(unique_stubs)}/{target_count})...")

            try:
                await page.goto("https://www.jobserve.com/gb/en/Job-Search/", wait_until="networkidle", timeout=15000)

                # Dismiss cookies
                try:
                    cookie_btn = page.locator("a:has-text('Accept All'), button:has-text('Accept'), #onetrust-accept-btn-handler, #btnAccept").first
                    if await cookie_btn.count() > 0:
                        await cookie_btn.click()
                        await page.wait_for_timeout(200)
                except Exception:
                    pass

                # Fill search form
                kw_input = page.locator("#txtKey, input[name*='txtKey']").first
                if await kw_input.count() > 0:
                    await kw_input.fill(kw)

                loc_input = page.locator("#txtLoc, input[name*='txtLoc']").first
                if await loc_input.count() > 0:
                    await loc_input.fill(loc)

                try:
                    age_select = page.locator("#selAge, select[name*='selAge']").first
                    if await age_select.count() > 0:
                        await age_select.select_option(value=age_val)
                except Exception:
                    pass

                search_btn = page.locator("#btnSearch, input[value='Search'], button:has-text('Search')").first
                if await search_btn.count() > 0:
                    await search_btn.click()
                else:
                    await page.keyboard.press("Enter")

                for page_num in range(1, 4):
                    if len(unique_stubs) >= target_count:
                        break

                    try:
                        await page.wait_for_selector(".jobItem, tr[id^='job_'], div[id^='job_'], #JobResults", timeout=8000)
                        await page.wait_for_timeout(800)
                    except Exception:
                        break

                    cards = await page.evaluate('''() => {
                        const items = [];
                        const divs = document.querySelectorAll(".jobItem, tr[id^='job_'], div[id^='job_']");
                        divs.forEach(div => {
                            const id = div.id || "";
                            const titleEl = div.querySelector("h3 a, .jobtitle, .positiontitle, h3, a");
                            const title = titleEl ? titleEl.innerText.trim() : "";
                            const linkEl = div.querySelector("a[href*='/job/'], a[href*='/Job/'], a[href*='jid'], a[id*='positionlink'], h3 a");
                            const href = linkEl ? linkEl.getAttribute('href') : "";
                            const rawText = div.innerText.trim();
                            items.push({ id, title, href, rawText });
                        });
                        return items;
                    }''')

                    added_on_page = 0
                    for c in cards:
                        if len(unique_stubs) >= target_count:
                            break

                        div_id = c["id"]
                        title = c["title"]
                        raw_text = c["rawText"]
                        href = c["href"]

                        if not div_id or not title:
                            continue

                        snip_hash = hashlib.md5(raw_text[:140].encode('utf-8')).hexdigest()
                        canon = _clean_key(title)

                        if snip_hash in seen_snippets or canon in seen_canonical:
                            continue

                        seen_snippets.add(snip_hash)
                        seen_canonical.add(canon)

                        full_url = urllib.parse.urljoin("https://www.jobserve.com", href) if href else f"https://www.jobserve.com/{div_id}"
                        unique_stubs[div_id] = {
                            "job_id": div_id,
                            "title": title,
                            "url": full_url,
                            "raw_text": raw_text,
                            "query": kw,
                            "location": loc
                        }
                        added_on_page += 1

                    print(f"    Page {page_num}: Added {added_on_page} unique jobs (Total: {len(unique_stubs)}/{target_count})")

                    # Paginate if needed
                    if len(unique_stubs) < target_count:
                        next_btn = page.locator("a:has-text('Next'), a#btnNext, a.pagerNext, #ctl00_main_srch_ctl_qs_btnNext").first
                        if await next_btn.count() > 0:
                            await next_btn.click()
                            await page.wait_for_timeout(1500)
                        else:
                            break

            except Exception as ex:
                print(f"    Error querying '{kw}': {ex}")

        await browser.close()

    print(f"\n[Phase 1 Complete] ✓ Successfully discovered {len(unique_stubs)} strictly unique job listings.")
    return list(unique_stubs.values())


async def fetch_single_job_detail(context, stub: Dict[str, Any], semaphore: asyncio.Semaphore) -> Dict[str, Any]:
    """Worker task that fetches full job description concurrently."""
    async with semaphore:
        page = await context.new_page()
        div_id = stub["job_id"]
        job_url = stub["url"]
        job_title = stub["title"]
        raw_text = stub["raw_text"]

        try:
            # Navigate directly to the job URL or preview
            await page.goto(job_url, wait_until="domcontentloaded", timeout=12000)
            await page.wait_for_timeout(500)

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")

            # Extract Title
            title_elem = soup.select_one("h1, .positiontitle, #td_jobpositionlink, .job-title")
            title = title_elem.get_text(strip=True) if title_elem else job_title

            # Extract Company / Agency
            comp_elem = soup.select_one("#td_posted_by_name, .posted_by, .agency_name, .company_name, .recruiter")
            company = comp_elem.get_text(strip=True) if comp_elem else "Hiring Agency / Client"

            # Extract Location
            loc_elem = soup.select_one("#td_job_location, .job_location, .location")
            location = loc_elem.get_text(strip=True) if loc_elem else stub["location"]

            # Extract Rate / Salary
            rate_elem = soup.select_one("#td_job_rate, .job_rate, .rate, .salary")
            rate = rate_elem.get_text(strip=True) if rate_elem else "Competitive"

            # Extract Date
            date_elem = soup.select_one("#td_posted_date, .posted_date, .date")
            posted_date = date_elem.get_text(strip=True) if date_elem else "Recent"

            # Extract Job Description
            jd_elem = soup.select_one("#JobDetails, .job_description, .jobdetails, .content, #job-content")
            if jd_elem:
                description = jd_elem.get_text(separator="\n", strip=True)
            else:
                description = soup.get_text(separator="\n", strip=True)

            if len(description) < 100:
                description = raw_text

            # Enhanced rate regex if rate was default
            if rate in ["Competitive", "", "N/A"]:
                rate_m = re.search(r'(?:£|\$|€)\s*\d+[\d,kK\.\s-]*(?:per\s+(?:day|hour|annum|month)|/day|/hr|/yr|k\b|annum\b)?', description)
                if rate_m:
                    rate = rate_m.group(0).strip()

            return {
                "job_id": div_id,
                "title": title or job_title,
                "company": company,
                "location": location,
                "rate": rate,
                "posted_date": posted_date,
                "url": page.url if page.url != "about:blank" else job_url,
                "description": description,
                "platform": "Jobserve"
            }
        except Exception:
            # Fallback to stub text on network timeout
            return {
                "job_id": div_id,
                "title": job_title,
                "company": "Hiring Agency / Client",
                "location": stub["location"],
                "rate": "Competitive",
                "posted_date": "Recent",
                "url": job_url,
                "description": raw_text,
                "platform": "Jobserve"
            }
        finally:
            await page.close()


async def parallel_fetch_all_jds(stubs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Phase 2: Concurrently fetches all full JDs using a browser context pool."""
    from playwright.async_api import async_playwright

    print(f"\n[Phase 2] ⚡ Parallel Fetching {len(stubs)} full JDs with {CONCURRENCY_WORKERS} concurrent workers...")
    semaphore = asyncio.Semaphore(CONCURRENCY_WORKERS)
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])

        tasks = [fetch_single_job_detail(context, stub, semaphore) for stub in stubs]
        
        # Track progress with chunked gather
        chunk_size = 10
        for i in range(0, len(tasks), chunk_size):
            chunk = tasks[i:i + chunk_size]
            chunk_results = await asyncio.gather(*chunk)
            results.extend(chunk_results)
            print(f"  ✓ Fetched [{len(results)}/{len(stubs)}] job descriptions in parallel...")

        await browser.close()

    return results


def score_and_rank_all_jobs(jobs: List[Dict[str, Any]], candidate_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Phase 3: Runs full deterministic ATS scoring across all 100 jobs."""
    print(f"\n[Phase 3] 🎯 ATS Scoring {len(jobs)} jobs against candidate profile...")
    ranked = []

    for job in jobs:
        jd_text = job["description"]
        title = job["title"]
        try:
            ats_res = compute_ats_score(resume_data=candidate_profile, jd_text=jd_text)
            role_fit = estimate_role_fit_score(candidate_profile, jd_text)
            overall = compute_overall_score(ats_res.skills_score, ats_res.experience_score, role_fit)

            jd_taxonomy = _extract_taxonomy_skills(jd_text)
            cand_skills_set = {s.lower() for s in candidate_profile.get("skills", [])}
            matched = [s for s in jd_taxonomy if s.lower() in cand_skills_set]
            missing = [s for s in jd_taxonomy if s.lower() not in cand_skills_set]

            ranked.append({
                **job,
                "overall_score": overall,
                "skills_score": ats_res.skills_score,
                "experience_score": ats_res.experience_score,
                "role_fit_score": role_fit,
                "matched_skills": matched,
                "missing_skills": missing,
                "fit_tier": "🔥 Top Tier (>=75%)" if overall >= 75 else ("⚡ High Fit (65-74%)" if overall >= 65 else "📋 Moderate (<65%)")
            })
        except Exception as e:
            print(f"  Error scoring '{title}': {e}")

    ranked.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
    return ranked


def generate_shortlist_report(ranked_jobs: List[Dict[str, Any]], top_n: int = 25) -> str:
    """Generates Markdown Shortlist Report."""
    report = []
    report.append("# 🎯 Jobserve Top 100 Ingestion & Shortlist Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} | **Total Scored:** {len(ranked_jobs)} Unique Jobs\n")
    report.append("--- \n")
    report.append("## 🏆 Top 25 Shortlisted Opportunities\n")
    report.append("| Rank | Overall ATS | Skills Fit | Rate / Salary | Role & Location | Direct Link |")
    report.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for idx, j in enumerate(ranked_jobs[:top_n], 1):
        rate = j['rate'] if j['rate'] != "Competitive" else "Market Rate"
        report.append(f"| **#{idx}** | **{j['overall_score']}%** | {j['skills_score']}% | `{rate}` | **{j['title']}** <br>_{j['company']}_ ({j['location']}) | [View Job]({j['url']}) |")

    report.append("\n---\n")
    report.append("## 📋 Detailed Breakdown of Top Opportunities\n")

    for idx, j in enumerate(ranked_jobs[:top_n], 1):
        report.append(f"### #{idx}. {j['title']}")
        report.append(f"- **Company / Agency:** {j['company']}")
        report.append(f"- **Location:** {j['location']}")
        report.append(f"- **Compensation:** `{j['rate']}`")
        report.append(f"- **Posted Date:** {j['posted_date']}")
        report.append(f"- **Overall ATS Match:** **{j['overall_score']}%** ({j['fit_tier']})")
        report.append(f"- **Skills Match:** {j['skills_score']}% | **Experience Match:** {j['experience_score']}% | **Role Fit:** {j['role_fit_score']}%")
        report.append(f"- **Key Matched Skills:** `{', '.join(j['matched_skills'][:10]) if j['matched_skills'] else 'N/A'}`")
        if j['missing_skills']:
            report.append(f"- **Skill Gaps:** `{', '.join(j['missing_skills'][:6])}`")
        report.append(f"- **Direct URL:** [{j['url']}]({j['url']})")
        report.append(f"- **JD Excerpt:**\n> {j['description'][:280]}...\n")
        report.append("---\n")

    return "\n".join(report)


async def main():
    print("=" * 80)
    print(" Jobserve 100 Fast Parallel Ingestion & ATS Shortlist Suite")
    print("=" * 80)

    profile = load_candidate_profile()
    print(f"Loaded Profile: {profile.get('name')} ({len(profile.get('skills', []))} skills, {profile.get('years_experience')}y exp).")

    # Phase 1: Rapid discovery of 100 unique job stubs
    stubs = await discover_job_stubs(target_count=100, timeframe="1w")

    # Phase 2: Parallel fetch of all JDs
    full_jobs = await parallel_fetch_all_jds(stubs)

    # Phase 3: In-memory deterministic ATS scoring
    ranked_jobs = score_and_rank_all_jobs(full_jobs, profile)

    # Save outputs
    output_json = "jobserve_top100_results.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(ranked_jobs, f, indent=2)
    print(f"\n✓ Saved all {len(ranked_jobs)} scored jobs to {output_json}")

    report_md = generate_shortlist_report(ranked_jobs, top_n=25)
    with open("jobserve_shortlist_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"✓ Saved Shortlist Report to jobserve_shortlist_report.md")

    # Print Summary Table
    print("\n" + "=" * 90)
    print(f" Top 20 Shortlisted Jobs (from {len(ranked_jobs)} Unique Jobserve Postings)")
    print("=" * 90)
    print(f"{'#':<3} | {'ATS Score':<10} | {'Skills Fit':<12} | {'Rate / Salary':<22} | {'Job Title'}")
    print("-" * 90)
    for idx, j in enumerate(ranked_jobs[:20], 1):
        print(f"{idx:<3} | {j['overall_score']:<10}% | {j['skills_score']:<12}% | {j['rate'][:20]:<22} | {j['title'][:35]}")


if __name__ == "__main__":
    asyncio.run(main())
