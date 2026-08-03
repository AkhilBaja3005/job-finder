import os
import json
import urllib.parse
import urllib.request
import re
import asyncio
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
from typing import List, Optional, Dict
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from services.gemini_client import generate_content_with_fallback
from services.ats_scorer import (
    compute_ats_score, compute_overall_score, calculate_flattened_experience,
    estimate_role_fit_score, _extract_taxonomy_skills, get_candidate_seniority_tier,
    _COMPILED_TITLE_TIER_PATTERNS
)
from services.scraper import scrape_job_description
from services.recruiter_extractor import extract_recruiter
from utils.ssl_utils import SSL_CONTEXT

# ─── Pydantic Schemas for Search ──────────────────────────────────────────

class SearchQueries(BaseModel):
    queries: List[str] = Field(
        description="3-5 optimized job search keywords (e.g. ['Machine Learning Engineer', 'Generative AI Engineer'])"
    )

class JobSearchResult(BaseModel):
    title: str
    company: str
    location: str
    url: str
    platform: str
    post_date_raw: str
    job_id: str

# ─── Query Generation from Resume ─────────────────────────────────────────

def generate_search_queries_from_resume(resume_data: dict, custom_api_key: Optional[str] = None) -> List[str]:
    """Uses Gemini to extract 3-5 optimized search queries based on the candidate's skills and roles."""
    skills = resume_data.get("skills", [])
    recent_roles = [exp.get("role", "") for exp in resume_data.get("experience", [])[:2]]
    
    prompt = f"""Given the candidate skills and recent job roles, generate 3-5 high-converting job search queries (keywords) for hiring search engines.
    Make sure to cover related job domains including Data Science, Machine Learning, AI Engineering, and Data Engineering to discover similar listings.
    
    Skills: {', '.join(skills)}
    Recent Roles: {', '.join(recent_roles)}
    
    Respond with the JSON format matching the schema. Keep queries clean (no quotation marks, e.g. \"Generative AI Engineer\").
    """
    try:
        response = generate_content_with_fallback(prompt, SearchQueries, custom_api_key)
        res = json.loads(response)
        return res.get("queries", [recent_roles[0]] if recent_roles else ["Software Engineer"])
    except Exception as e:
        print(f"[Job Searcher] Failed to generate queries: {e}")
        # Default fallbacks
        return [recent_roles[0]] if recent_roles else ["Software Engineer"]

# ─── LinkedIn Scraper (Unauthenticated API) ───────────────────────────────

def search_linkedin_jobs(keyword: str, location: str = "Remote", timeframe: str = "48h") -> List[JobSearchResult]:
    """Scrapes LinkedIn's guest job search API for postings from the specified timeframe."""
    encoded_keyword = urllib.parse.quote(keyword)
    encoded_location = urllib.parse.quote(location)
    
    # Map timeframe to LinkedIn f_TPR parameter (seconds)
    tpr_map = {
        "24h": "r86400",
        "48h": "r172800",
        "1w": "r604800",
        "1m": "r2592000"
    }
    tpr = tpr_map.get(timeframe, "r172800")
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={encoded_keyword}&location={encoded_location}&f_TPR={tpr}&start=0"
    
    print(f"[Job Searcher] Fetching LinkedIn: {url}")
    results = []
    
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
        )
        context = SSL_CONTEXT
        with urllib.request.urlopen(req, context=context, timeout=12) as response:
            html = response.read().decode("utf-8")
            
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("li")
        
        for card in cards:
            title_elem = card.select_one(".base-search-card__title")
            company_elem = card.select_one(".base-search-card__subtitle")
            location_elem = card.select_one(".job-search-card__location")
            link_elem = card.select_one(".base-card__full-link")
            date_elem = card.select_one(".job-search-card__listdate, .job-search-card__listdate--new")
            
            if not title_elem or not link_elem:
                continue
                
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"
            loc = location_elem.get_text(strip=True) if location_elem else location
            href = link_elem.get("href", "").split("?")[0] # Clean query trackers
            date_str = date_elem.get_text(strip=True) if date_elem else "Just posted"
            
            # Extract job ID from href URN
            job_id_match = re.search(r"-(\d+)$", href)
            job_id = job_id_match.group(1) if job_id_match else href.split("/")[-1]
            
            results.append(JobSearchResult(
                title=title,
                company=company,
                location=loc,
                url=href,
                platform="LinkedIn",
                post_date_raw=date_str,
                job_id=job_id
            ))
            
    except Exception as e:
        print(f"[Job Searcher] LinkedIn search error: {e}")
        
    return results

