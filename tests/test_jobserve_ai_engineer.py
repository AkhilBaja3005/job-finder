#!/usr/bin/env python3
"""
test_jobserve_ai_engineer.py - End-to-End Jobserve Discovery & ATS Scoring Suite.

Searches Jobserve for "AI Engineer" across configurable timeframes (24h, 48h, 1w, 1m),
extracts all Job Descriptions, and computes ATS Match Scores & Skill Gaps.
"""

import sys
import os
import re
import json
import asyncio
import urllib.parse
from typing import List, Dict, Any

# Ensure backend modules are on sys.path
sys.path.insert(0, os.path.abspath("backend"))

from bs4 import BeautifulSoup
from utils.ssl_utils import SSL_CONTEXT
from services.ats_scorer import compute_ats_score, compute_overall_score, _extract_taxonomy_skills

# Age parameter mapping for Jobserve
TIMEFRAME_MAP = {
    "24h": "1",    # 1 day / Today
    "48h": "2",    # 2 days
    "1w": "7",     # 1 week / 7 days
    "1m": "30",    # 1 month / 30 days
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def load_candidate_profile() -> Dict[str, Any]:
    """Loads existing candidate profile or returns a robust AI Engineer profile."""
    return {
        "name": "Akhil Baja",
        "skills": [
            "Python", "PyTorch", "TensorFlow", "Generative AI", "LLM", "RAG",
            "Agentic AI", "LangChain", "Vector Databases", "FastAPI", "Docker",
            "Kubernetes", "AWS", "Machine Learning", "Deep Learning", "NLP",
            "PostgreSQL", "Redis", "TypeScript", "React", "CI/CD", "Git", "Azure"
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
                "company": "AI Technologies",
                "role": "Senior AI Engineer",
                "start_date": "01/2021",
                "end_date": "10/2026",
                "skills": ["Python", "PyTorch", "LLM", "RAG", "Agentic AI", "LangChain", "Vector Databases", "FastAPI", "Docker", "AWS"],
                "description": "Architected LLM pipelines, RAG frameworks, and autonomous multi-agent systems using Python, PyTorch, LangChain, and vector databases."
            }
        ]
    }


