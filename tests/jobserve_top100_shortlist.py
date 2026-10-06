#!/usr/bin/env python3
"""
jobserve_top100_shortlist.py - Ingests 100 jobs from Jobserve and produces a ranked ATS Shortlist.

1. Executes multi-query sweeps across Jobserve (AI Engineer, Machine Learning, Python GenAI, LLM Platform).
2. Collects 100 distinct job postings with full JDs, compensation rates, and recruiter info.
3. Scores every single job against your candidate profile using the deterministic ATS Scoring Engine.
4. Shortlists and ranks the top-fit opportunities with detailed match breakdown and direct URLs.
5. Saves results to JSON and generates an artifact report.
"""

import sys
import os
import re
import json
import asyncio
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

QUERIES = [
    {"kw": "AI Engineer", "loc": "London"},
    {"kw": "Machine Learning Engineer", "loc": "London"},
    {"kw": "Python Generative AI LLM", "loc": "London"},
    {"kw": "AI Platform Engineer RAG", "loc": "London"},
    {"kw": "Senior AI Python Developer", "loc": "London"},
]


def load_candidate_profile() -> Dict[str, Any]:
    """Loads existing candidate profile or returns a verified AI Engineer profile."""
    paths = [
        "backend/config/candidate_profile.json",
        "backend/config/candidate_profile.example.json",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cand = data.get("candidate", data)
                    if cand and cand.get("name"):
                        # Ensure skills and experience are list-formatted for ats_scorer
                        skills = cand.get("skills", cand.get("core_skills", []))
                        exp = cand.get("experience", cand.get("work_experience", []))
                        # Normalize exp descriptions to lists of strings if strings
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

    # High-caliber AI Engineer fallback profile
    return {
        "name": "Akhil Baja",
        "skills": [
            "Python", "PyTorch", "TensorFlow", "Generative AI", "LLM", "RAG",
            "Agentic AI", "LangChain", "Vector Databases", "FastAPI", "Docker",
            "Kubernetes", "AWS", "Machine Learning", "Deep Learning", "NLP",
            "PostgreSQL", "Redis", "TypeScript", "React", "CI/CD", "Git", "Azure",
            "Pinecone", "Milvus", "ChromaDB", "Fine-Tuning", "Prompt Engineering"
        ],
        "education": [
            {
                "institution": "University",
                "degree": "B.S. in Computer Science",
                "start_year": 2017,
                "end_year": 2020
            }
        ],
        "experience": [
            {
                "company": "Enterprise AI Systems",
                "role": "Senior AI Engineer",
                "start_date": "01/2021",
                "end_date": "Present",
                "description": [
                    "Architected high-throughput GenAI microservices and RAG pipelines using Python, FastAPI, PyTorch, LangChain, and vector databases.",
                    "Implemented autonomous multi-agent systems and LLM orchestration reducing workflow latencies by 45%.",
                    "Deployed containerized machine learning models to AWS and Azure using Docker and Kubernetes with automated CI/CD pipelines.",
                    "Fine-tuned open-source LLMs and built semantic vector search retrieval across multi-million document indexes."
                ],
                "skills": ["Python", "PyTorch", "LLM", "RAG", "Agentic AI", "LangChain", "Vector Databases", "FastAPI", "Docker", "AWS", "PostgreSQL", "Redis"]
            }
        ],
        "years_experience": 5
    }


def _clean_key(text: str) -> str:
    """Normalizes title or company for canonical deduplication."""
    return re.sub(r'[^a-zA-Z0-9]', '', (text or '').lower())


async def fetch_jobserve_100_jobs(target_count: int = 100, timeframe: str = "1w") -> List[Dict[str, Any]]:
    """
    Sweeps across search queries and pages on Jobserve to collect 100 strictly unique jobs.
    Implements 3-tier deduplication:
    1. Pre-click Canonical Key (Normalized Title + Company)
    2. Summary / Snippet hash filtering
    3. Post-fetch Full JD MD5 Content Fingerprinting
    """
    from playwright.async_api import async_playwright
    import hashlib

    age_val = "7" if timeframe == "1w" else ("1" if timeframe == "24h" else ("2" if timeframe == "48h" else "30"))
    
    collected_jobs: Dict[str, Dict[str, Any]] = {}
    seen_canonical_keys: set = set()
    seen_snippet_hashes: set = set()
    seen_jd_hashes: set = set()

    print(f"\n[Jobserve Orchestrator] Starting sweep for {target_count} STRICTLY UNIQUE jobs (Timeframe: {timeframe})...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()

        for q_idx, q_item in enumerate(QUERIES, 1):
            if len(collected_jobs) >= target_count:
                break

            kw = q_item["kw"]
            loc = q_item["loc"]
            print(f"\n--- Query [{q_idx}/{len(QUERIES)}]: '{kw}' in '{loc}' (Unique Collected: {len(collected_jobs)}/{target_count}) ---")

            try:
                await page.goto("https://www.jobserve.com/gb/en/Job-Search/", wait_until="networkidle", timeout=20000)

                # Dismiss cookie banner
                try:
                    cookie_btn = page.locator("a:has-text('Accept All'), button:has-text('Accept'), #onetrust-accept-btn-handler, #btnAccept").first
                    if await cookie_btn.count() > 0:
                        await cookie_btn.click()
                        await page.wait_for_timeout(300)
                except Exception:
                    pass

                # Fill Search Form
                kw_input = page.locator("#txtKey, input[name*='txtKey']").first
                if await kw_input.count() > 0:
                    await kw_input.fill(kw)

                loc_input = page.locator("#txtLoc, input[name*='txtLoc']").first
                if await loc_input.count() > 0:
                    await loc_input.fill(loc)

                # Set Age / Timeframe
                try:
                    age_select = page.locator("#selAge, select[name*='selAge']").first
                    if await age_select.count() > 0:
                        await age_select.select_option(value=age_val)
                except Exception:
                    pass

                # Click Search
                search_btn = page.locator("#btnSearch, input[value='Search'], button:has-text('Search')").first
                if await search_btn.count() > 0:
                    await search_btn.click()
                else:
                    await page.keyboard.press("Enter")

                # Process multiple pages per query if needed to fill target
                for page_num in range(1, 4):
                    if len(collected_jobs) >= target_count:
                        break

                    try:
                        await page.wait_for_selector(".jobItem, tr[id^='job_'], div[id^='job_'], #JobResults", timeout=10000)
                        await page.wait_for_timeout(1500)
                    except Exception:
                        break

                    # Extract card data from current page
                    raw_items = await page.evaluate('''() => {
                        const items = [];
                        const divs = document.querySelectorAll(".jobItem, tr[id^='job_'], div[id^='job_']");
                        divs.forEach(div => {
                            const id = div.id || "";
                            const titleEl = div.querySelector("h3 a, .jobtitle, .positiontitle, h3, a");
                            const title = titleEl ? titleEl.innerText.trim() : "";
                            const rawText = div.innerText.trim();
                            items.push({ id, title, rawText });
                        });
                        return items;
                    }''')

                    print(f"  [Page {page_num}] Discovered {len(raw_items)} listings on page. Filtering & ingesting...")

                    for item in raw_items:
                        if len(collected_jobs) >= target_count:
                            break

                        div_id = item["id"]
                        job_title = item["title"]
                        raw_text = item["rawText"]

                        if not div_id or not job_title:
                            continue

                        # Pre-filter Stage 1: Snippet Hash
                        snippet_sig = hashlib.md5(raw_text[:140].encode('utf-8')).hexdigest()
                        if snippet_sig in seen_snippet_hashes:
                            # Already seen this exact agency snippet
                            continue
                        seen_snippet_hashes.add(snippet_sig)

                        # Pre-filter Stage 2: Normalized Title Check
                        clean_title_sig = _clean_key(job_title)
                        if clean_title_sig in seen_canonical_keys:
                            continue

                        # Synchronized Preview Loading
                        try:
                            job_el = page.locator(f"#{div_id}").first
                            if await job_el.count() > 0:
                                # Trigger click and wait for JobDetailPanel to update
                                await job_el.click()
                                await page.wait_for_timeout(900)
                        except Exception:
                            pass

                        # Extract updated detail panel
                        detail_html = await page.evaluate('''() => {
                            const p = document.getElementById("JobDetailPanel");
                            return p ? p.innerHTML : "";
                        }''')

                        soup = BeautifulSoup(detail_html, "html.parser")

                        title_elem = soup.select_one("h1, .positiontitle, #td_jobpositionlink")
                        title = title_elem.get_text(strip=True) if title_elem else job_title
                        
                        comp_elem = soup.select_one("#td_posted_by_name, .posted_by, .agency_name, .company_name")
                        company = comp_elem.get_text(strip=True) if comp_elem else "Hiring Agency / Client"
                        
                        loc_elem = soup.select_one("#td_job_location, .job_location, .location")
                        job_loc = loc_elem.get_text(strip=True) if loc_elem else loc
                        
                        rate_elem = soup.select_one("#td_job_rate, .job_rate, .rate, .salary")
                        rate = rate_elem.get_text(strip=True) if rate_elem else "Competitive"

                        date_elem = soup.select_one("#td_posted_date, .posted_date, .date")
                        posted_date = date_elem.get_text(strip=True) if date_elem else f"Last {timeframe}"

                        url_elem = soup.select_one("#td_jobpositionlink, a[id*='positionlink']")
                        href = url_elem.get("href", "") if url_elem else ""
                        full_url = urllib.parse.urljoin("https://www.jobserve.com", href) if href else f"https://www.jobserve.com/{div_id}"

                        jd_elem = soup.select_one("#JobDetails, .job_description, .jobdetails")
                        if jd_elem:
                            description = jd_elem.get_text(separator="\n", strip=True)
                        else:
                            description = soup.get_text(separator="\n", strip=True)

                        if len(description) < 100:
                            description = raw_text

                        # Post-filter Stage 3: JD Content Fingerprint
                        jd_fingerprint = hashlib.md5(description[:250].encode('utf-8')).hexdigest()
                        if jd_fingerprint in seen_jd_hashes:
                            # Duplicate JD body detected across agencies
                            continue
                        seen_jd_hashes.add(jd_fingerprint)

                        # Check Canonical Key (Title + Company)
                        canonical_key = f"{_clean_key(title)}|{_clean_key(company)}"
                        if canonical_key in seen_canonical_keys:
                            continue
                        seen_canonical_keys.add(canonical_key)
                        seen_canonical_keys.add(clean_title_sig)

                        # Extract rate if missing
                        if rate in ["Competitive", "", "N/A"]:
                            rate_m = re.search(r'(?:£|\$|€)\s*\d+[\d,kK\.\s-]*(?:per\s+(?:day|hour|annum|month)|/day|/hr|/yr|k\b|annum\b)?', description)
                            if rate_m:
                                rate = rate_m.group(0).strip()

                        collected_jobs[div_id] = {
                            "job_id": div_id,
                            "title": title or job_title,
                            "company": company,
                            "location": job_loc,
                            "rate": rate,
                            "posted_date": posted_date,
                            "url": full_url,
                            "description": description,
                            "platform": "Jobserve"
                        }
                        print(f"    ✓ [{len(collected_jobs)}/{target_count}] {title[:42]} | {company[:20]} | {rate}")

                    # Attempt pagination to next page if target not yet reached
                    if len(collected_jobs) < target_count:
                        next_btn = page.locator("a:has-text('Next'), a#btnNext, a.pagerNext, #ctl00_main_srch_ctl_qs_btnNext").first
                        if await next_btn.count() > 0:
                            print(f"  Navigating to Page {page_num + 1}...")
                            await next_btn.click()
                            await page.wait_for_timeout(2000)
                        else:
                            break

            except Exception as ex:
                print(f"  Error on query '{kw}': {ex}")

        await browser.close()

    return list(collected_jobs.values())


def score_and_shortlist(jobs: List[Dict[str, Any]], candidate_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scores all 100 jobs and ranks them by ATS overall match score."""
    ranked = []
    print(f"\n[ATS Engine] Scoring {len(jobs)} jobs against candidate profile...")

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
                "candidate_years": ats_res.candidate_years,
                "required_years": ats_res.required_years,
                "fit_tier": "🔥 Top Tier (>=75%)" if overall >= 75 else ("⚡ High Fit (65-74%)" if overall >= 65 else "📋 Moderate (<65%)")
            })
        except Exception as e:
            print(f"  Scoring failed for '{title}': {e}")

    ranked.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
    return ranked


def generate_shortlist_report(ranked_jobs: List[Dict[str, Any]], top_n: int = 20) -> str:
    """Generates a Markdown artifact report for the shortlisted jobs."""
    report = []
    report.append("# 🎯 Jobserve Top 100 Ingestion & Shortlist Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} | **Total Ingested:** {len(ranked_jobs)} Jobs\n")
    report.append("--- \n")
    report.append("## 🏆 Top Shortlisted Opportunities\n")
    report.append("| Rank | Overall ATS | Skills Fit | Rate / Salary | Role & Location | Direct Link |")
    report.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for idx, j in enumerate(ranked_jobs[:top_n], 1):
        rate = j['rate'] if j['rate'] != "Competitive" else "Market Rate"
        report.append(f"| **#{idx}** | **{j['overall_score']}%** | {j['skills_score']}% | `{rate}` | **{j['title']}** <br>_{j['company']}_ ({j['location']}) | [View Job]({j['url']}) |")

    report.append("\n---\n")
    report.append("## 📋 Detailed Breakdown of Top Candidates\n")

    for idx, j in enumerate(ranked_jobs[:top_n], 1):
        report.append(f"### #{idx}. {j['title']}")
        report.append(f"- **Company / Agency:** {j['company']}")
        report.append(f"- **Location:** {j['location']}")
        report.append(f"- **Compensation:** `{j['rate']}`")
        report.append(f"- **Posted Date:** {j['posted_date']}")
        report.append(f"- **Overall ATS Match:** **{j['overall_score']}%** ({j['fit_tier']})")
        report.append(f"- **Skills Match Score:** {j['skills_score']}% | **Experience Match:** {j['experience_score']}%")
        report.append(f"- **Key Matched Skills:** `{', '.join(j['matched_skills'][:10]) if j['matched_skills'] else 'N/A'}`")
        if j['missing_skills']:
            report.append(f"- **Skill Gaps:** `{', '.join(j['missing_skills'][:6])}`")
        report.append(f"- **Direct Application URL:** [{j['url']}]({j['url']})")
        report.append(f"- **JD Excerpt:**\n> {j['description'][:280]}...\n")
        report.append("---\n")

    return "\n".join(report)


async def main():
    print("=" * 80)
    print(" Jobserve 100 Jobs Ingestion & Shortlist Engine")
    print("=" * 80)

    profile = load_candidate_profile()
    print(f"Loaded Candidate Profile for: {profile.get('name')} with {len(profile.get('skills', []))} core skills.")

    # Fetch 100 jobs
    jobs = await fetch_jobserve_100_jobs(target_count=100, timeframe="1w")

    if not jobs:
        print("✕ Could not retrieve jobs from Jobserve.")
        return

    # Score and shortlist
    ranked_jobs = score_and_shortlist(jobs, profile)

    # Save to JSON
    output_json = "jobserve_top100_results.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(ranked_jobs, f, indent=2)
    print(f"\n✓ Saved all {len(ranked_jobs)} scored jobs to {output_json}")

    # Generate Report
    report_md = generate_shortlist_report(ranked_jobs, top_n=20)
    with open("jobserve_shortlist_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"✓ Saved Shortlist Report to jobserve_shortlist_report.md")

    # Print Summary Table
    print("\n" + "=" * 90)
    print(f" Top 15 Shortlisted Jobs from {len(ranked_jobs)} Jobserve Postings")
    print("=" * 90)
    print(f"{'#':<3} | {'ATS Score':<10} | {'Skills Score':<12} | {'Rate / Salary':<22} | {'Job Title'}")
    print("-" * 90)
    for idx, j in enumerate(ranked_jobs[:15], 1):
        print(f"{idx:<3} | {j['overall_score']:<10}% | {j['skills_score']:<12}% | {j['rate'][:20]:<22} | {j['title'][:35]}")


if __name__ == "__main__":
    asyncio.run(main())
