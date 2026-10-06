#!/usr/bin/env python3
"""
jobserve_role_100_shortlist.py - Role-Specific 100-Job Ingestion & ATS Shortlist Suite.

Usage:
  python3 jobserve_role_100_shortlist.py --role "AI Engineer" --location "UK" --timeframe "1m" --target 100
  python3 jobserve_role_100_shortlist.py --role "Machine Learning Engineer" --location "UK" --timeframe "1m" --target 100
"""

import sys
import os
import re
import json
import asyncio
import hashlib
import argparse
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


async def collect_100_jobs_for_role(
    role: str = "AI Engineer",
    location: str = "UK",
    timeframe: str = "1m",
    target_count: int = 100
) -> List[Dict[str, Any]]:
    """
    Paginates through Jobserve search results for a specific role and extracts
    up to 100 strictly unique jobs with full descriptions and rates.
    """
    from playwright.async_api import async_playwright

    age_val = "30" if timeframe == "1m" else ("7" if timeframe == "1w" else ("1" if timeframe == "24h" else "2"))
    collected_jobs: Dict[str, Dict[str, Any]] = {}
    seen_canonical_keys: set = set()
    seen_snippet_hashes: set = set()
    seen_jd_hashes: set = set()

    print(f"\n[Jobserve Ingestor] 🚀 Target: {target_count} unique listings for role='{role}', location='{location}', timeframe='{timeframe}' (Age: {age_val}d)...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(user_agent=HEADERS["User-Agent"], viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        try:
            await page.goto("https://www.jobserve.com/gb/en/Job-Search/", wait_until="networkidle", timeout=20000)

            # Accept cookies
            try:
                cookie_btn = page.locator("a:has-text('Accept All'), button:has-text('Accept'), #onetrust-accept-btn-handler, #btnAccept").first
                if await cookie_btn.count() > 0:
                    await cookie_btn.click()
                    await page.wait_for_timeout(300)
            except Exception:
                pass

            # Fill keywords
            kw_input = page.locator("#txtKey, input[name*='txtKey']").first
            if await kw_input.count() > 0:
                await kw_input.fill(role)

            loc_input = page.locator("#txtLoc, input[name*='txtLoc']").first
            if await loc_input.count() > 0:
                await loc_input.fill(location)

            try:
                age_select = page.locator("#selAge, select[name*='selAge']").first
                if await age_select.count() > 0:
                    await age_select.select_option(value=age_val)
            except Exception:
                pass

            # Submit
            search_btn = page.locator("#btnSearch, input[value='Search'], button:has-text('Search')").first
            if await search_btn.count() > 0:
                await search_btn.click()
            else:
                await page.keyboard.press("Enter")

            # Iterate through paginated search results
            for page_num in range(1, 15):
                if len(collected_jobs) >= target_count:
                    break

                try:
                    await page.wait_for_selector(".jobItem, tr[id^='job_'], div[id^='job_'], #JobResults", timeout=10000)
                    await page.wait_for_timeout(1000)
                except Exception:
                    print(f"  Reached last page at page {page_num}.")
                    break

                # Extract job list elements on current page
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

                print(f"\n  📄 [Page {page_num}] Discovered {len(raw_items)} listings on page. Current total: {len(collected_jobs)}/{target_count}")

                added_this_page = 0
                for item in raw_items:
                    if len(collected_jobs) >= target_count:
                        break

                    div_id = item["id"]
                    job_title = item["title"]
                    raw_text = item["rawText"]

                    if not div_id or not job_title:
                        continue

                    # Pre-filter: snippet hash & canonical title
                    snip_sig = hashlib.md5(raw_text[:140].encode('utf-8')).hexdigest()
                    if snip_sig in seen_snippet_hashes:
                        continue
                    seen_snippet_hashes.add(snip_sig)

                    clean_title = _clean_key(job_title)
                    if clean_title in seen_canonical_keys:
                        continue

                    # Click item to load preview pane
                    try:
                        job_el = page.locator(f"#{div_id}").first
                        if await job_el.count() > 0:
                            await job_el.click()
                            await page.wait_for_timeout(700)
                    except Exception:
                        pass

                    # Read preview pane
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
                    job_loc = loc_elem.get_text(strip=True) if loc_elem else location

                    rate_elem = soup.select_one("#td_job_rate, .job_rate, .rate, .salary")
                    rate = rate_elem.get_text(strip=True) if rate_elem else "Competitive"

                    date_elem = soup.select_one("#td_posted_date, .posted_date, .date")
                    posted_date = date_elem.get_text(strip=True) if date_elem else f"Last {timeframe}"

                    url_elem = soup.select_one("#td_jobpositionlink, a[id*='positionlink']")
                    href = url_elem.get("href", "") if url_elem else ""
                    full_url = urllib.parse.urljoin("https://www.jobserve.com", href) if href else f"https://www.jobserve.com/{div_id}"

                    jd_elem = soup.select_one("#JobDetails, .job_description, .jobdetails")
                    description = jd_elem.get_text(separator="\n", strip=True) if jd_elem else soup.get_text(separator="\n", strip=True)

                    if len(description) < 100:
                        description = raw_text

                    # Post-filter: JD content hash
                    jd_sig = hashlib.md5(description[:250].encode('utf-8')).hexdigest()
                    if jd_sig in seen_jd_hashes:
                        continue
                    seen_jd_hashes.add(jd_sig)

                    # Canonical key
                    canonical_key = f"{_clean_key(title)}|{_clean_key(company)}"
                    if canonical_key in seen_canonical_keys:
                        continue
                    seen_canonical_keys.add(canonical_key)
                    seen_canonical_keys.add(clean_title)

                    # Rate extraction
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
                        "role": role,
                        "platform": "Jobserve"
                    }
                    added_this_page += 1
                    print(f"    ✓ [{len(collected_jobs)}/{target_count}] {title[:40]} | {rate[:18]}")

                # Paginate to Next Page if target not reached
                if len(collected_jobs) < target_count:
                    next_btn = page.locator("a:has-text('Next'), a#btnNext, a.pagerNext, #ctl00_main_srch_ctl_qs_btnNext").first
                    if await next_btn.count() > 0:
                        print(f"  -> Clicking Next Page to Page {page_num + 1}...")
                        await next_btn.click()
                        await page.wait_for_timeout(2000)
                    else:
                        print(f"  No 'Next Page' button found. Sweep complete.")
                        break

        except Exception as e:
            print(f"  Error during ingestion for role '{role}': {e}")
        finally:
            await browser.close()

    print(f"\n[Ingestion Complete] ✓ Successfully collected {len(collected_jobs)} strictly unique jobs for '{role}'.")
    return list(collected_jobs.values())