async def search_jobserve(
    keyword: str = "AI Engineer",
    location: str = "London",
    timeframe: str = "1w",
    max_jobs: int = 20
) -> List[Dict[str, Any]]:
    """
    Automates Jobserve search with specific keyword, location, and age filter,
    then retrieves full JD HTML for each discovered listing.
    """
    from playwright.async_api import async_playwright

    age_val = TIMEFRAME_MAP.get(timeframe.lower(), "7")
    print(f"\n[Jobserve Engine] Initializing search: keyword='{keyword}', location='{location}', timeframe='{timeframe}' (age={age_val} days)...")

    results: List[Dict[str, Any]] = []

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

        # Intercept job detail responses
        job_details_map: Dict[str, str] = {}

        async def on_response(resp):
            if "retrievesinglejobdetail" in resp.url.lower():
                try:
                    data = await resp.json()
                    if isinstance(data, dict) and "d" in data:
                        d_val = data["d"]
                        html = d_val.get("JobDetailHtml", "")
                        if html:
                            # Extract Job ID or position title from HTML
                            m_id = re.search(r'id=["\']td_jobpositionlink["\'].*?href=["\']/([a-zA-Z0-9_-]+)["\']', html)
                            if m_id:
                                job_details_map[m_id.group(1)] = html
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            search_url = "https://www.jobserve.com/gb/en/Job-Search/"
            await page.goto(search_url, wait_until="networkidle", timeout=20000)

            # Accept cookies
            try:
                cookie_btn = page.locator("a:has-text('Accept All'), button:has-text('Accept'), #onetrust-accept-btn-handler, #btnAccept, a.cookieConsentOK")
                if await cookie_btn.count() > 0:
                    await cookie_btn.first.click()
                    await page.wait_for_timeout(500)
            except Exception:
                pass

            # Fill Keywords
            kw_input = page.locator("#txtKey, input[name*='txtKey'], #keywords").first
            if await kw_input.count() > 0:
                await kw_input.fill(keyword)

            # Fill Location
            loc_input = page.locator("#txtLoc, input[name*='txtLoc'], #location").first
            if await loc_input.count() > 0:
                await loc_input.fill(location)

            # Set Age / Timeframe if available
            try:
                age_select = page.locator("#selAge, select[name*='selAge'], #ddcl-selAge").first
                if await age_select.count() > 0:
                    await age_select.select_option(value=age_val)
                    print(f"  ✓ Selected timeframe filter: {timeframe} ({age_val} days)")
            except Exception as age_err:
                print(f"  (Note: could not set age selector: {age_err})")

            # Click Search
            search_btn = page.locator("#btnSearch, input[value='Search'], button:has-text('Search')").first
            if await search_btn.count() > 0:
                await search_btn.click()
            else:
                await page.keyboard.press("Enter")

            # Wait for results
            await page.wait_for_selector(".jobItem, tr[id^='job_'], div[id^='job_'], #JobResults", timeout=12000)
            await page.wait_for_timeout(2000)

            # Extract job items from the search list
            raw_job_items = await page.evaluate('''() => {
                const items = [];
                const jobDivs = document.querySelectorAll(".jobItem, tr[id^='job_'], div[id^='job_']");
                jobDivs.forEach(div => {
                    const id = div.id || "";
                    const titleEl = div.querySelector("h3, .jobtitle, .positiontitle, a");
                    const title = titleEl ? titleEl.innerText.trim() : "";
                    const rawText = div.innerText;
                    items.push({ id, title, rawText });
                });
                return items;
            }''')

            print(f"  ✓ Discovered {len(raw_job_items)} jobs in Jobserve search results for '{timeframe}'.")

            # Iterate and click each job item to trigger detail loading in the preview pane
            limit = min(len(raw_job_items), max_jobs)
            for i in range(limit):
                item = raw_job_items[i]
                div_id = item["id"]
                job_title = item["title"]

                print(f"  [{i+1}/{limit}] Fetching JD for: {job_title[:60]}...")

                try:
                    # Click on the job item in the list
                    job_el = page.locator(f"#{div_id}").first
                    if await job_el.count() > 0:
                        await job_el.click()
                        await page.wait_for_timeout(1200)
                except Exception:
                    pass

                # Grab the currently displayed JobDetailPanel HTML
                detail_html = await page.evaluate('''() => {
                    const p = document.getElementById("JobDetailPanel");
                    return p ? p.innerHTML : "";
                }''')

                soup = BeautifulSoup(detail_html, "html.parser")
                
                # Extract components
                title_elem = soup.select_one("h1, .positiontitle, #td_jobpositionlink")
                title = title_elem.get_text(strip=True) if title_elem else job_title
                
                comp_elem = soup.select_one("#td_posted_by_name, .posted_by, .agency_name, .company_name")
                company = comp_elem.get_text(strip=True) if comp_elem else "Hiring Agency / Client"
                
                loc_elem = soup.select_one("#td_job_location, .job_location, .location")
                loc = loc_elem.get_text(strip=True) if loc_elem else location
                
                rate_elem = soup.select_one("#td_job_rate, .job_rate, .rate, .salary")
                rate = rate_elem.get_text(strip=True) if rate_elem else "Competitive"

                date_elem = soup.select_one("#td_posted_date, .posted_date, .date")
                posted_date = date_elem.get_text(strip=True) if date_elem else f"Last {timeframe}"

                url_elem = soup.select_one("#td_jobpositionlink, a[id*='positionlink']")
                href = url_elem.get("href", "") if url_elem else ""
                full_url = urllib.parse.urljoin("https://www.jobserve.com", href) if href else page.url

                # Clean JD text
                jd_elem = soup.select_one("#JobDetails, .job_description, .jobdetails")
                if jd_elem:
                    description = jd_elem.get_text(separator="\n", strip=True)
                else:
                    description = soup.get_text(separator="\n", strip=True)

                # Fallback if JobDetailPanel was not loaded yet
                if len(description) < 100:
                    description = item.get("rawText", "")

                # Enhanced rate extraction if default
                if rate in ["Competitive", "", "N/A"]:
                    rate_m = re.search(r'(?:£|\$|€)\s*\d+[\d,kK\.\s-]*(?:per\s+(?:day|hour|annum|month)|/day|/hr|/yr|k\b|annum\b)?', description)
                    if rate_m:
                        rate = rate_m.group(0).strip()

                results.append({
                    "job_id": div_id,
                    "title": title or job_title,
                    "company": company,
                    "location": loc,
                    "rate": rate,
                    "posted_date": posted_date,
                    "url": full_url,
                    "description": description,
                    "platform": "Jobserve"
                })

        except Exception as e:
            print(f"  ✕ Search error: {e}")
        finally:
            await browser.close()

    return results