# ─── Reed.co.uk Official API Integration ──────────────────────────────────────

REED_API_KEY = os.getenv("REED_API_KEY")

def search_reed_jobs(keyword: str, location: str = "London", timeframe: str = "48h") -> List[JobSearchResult]:
    """Queries official Reed.co.uk API for live UK job postings filtered by timeframe."""
    if not REED_API_KEY:
        print("[Job Searcher] REED_API_KEY not configured. Skipping Reed search.")
        return []

    encoded_keyword = urllib.parse.quote(keyword)
    encoded_location = urllib.parse.quote(location)
    
    # Calculate cutoff date based on requested timeframe
    from datetime import datetime, timedelta
    days = 2
    if timeframe == "24h":
        days = 1
    elif timeframe == "48h":
        days = 2
    elif timeframe == "1w":
        days = 7
    elif timeframe == "1m":
        days = 30
        
    cutoff_date = datetime.now() - timedelta(days=days)

    url = f"https://www.reed.co.uk/api/1.0/search?keywords={encoded_keyword}&locationName={encoded_location}&resultsToTake=100"
    
    print(f"[Job Searcher] Fetching Reed API ({timeframe}): {url}")
    results = []
    
    import base64
    auth_str = f"{REED_API_KEY}:"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "User-Agent": "JobFinderApp/1.0"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for job in data.get("results", []):
                title = job.get("jobTitle", "Job Posting")
                company = job.get("employerName", "Reed Employer")
                
                # Filter out spam/course training company listings (e.g. "Newto Training")
                if "newto training" in company.lower() or "newto" in company.lower():
                    continue

                loc = job.get("locationName", location)
                job_url = job.get("jobUrl", "")
                job_id = str(job.get("jobId", job_url))
                post_date_str = job.get("date", "")
                job_dt = None
                if post_date_str:
                    try:
                        job_dt = datetime.strptime(post_date_str, "%d/%m/%Y")
                        if job_dt < cutoff_date:
                            continue
                    except Exception:
                        pass
                
                results.append({
                    "job": JobSearchResult(
                        title=title,
                        company=company,
                        location=loc,
                        url=job_url,
                        platform="Reed",
                        post_date_raw=post_date_str or "Recent",
                        job_id=job_id
                    ),
                    "dt": job_dt or datetime.min
                })

            # Sort by post date descending (newest jobs first)
            results.sort(key=lambda x: x["dt"], reverse=True)
            final_jobs = [r["job"] for r in results[:20]]
            print(f"[Job Searcher] ✓ Reed API returned {len(final_jobs)} fresh jobs within {timeframe} for '{keyword}' (sorted newest first)")
            return final_jobs
    except Exception as e:
        print(f"[Job Searcher] Reed API search error: {e}")

    return []

# ─── Indeed Scraper ───────────────────────────────────────────────────────

# ─── Indeed Scraper (Playwright Stealth Browser) ───────────────────────────

def _is_local_deployment() -> bool:
    if any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME")):
        return False
    frontend_url = os.getenv("FRONTEND_URL", "")
    return "localhost" in frontend_url or "127.0.0.1" in frontend_url