def score_and_rank_jobs(jobs: List[Dict[str, Any]], candidate_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Runs full deterministic ATS scoring across all collected jobs."""
    print(f"\n[ATS Engine] 🎯 Scoring {len(jobs)} jobs against candidate profile...")
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


def generate_shortlist_report(role: str, ranked_jobs: List[Dict[str, Any]], top_n: int = 30) -> str:
    """Generates Markdown Shortlist Report for the role."""
    report = []
    report.append(f"# 🎯 Jobserve 100 Shortlist Report: {role}\n")
    report.append(f"**Target Role:** `{role}` | **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} | **Total Evaluated:** {len(ranked_jobs)} Unique Jobs\n")
    report.append("--- \n")
    report.append(f"## 🏆 Top {min(top_n, len(ranked_jobs))} Shortlisted Opportunities\n")
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
        report.append(f"- **Direct Application URL:** [{j['url']}]({j['url']})")
        report.append(f"- **JD Excerpt:**\n> {j['description'][:280]}...\n")
        report.append("---\n")

    return "\n".join(report)


async def main():
    parser = argparse.ArgumentParser(description="Jobserve Dedicated Role 100 Shortlist Suite")
    parser.add_argument("--role", default="AI Engineer", help="Specific role to search (e.g. 'AI Engineer', 'Machine Learning Engineer')")
    parser.add_argument("--location", default="UK", help="Location (e.g. 'UK', 'London')")
    parser.add_argument("--timeframe", default="1m", choices=["24h", "48h", "1w", "1m"], help="Timeframe filter")
    parser.add_argument("--target", type=int, default=100, help="Target number of unique jobs to collect")
    args = parser.parse_args()

    print("=" * 80)
    print(f" Jobserve Single-Role 100 Suite: Role='{args.role}' | Location='{args.location}' | Timeframe='{args.timeframe}'")
    print("=" * 80)

    profile = load_candidate_profile()
    print(f"Candidate Profile: {profile.get('name')} ({len(profile.get('skills', []))} skills).")

    # Ingestion phase (paginated until target count reached)
    jobs = await collect_100_jobs_for_role(
        role=args.role,
        location=args.location,
        timeframe=args.timeframe,
        target_count=args.target
    )

    if not jobs:
        print(f"✕ No jobs collected for role '{args.role}'.")
        return

    # ATS Scoring
    ranked_jobs = score_and_rank_jobs(jobs, profile)

    clean_role = re.sub(r'[^a-zA-Z0-9]', '_', args.role.lower()).strip('_')
    json_path = f"jobserve_100_{clean_role}.json"
    report_path = f"jobserve_shortlist_{clean_role}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ranked_jobs, f, indent=2)
    print(f"\n✓ Saved {len(ranked_jobs)} scored jobs to {json_path}")

    report_md = generate_shortlist_report(args.role, ranked_jobs, top_n=30)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"✓ Saved Shortlist Report to {report_path}")

    print("\n" + "=" * 90)
    print(f" Top 20 Shortlisted Jobs for Role: '{args.role}' (Total Evaluated: {len(ranked_jobs)})")
    print("=" * 90)
    print(f"{'#':<3} | {'ATS Score':<10} | {'Skills Fit':<12} | {'Rate / Salary':<22} | {'Job Title'}")
    print("-" * 90)
    for idx, j in enumerate(ranked_jobs[:20], 1):
        print(f"{idx:<3} | {j['overall_score']:<10}% | {j['skills_score']:<12}% | {j['rate'][:20]:<22} | {j['title'][:35]}")


if __name__ == "__main__":
    asyncio.run(main())