def run_ats_scoring_suite(jobs: List[Dict[str, Any]], candidate_profile: Dict[str, Any]):
    """Runs the deterministic ATS Scorer across all extracted Jobserve jobs."""
    print("\n" + "=" * 90)
    print(" Jobserve ATS Scoring & Match Analysis")
    print("=" * 90)

    ranked_jobs = []
    
    for job in jobs:
        jd_text = job["description"]
        title = job["title"]
        
        try:
            # Deterministic ATS Scoring pipeline
            from services.ats_scorer import estimate_role_fit_score
            ats_res = compute_ats_score(resume_data=candidate_profile, jd_text=jd_text)
            
            skills_score = ats_res.skills_score
            exp_score = ats_res.experience_score
            role_fit = estimate_role_fit_score(candidate_profile, jd_text)
            overall_score = compute_overall_score(skills_score, exp_score, role_fit)
            
            # Extract skills present in JD
            jd_taxonomy = _extract_taxonomy_skills(jd_text)
            cand_skills_set = {s.lower() for s in candidate_profile.get("skills", [])}
            matched_skills = [s for s in jd_taxonomy if s.lower() in cand_skills_set]
            missing_skills = [s for s in jd_taxonomy if s.lower() not in cand_skills_set]

            ranked_jobs.append({
                **job,
                "overall_score": overall_score,
                "skills_score": skills_score,
                "experience_score": exp_score,
                "role_fit": role_fit,
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
                "fit_tier": "High Fit (>=75%)" if overall_score >= 75 else ("Moderate (60-74%)" if overall_score >= 60 else "Low (<60%)")
            })
        except Exception as ex:
            print(f"  Error scoring job '{title}': {ex}")

    # Sort descending by ATS overall score
    ranked_jobs.sort(key=lambda x: x.get("overall_score", 0), reverse=True)

    # Print Summary Table
    print(f"\nTotal Discovered & Scored: {len(ranked_jobs)} Jobs\n")
    print(f"{'#':<3} | {'ATS Score':<10} | {'Skills Score':<12} | {'Rate / Salary':<22} | {'Job Title & Location'}")
    print("-" * 90)

    for idx, r in enumerate(ranked_jobs, 1):
        score_str = f"{r['overall_score']:.1f}%"
        skills_str = f"{r['skills_score']:.1f}%"
        rate_str = r['rate'][:20]
        title_loc = f"{r['title'][:40]} ({r['location'][:15]})"
        print(f"{idx:<3} | {score_str:<10} | {skills_str:<12} | {rate_str:<22} | {title_loc}")

    print("\n" + "=" * 90)
    print(" Top Matching Opportunities Breakdown (Detailed View)")
    print("=" * 90)

    for idx, top in enumerate(ranked_jobs[:5], 1):
        print(f"\n[{idx}] {top['title']}")
        print(f"    Company:     {top['company']}")
        print(f"    Location:    {top['location']}")
        print(f"    Rate/Salary: {top['rate']}")
        print(f"    Posted:      {top['posted_date']}")
        print(f"    ATS Score:   {top['overall_score']:.1f}% ({top['fit_tier']})")
        print(f"    Matched:     {', '.join(top['matched_skills'][:8]) if top['matched_skills'] else 'N/A'}")
        print(f"    Skill Gaps:  {', '.join(top['missing_skills'][:6]) if top['missing_skills'] else 'None'}")
        print(f"    URL:         {top['url']}")
        print(f"    JD Excerpt:  {top['description'][:200]}...")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Jobserve AI Engineer ATS Discovery")
    parser.add_argument("--keyword", default="AI Engineer", help="Job keyword (e.g. 'AI Engineer', 'Python Developer')")
    parser.add_argument("--location", default="London", help="Location (e.g. 'London', 'Remote')")
    parser.add_argument("--timeframe", default="1w", choices=["24h", "48h", "1w", "1m"], help="Posted timeframe")
    parser.add_argument("--max", type=int, default=15, help="Max jobs to fetch and score")
    args = parser.parse_args()

    print("=" * 90)
    print(f" Jobserve ATS Discovery Suite: Keyword='{args.keyword}' | Location='{args.location}' | Timeframe='{args.timeframe}'")
    print("=" * 90)

    profile = load_candidate_profile()
    jobs = await search_jobserve(
        keyword=args.keyword,
        location=args.location,
        timeframe=args.timeframe,
        max_jobs=args.max
    )

    if not jobs:
        print("\n✕ No jobs extracted. Retrying with broad search...")
        jobs = await search_jobserve(keyword=args.keyword, location="", timeframe=args.timeframe, max_jobs=args.max)

    if jobs:
        run_ats_scoring_suite(jobs, profile)
    else:
        print("\n✕ Could not retrieve listings for the specified criteria.")


if __name__ == "__main__":
    asyncio.run(main())