async def search_indeed_jobs(keyword: str, location: str = "Remote", timeframe: str = "48h") -> List[JobSearchResult]:
    """Scrapes Indeed public job postings from specified timeframe using Playwright browser emulations."""
    if not _is_local_deployment():
        print("[Job Searcher] Non-local/cloud deployment detected. Skipping Indeed scraping (cloud IP ranges blocked by Indeed).")
        return []

    encoded_keyword = urllib.parse.quote(keyword)
    encoded_location = urllib.parse.quote(location)
    
    # Map timeframe to Indeed fromage parameter (days)
    fromage_map = {
        "24h": "1",
        "48h": "2",
        "1w": "7",
        "1m": "30"
    }
    fromage = fromage_map.get(timeframe, "2")
    url = f"https://www.indeed.com/jobs?q={encoded_keyword}&l={encoded_location}&fromage={fromage}"
    
    print(f"[Job Searcher] Fetching Indeed via Playwright: {url}")
    results = []

    # pyrefly: ignore [missing-import]
    from playwright.async_api import async_playwright

    html = ""
    page_title = ""
    status = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                    "--ignore-certificate-errors-spki-list"
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                has_touch=False,
                is_mobile=False,
                locale="en-US",
                timezone_id="Asia/Kolkata"
            )
            page = await context.new_page()

            # Inject enhanced anti-bot evasion scripts
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
            """)

            response = None
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=8000)
            except Exception as e:
                print(f"[Job Searcher] Indeed navigation timed out, checking loaded content: {e}")

            await page.wait_for_timeout(500)
            html = await page.content()
            page_title = await page.title()
            status = response.status if response else None
            await browser.close()
    except Exception as pw_err:
        print(f"[Job Searcher] Playwright browser launch skipped ({pw_err}). Proceeding to search fallback.")
        page_title = "Just a moment..."
        status = 403

    try:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".job_seen_beacon")

        if not cards and (status == 403 or "blocked" in page_title.lower() or "just a moment" in page_title.lower()):
            print(f"[Job Searcher] Indeed Cloudflare Challenge triggered (status={status}, title={page_title!r}). "
                  f"LinkedIn, Reed search remains 100% active and operational.")
            return results

        for card in cards:
            title_elem = card.select_one(".jobTitle a span[title]") or card.select_one(".jobTitle a")
            company_elem = card.select_one("[data-testid='company-name']")
            location_elem = card.select_one("[data-testid='text-location']")
            link_elem = card.select_one("a.jcs-JobTitle") or card.select_one(".jobTitle a")
            date_elem = card.select_one(".date")
            
            if not title_elem or not link_elem:
                continue
                
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"
            loc = location_elem.get_text(strip=True) if location_elem else location
            jk = link_elem.get("data-jk", "")
            href = f"https://www.indeed.com/viewjob?jk={jk}" if jk else "https://www.indeed.com"
            date_str = date_elem.get_text(strip=True) if date_elem else "2 days ago"
            
            results.append(JobSearchResult(
                title=title,
                company=company,
                location=loc,
                url=href,
                platform="Indeed",
                post_date_raw=date_str,
                job_id=jk or href
            ))
            
    except Exception as e:
        print(f"[Job Searcher] Indeed search error: {e}")
        
    return results

# ─── Combined Aggregation & Scoring Pipeline ──────────────────────────────

DISCOVERY_JD_FETCH_CAP = 30
# Dynamically scale concurrency based on the hosting environment:
# - We check for an explicit override environment variable SCRAPER_CONCURRENCY
# - Render automatically injects "RENDER" into all web service environments under the hood.
# - If none is found, we fall back to 5 for local runs.
try:
    env_concurrency = os.getenv("SCRAPER_CONCURRENCY")
    if env_concurrency is not None:
        DISCOVERY_FETCH_CONCURRENCY = int(env_concurrency)
    else:
        # Detect if running locally by checking the FRONTEND_URL value
        frontend_url = os.getenv("FRONTEND_URL", "")
        is_local = "localhost" in frontend_url or "127.0.0.1" in frontend_url
        DISCOVERY_FETCH_CONCURRENCY = 5 if is_local else 8
except Exception:
    DISCOVERY_FETCH_CONCURRENCY = 8


def _title_heuristic_score(job: JobSearchResult, resume_data: dict) -> int:
    """
    Cheap title-only pre-rank used ONLY to decide which jobs are worth the cost
    of fetching their real JD (see DISCOVERY_JD_FETCH_CAP below) — NOT the final
    displayed score, which always comes from compute_ats_score() against the
    actual job description via _score_job_with_real_jd, same as Tailor Resume.

    Derived generically from the candidate's own resume (skill-alias matches in
    the title + seniority-tier alignment via the existing ats_scorer taxonomy)
    rather than hardcoded domain keywords, so it ranks fairly regardless of
    whether the candidate is in data/ML, frontend, backend, etc.
    """
    title_lower = job.title.lower()

    resume_skill_set = _extract_taxonomy_skills(" ".join(resume_data.get("skills", [])))
    title_skill_set = _extract_taxonomy_skills(title_lower)
    matched_count = len(resume_skill_set & title_skill_set)

    candidate_tier = get_candidate_seniority_tier(resume_data)
    tier_hierarchy = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "executive": 5}
    title_tier = "mid"
    for tier, pattern in _COMPILED_TITLE_TIER_PATTERNS:
        if pattern.search(title_lower):
            title_tier = tier
            break
    tier_gap = abs(tier_hierarchy.get(candidate_tier, 2) - tier_hierarchy.get(title_tier, 2))

    return 70 + (matched_count * 8) - (tier_gap * 10)


async def _score_job_with_real_jd(job: JobSearchResult, resume_data: dict, browser, semaphore: asyncio.Semaphore) -> Optional[dict]:
    """Fetches the real JD for a single job and scores it with the exact same
    deterministic engine (compute_ats_score / compute_overall_score) that the
    Tailor Resume flow uses, so discovery's overall score is directly comparable
    to the ATS score shown after tailoring — not a separately-invented estimate."""
    async with semaphore:
        try:
            scraped = await scrape_job_description(job.url, browser=browser)
        except Exception as e:
            print(f"[Job Searcher] Failed to fetch JD for '{job.title}' at {job.url}: {e}")
            return None

    jd_text = scraped.get("description", "")
    if not jd_text or len(jd_text.strip()) < 100:
        return None

    ats = compute_ats_score(resume_data, jd_text)
    if not ats.eligible:
        return None
    role_fit = estimate_role_fit_score(resume_data, jd_text)
    overall_score = compute_overall_score(ats.skills_score, ats.experience_score, role_fit)

    recruiter_name = None
    recruiter_profile_url = None
    if job.platform == "LinkedIn":
        try:
            recruiter_info = await extract_recruiter(job.url, platform="linkedin", html=scraped.get("html"), browser=browser)
            recruiter_name = recruiter_info.get("recruiter_name")
            recruiter_profile_url = recruiter_info.get("recruiter_profile_url")
        except Exception as e:
            print(f"[Job Searcher] Failed to extract recruiter info for '{job.title}': {e}")

    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "platform": job.platform,
        "age": job.post_date_raw,
        "score": overall_score,
        "skills_score": ats.skills_score,
        "experience_score": ats.experience_score,
        "role_fit_score": role_fit,
        "candidate_years": ats.candidate_years,
        "required_years": ats.required_years,
        "matched_skills": ats.matched_skills,
        "missing_skills": ats.missing_skills,
        "estimated": False,
        "recruiter_name": recruiter_name,
        "recruiter_profile_url": recruiter_profile_url,
    }


def _score_job_with_title_heuristic(job: JobSearchResult, resume_data: dict) -> dict:
    """Fallback scoring for jobs past the JD-fetch cap — no JD text is available,
    so this derives everything from taxonomy skill matches in the title (same
    SKILL_ALIASES taxonomy compute_ats_score uses) rather than hardcoded domain
    keywords, so it isn't biased toward any one field (e.g. data/ML). Tagged
    estimated=True so the UI can visually distinguish it from a real ATS-scored
    result rather than silently presenting it as equally accurate."""
    title_lower = job.title.lower()

    resume_skill_set = _extract_taxonomy_skills(" ".join(resume_data.get("skills", [])))
    title_skill_set = _extract_taxonomy_skills(title_lower)
    matched_skills = sorted(resume_skill_set & title_skill_set)
    missing_skills = sorted(title_skill_set - resume_skill_set)

    total_title_skills = len(title_skill_set) or 1
    # If the title has no recognizable taxonomy skill keywords at all (e.g. a
    # role-flavor title like "AI-Native Product Engineer" instead of a
    # tech-stack title), there's nothing to actually measure — use the same
    # neutral default as compute_skills_score's unscoreable-JD case, and don't
    # imply a real 0/0 skill match ratio behind a misleadingly high percentage.
    skills_score = max(40, min(95, int((len(matched_skills) / total_title_skills) * 100))) if title_skill_set else 60

    cand_years, avg_tenure, weighted_segments = calculate_flattened_experience(resume_data)

    req_years = 2
    title_years_match = re.search(r'(\d+)\s*(?:\+|to|-)?\s*\d*\s*(?:year|yr|y/o)', title_lower)
    if title_years_match:
        try:
            req_years = int(title_years_match.group(1))
        except ValueError:
            pass
    else:
        candidate_tier = get_candidate_seniority_tier(resume_data)
        title_tier = "mid"
        for tier, pattern in _COMPILED_TITLE_TIER_PATTERNS:
            if pattern.search(title_lower):
                title_tier = tier
                break
        req_years = 5 if title_tier in ("senior", "lead", "executive") else 2

    experience_score = 95
    if cand_years < req_years:
        experience_score = max(40, 95 - int((req_years - cand_years) * 10))
    elif cand_years > req_years + 3:
        experience_score = 85

    role_fit_score = estimate_role_fit_score(resume_data, job.title)

    overall_score = int(0.40 * skills_score + 0.35 * experience_score + 0.25 * role_fit_score)

    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "platform": job.platform,
        "age": job.post_date_raw,
        "score": overall_score,
        "skills_score": skills_score,
        "experience_score": experience_score,
        "role_fit_score": role_fit_score,
        "candidate_years": cand_years,
        "required_years": req_years,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "estimated": True,
    }



async def find_matching_jobs(
    resume_data: dict,
    location: str = "Remote",
    keywords: Optional[str] = None,
    timeframe: str = "48h",
    custom_api_key: Optional[str] = None
):
    """
    Main aggregator pipeline:
    1. Resolves search queries (either user-entered keywords or auto-generates from resume).
    2. Fetches LinkedIn & Indeed postings concurrently.
    3. Ranks by a cheap title heuristic, then fetches the real JD for the top
       DISCOVERY_JD_FETCH_CAP jobs and scores them with the SAME deterministic
       engine (compute_ats_score/compute_overall_score) used by Tailor Resume,
       so discovery's overall score is directly comparable — not a separately
       invented number. Jobs beyond the cap fall back to a title-only estimate
       and are tagged estimated=True.
    4. Filters and returns job matches >= 55%.
    """
    if keywords and keywords.strip():
        # User-provided search role overrides
        queries = [q.strip() for q in keywords.split(",") if q.strip()]
        yield json.dumps({"type": "log", "message": f"🔎 Using user-preferred search queries: {', '.join(queries)}"}) + "\n"
    else:
        yield json.dumps({"type": "log", "message": "🤖 Analyzing resume context to generate optimal search queries..."}) + "\n"
        queries = generate_search_queries_from_resume(resume_data, custom_api_key)
        yield json.dumps({"type": "log", "message": f"🔎 Generated search queries: {', '.join(queries)}"}) + "\n"

    raw_jobs = []
    indeed_jobs_for_est = []  # Store Indeed jobs for EST section

    async def _fetch_query(query: str):
        yield_msg = f"🌐 Fetching listings from LinkedIn & Reed.co.uk ({timeframe}) for '{query}'..."
        li_task = asyncio.to_thread(search_linkedin_jobs, query, location, timeframe)
        reed_task = asyncio.to_thread(search_reed_jobs, query, location, timeframe)
        ind_task = search_indeed_jobs(query, location, timeframe)
        li_jobs, reed_jobs, ind_jobs = await asyncio.gather(li_task, reed_task, ind_task)
        return yield_msg, li_jobs, reed_jobs, ind_jobs

    query_results = await asyncio.gather(*[_fetch_query(q) for q in queries])
    for yield_msg, li_jobs, reed_jobs, ind_jobs in query_results:
        yield json.dumps({"type": "log", "message": yield_msg}) + "\n"
        raw_jobs.extend(li_jobs)
        raw_jobs.extend(reed_jobs)
        raw_jobs.extend(ind_jobs)

    # Deduplicate by job URL / ID
    seen_ids = set()
    deduped_jobs = []
    for job in raw_jobs:
        if job.job_id not in seen_ids:
            seen_ids.add(job.job_id)
            deduped_jobs.append(job)

    yield json.dumps({"type": "log", "message": f"📊 Found {len(deduped_jobs)} unique postings. Computing ATS matches..."}) + "\n"

    deduped_jobs.sort(key=lambda j: _title_heuristic_score(j, resume_data), reverse=True)

    jd_scored_batch = deduped_jobs[:DISCOVERY_JD_FETCH_CAP]
    title_only_batch = deduped_jobs[DISCOVERY_JD_FETCH_CAP:]

    scored_jobs = []
    if jd_scored_batch:
        yield json.dumps({"type": "log", "message": f"📄 Fetching real job descriptions for top {len(jd_scored_batch)} matches to compute accurate ATS scores..."}) + "\n"
        # pyrefly: ignore [missing-import]
        from playwright.async_api import async_playwright
        semaphore = asyncio.Semaphore(DISCOVERY_FETCH_CONCURRENCY)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                results = await asyncio.gather(*[
                    _score_job_with_real_jd(job, resume_data, browser, semaphore) for job in jd_scored_batch
                ])
            finally:
                await browser.close()
        scored_jobs.extend([r for r in results if r is not None])

    if title_only_batch:
        yield json.dumps({"type": "log", "message": f"📝 Estimating {len(title_only_batch)} additional matches from title only (beyond the {DISCOVERY_JD_FETCH_CAP}-job accurate-scan cap)..."}) + "\n"
        scored_jobs.extend([_score_job_with_title_heuristic(job, resume_data) for job in title_only_batch])

    scored_jobs = [j for j in scored_jobs if j["score"] >= 55]

    # Sort accurate (JD-scored) jobs before estimated (title-only) ones, since
    # an estimated job's raw score isn't directly comparable to a real
    # ATS-scored one — within each group, sort descending by score.
    scored_jobs.sort(key=lambda x: (x["estimated"], -x["score"]))
    accurate_count = sum(1 for j in scored_jobs if not j["estimated"])
    estimated_count = len(scored_jobs) - accurate_count
    yield json.dumps({"type": "log", "message": f"🏁 Scanned {len(scored_jobs)} matches successfully! ({accurate_count} JD-scored, {estimated_count} title-estimated)"}) + "\n"

    # Prepare EST (External Sources - Indeed) section
    est_jobs = []
    if indeed_jobs_for_est:
        # Deduplicate Indeed jobs
        seen_indeed_ids = set()
        for job in indeed_jobs_for_est:
            if job.job_id not in seen_indeed_ids:
                seen_indeed_ids.add(job.job_id)
                est_jobs.append({
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "url": job.url,
                    "source": "Indeed",
                    "posted_date": job.post_date_raw,
                    "score": 0,  # Not scored - external source
                    "estimated": True,
                    "reason": "External source (Indeed) - not scored by our ATS engine"
                })
        yield json.dumps({"type": "log", "message": f"📌 Found {len(est_jobs)} Indeed jobs in EST section (not scored by our engine)"}) + "\n"

    yield json.dumps({"type": "result", "jobs": scored_jobs, "est_jobs": est_jobs}) + "\n"

