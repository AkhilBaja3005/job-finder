import os
import json
import urllib.parse
import urllib.request
import re
import asyncio
import hashlib
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any
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
from utils.ttl_cache import TTLCache
from utils.location_resolver import get_indeed_domain_for_location, resolve_location_country
from services.log_queue import LLMClientLogQueue, log_ist

# ─── System Caps & TTL Cache ─────────────────────────────────────────────
DISCOVERY_JD_FETCH_CAP = 15       # Top 15 web-scraped jobs get real JD ATS scoring
DISCOVERY_FETCH_CONCURRENCY = 5  # Scaled up to 5 concurrent browser tasks utilizing 3GB combined memory
_job_search_cache = TTLCache(ttl_seconds=300)  # 5-minute TTL search cache
_indeed_blocked_circuit_breaker = False        # Flips to True if 1 Indeed request gets Cloudflare blocked

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
    full_description: Optional[str] = None

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
    
    log_ist(f"[Job Searcher] Fetching LinkedIn: {url}")
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

def search_reed_jobs(keyword: str, location: str = "London", timeframe: str = "24h") -> List[JobSearchResult]:
    """
    Search Reed.co.uk API for UK job listings.
    Gates execution: skips network calls if location is outside UK (GB).
    """
    country_code = resolve_location_country(location)
    if country_code != "GB":
        log_ist(f"[Job Searcher] Skipping Reed.co.uk search for non-UK location: '{location}' (Country={country_code})")
        return []

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
    
    log_ist(f"[Job Searcher] Fetching Reed API ({timeframe}): {url}")
    raw_candidates = []
    
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
                
                # Filter out paid course / trainee fee / boot camp spam listings disguised as jobs
                title_lower = title.lower()
                company_lower = company.lower()
                
                spam_keywords = [
                    "course cost", "job guarantee", "guaranteed job", "trainee fee", "course fee", 
                    "refund you 100%", "training package", "newto", "nology", "learning people", 
                    "the training room", "itol recruit", "traineeship", "training course", "fees apply"
                ]
                
                if any(kw in company_lower or kw in title_lower for kw in spam_keywords):
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

                raw_candidates.append({
                    "job": JobSearchResult(
                        title=title,
                        company=company,
                        location=loc,
                        url=job_url,
                        platform="Reed",
                        post_date_raw=post_date_str or "Recent",
                        job_id=job_id
                    ),
                    "job_id": job_id,
                    "title": title,
                    "dt": job_dt or datetime.min
                })

            # Concurrent pre-screening via ThreadPoolExecutor instead of sequential HTTP requests
            def _check_reed_spam(candidate):
                j_id = candidate["job_id"]
                if j_id and j_id.isdigit():
                    try:
                        detail_req = urllib.request.Request(f"https://www.reed.co.uk/api/1.0/jobs/{j_id}", headers=headers)
                        with urllib.request.urlopen(detail_req, context=SSL_CONTEXT, timeout=3) as detail_resp:
                            detail_data = json.loads(detail_resp.read().decode("utf-8"))
                            jd_raw = (detail_data.get("jobDescription", "") or "").lower()
                            jd_spam_patterns = [
                                "course cost", "course fee", "fees apply", "traineeship", "training course",
                                "refund you 100%", "fees of £", "fee of £", "training cost", "payable by monthly",
                                "per month for the course", "get your money back", "job guaranteed", "guaranteed job"
                            ]
                            if any(sp in jd_raw for sp in jd_spam_patterns):
                                log_ist(f"[Job Searcher] 🚫 Pre-screening rejected Reed course/fee listing ID {j_id}: '{candidate['title']}'")
                                return None
                    except Exception:
                        pass
                return candidate

            # Run pre-screening checks concurrently across threads
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as executor:
                screened_results = list(executor.map(_check_reed_spam, raw_candidates[:40]))
            valid_results = [r for r in screened_results if r is not None]

            # Sort by post date descending (newest jobs first)
            valid_results.sort(key=lambda x: x["dt"], reverse=True)
            final_jobs = [r["job"] for r in valid_results[:20]]
            log_ist(f"[Job Searcher] ✓ Reed API returned {len(final_jobs)} fresh jobs within {timeframe} for '{keyword}' (sorted newest first)")
            return final_jobs
    except Exception as e:
        log_ist(f"[Job Searcher] Reed API search error: {e}")

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
    global _indeed_blocked_circuit_breaker
    if _indeed_blocked_circuit_breaker:
        log_ist("[Job Searcher] Indeed circuit breaker ACTIVE (Cloudflare block detected previously). Skipping Indeed scraping.")
        return []

    encoded_keyword = urllib.parse.quote(keyword)
    encoded_location = urllib.parse.quote(location)
    
    # Resolve regional Indeed domain based on target location (e.g. Hyderabad -> in.indeed.com)
    indeed_domain, country_code = get_indeed_domain_for_location(location)

    # Map timeframe to Indeed fromage parameter (days)
    fromage_map = {
        "24h": "1",
        "48h": "2",
        "1w": "7",
        "1m": "30"
    }
    fromage = fromage_map.get(timeframe, "2")
    url = f"https://{indeed_domain}/jobs?q={encoded_keyword}&l={encoded_location}&fromage={fromage}"
    
    log_ist(f"[Job Searcher] Fetching Indeed ({indeed_domain}, Country={country_code}): {url}")
    results = []

    # Fast path: Parse Indeed RSS XML feed directly via urllib (bypasses Cloudflare & Playwright)
    try:
        rss_url = f"https://{indeed_domain}/rss?q={urllib.parse.quote(keyword)}&l={urllib.parse.quote(location)}"
        req = urllib.request.Request(
            rss_url,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
                "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.google.com/"
            }
        )
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=5) as resp:
            rss_xml = resp.read().decode("utf-8", errors="ignore")
            rss_soup = BeautifulSoup(rss_xml, "xml")
            items = rss_soup.find_all("item")
            if items:
                for item in items[:15]:
                    raw_title = item.find("title").get_text().strip() if item.find("title") else "Indeed Job"
                    link = item.find("link").get_text().strip() if item.find("link") else url
                    pub_date = item.find("pubDate").get_text().strip() if item.find("pubDate") else "Recent"
                    source_elem = item.find("source")
                    company_name = source_elem.get_text().strip() if source_elem else "Indeed Employer"
                    
                    jk_match = re.search(r'[?&]jk=([a-f0-9]{16})', link)
                    j_id = jk_match.group(1) if jk_match else None

                    results.append(JobSearchResult(
                        title=raw_title,
                        company=company_name,
                        location=location,
                        url=link,
                        platform="Indeed",
                        post_date_raw=pub_date,
                        job_id=j_id
                    ))
                log_ist(f"[Job Searcher] ⚡ Instantly fetched {len(results)} Indeed jobs via RSS XML feed for '{keyword}'")
                return results
    except Exception as rss_err:
        log_ist(f"[Job Searcher] Indeed RSS fetch skipped ({rss_err}), attempting Playwright fallback...")

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
            _indeed_blocked_circuit_breaker = True
            log_ist(f"[Job Searcher] ⛔ Indeed Cloudflare Challenge triggered (status={status}, title={page_title!r}). Flipping circuit breaker ON to skip remaining Indeed calls. LinkedIn & Reed search remain 100% operational.")
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
            href = f"https://{indeed_domain}/viewjob?jk={jk}" if jk else f"https://{indeed_domain}"
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


async def _score_job_with_real_jd(job: JobSearchResult, resume_data: dict, browser, semaphore: asyncio.Semaphore, on_log=None) -> Optional[dict]:
    """Fetches the real JD for a single job (with 24h TTLCache lookup) and scores it with the exact same
    deterministic engine (compute_ats_score / compute_overall_score) that the
    Tailor Resume flow uses, so discovery's overall score is directly comparable
    to the ATS score shown after tailoring — not a separately-invented estimate."""
    url_cache_key = f"jd_scrape_{hashlib.md5(job.url.encode('utf-8')).hexdigest()}"
    cached_scraped = _job_search_cache.get(url_cache_key)

    if hasattr(job, "full_description") and job.full_description and len(job.full_description.strip()) > 50:
        scraped = {"description": job.full_description, "title": job.title, "company": job.company}
    elif cached_scraped:
        scraped = cached_scraped
    else:
        async with semaphore:
            try:
                scraped = await scrape_job_description(job.url, browser=browser, on_log=on_log)
                if scraped and scraped.get("description"):
                    _job_search_cache.set(url_cache_key, scraped)
            except Exception as e:
                print(f"[Job Searcher] Failed to fetch JD for '{job.title}' at {job.url}: {e}")
                return None

    jd_text = scraped.get("description", "")
    raw_text = scraped.get("raw_text", "")
    if not jd_text or len(jd_text.strip()) < 100:
        return None

    # Filter out paid courses / fee-based training schemes disguised as jobs inside BOTH cleaned JD and raw scraped HTML text
    combined_text_lower = (jd_text + "\n" + raw_text).lower()
    fee_patterns = [
        "course cost", "course fee", "fees apply", "traineeship", "training course and fees",
        "refund you 100%", "fees of £", "fee of £", "training cost", "payable by monthly",
        "per month for the course", "get your money back", "job guaranteed - complete",
        "job guaranteed", "training course", "course fees"
    ]
    if any(fp in combined_text_lower for fp in fee_patterns):
        print(f"[Job Searcher] 🚫 Rejecting fee-based course/training listing: '{job.title}'")
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

    cand_years, avg_tenure, weighted_segments, _ = calculate_flattened_experience(resume_data)

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
    custom_api_key: Optional[str] = None,
    browser: Optional[Any] = None
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
        msg = f"🔎 Using user-preferred search queries: {', '.join(queries)}"
        log_ist(msg)
        yield json.dumps({"type": "log", "message": msg}) + " " * 2048 + "\n"
    else:
        msg1 = "🤖 Analyzing resume context to generate optimal search queries..."
        log_ist(msg1)
        yield json.dumps({"type": "log", "message": msg1}) + " " * 2048 + "\n"
        queries = await asyncio.to_thread(generate_search_queries_from_resume, resume_data, custom_api_key)
        msg2 = f"🔎 Generated search queries: {', '.join(queries)}"
        log_ist(msg2)
        yield json.dumps({"type": "log", "message": msg2}) + " " * 2048 + "\n"

    # Determine target country for clean user status logs
    target_country = resolve_location_country(location)
    platform_label = "LinkedIn, Indeed, Reed, Greenhouse, Ashby & Lever"

    # Concurrently scan configured target portals (Greenhouse, Ashby, Lever)
    portal_start_msg = "🌐 Scanning target ATS Portals (Greenhouse, Ashby & Lever)..."
    log_ist(portal_start_msg)
    yield json.dumps({"type": "log", "message": portal_start_msg}) + " " * 2048 + "\n"
    portal_jobs_raw = []
    try:
        from services.portal_scanner import PortalScanner
        scanner = PortalScanner()
        portal_results = await scanner.scan_all_portals(target_keywords=queries, timeframe=timeframe, location=location)
        gh_cnt = sum(1 for pj in portal_results if pj.get("portal") == "greenhouse")
        ash_cnt = sum(1 for pj in portal_results if pj.get("portal") == "ashby")
        lev_cnt = sum(1 for pj in portal_results if pj.get("portal") == "lever")
        
        for pj in portal_results:
            p_obj = JobSearchResult(
                title=pj.get("title", ""),
                company=pj.get("company", ""),
                location=pj.get("location", "Remote/Unspecified"),
                url=pj.get("url", ""),
                platform=pj.get("portal", "Portal").title(),
                post_date_raw=pj.get("age", "Active"),
                job_id=pj.get("id", hashlib.md5(pj.get("url", "").encode()).hexdigest()[:10]),
                full_description=pj.get("description", "")
            )
            portal_jobs_raw.append(p_obj)
        portal_done_msg = f"✓ Found {gh_cnt} Greenhouse, {ash_cnt} Ashby & {lev_cnt} Lever direct portal postings ({len(portal_jobs_raw)} total)"
        log_ist(portal_done_msg)
        yield json.dumps({"type": "log", "message": portal_done_msg}) + " " * 2048 + "\n"
    except Exception as pe:
        err_msg = f"[find_matching_jobs] PortalScanner error: {pe}"
        log_ist(err_msg)
        print(err_msg)

    # Execute search queries sequentially across queries, but fetch platforms in parallel per query
    raw_jobs = list(portal_jobs_raw)
    indeed_jobs_for_est = []
    for query in queries:
        yield_msg = f"🌐 Fetching listings from LinkedIn, Indeed & Reed for '{query}'..."
        log_ist(yield_msg)
        yield json.dumps({"type": "log", "message": yield_msg}) + " " * 2048 + "\n"
        
        # Parallel platform fetching per query for faster response
        li_task = asyncio.to_thread(search_linkedin_jobs, query, location, timeframe)
        reed_task = asyncio.to_thread(search_reed_jobs, query, location, timeframe)
        ind_task = search_indeed_jobs(query, location, timeframe)

        li_jobs, reed_jobs, ind_jobs = await asyncio.gather(li_task, reed_task, ind_task)
        
        yield json.dumps({"type": "log", "message": f"✓ Fetched {len(li_jobs)} LinkedIn listings for '{query}'"}) + " " * 2048 + "\n"
        if target_country == "GB":
            yield json.dumps({"type": "log", "message": f"✓ Fetched {len(reed_jobs)} Reed.co.uk listings for '{query}'"}) + " " * 2048 + "\n"
        
        raw_jobs.extend(li_jobs)
        raw_jobs.extend(reed_jobs)
        raw_jobs.extend(ind_jobs)
        indeed_jobs_for_est.extend(ind_jobs)
        
        res_msg = f"✓ Found {len(li_jobs)} LinkedIn, {len(ind_jobs)} Indeed & {len(reed_jobs)} Reed.co.uk postings for '{query}'" if target_country == "GB" else f"✓ Found {len(li_jobs)} LinkedIn & {len(ind_jobs)} Indeed postings for '{query}'"
        log_ist(res_msg)
        yield json.dumps({"type": "log", "message": res_msg}) + " " * 2048 + "\n"

    # Deduplicate by job URL / ID
    seen_ids = set()
    deduped_jobs = []
    for job in raw_jobs:
        if job.job_id not in seen_ids:
            seen_ids.add(job.job_id)
            deduped_jobs.append(job)

    yield json.dumps({"type": "log", "message": f"📊 Found {len(deduped_jobs)} unique postings. Computing ATS matches..."}) + " " * 2048 + "\n"

    # Separate instant API jobs (Reed, Greenhouse, Ashby, Lever) from web-scraped jobs (LinkedIn/Indeed)
    api_fast_jobs = [j for j in deduped_jobs if j.platform in ("Reed", "Greenhouse", "Ashby", "Lever")]
    scraped_jobs = [j for j in deduped_jobs if j.platform not in ("Reed", "Greenhouse", "Ashby", "Lever")]
    
    scraped_jobs.sort(key=lambda j: _title_heuristic_score(j, resume_data), reverse=True)

    scored_jobs = []

    # Phase A: Instant in-memory scoring for direct ATS API jobs (Greenhouse, Ashby, Lever, Reed with full JD)
    if api_fast_jobs:
        yield json.dumps({"type": "log", "message": f"⚡ Instantly computing ATS match scores for {len(api_fast_jobs)} direct ATS portal openings..."}) + " " * 2048 + "\n"
        for job in api_fast_jobs:
            try:
                if hasattr(job, "full_description") and job.full_description and len(job.full_description.strip()) > 50:
                    r = await _score_job_with_real_jd(job, resume_data, None, asyncio.Semaphore(50))
                    if r and r.get("score", 0) >= 55:
                        scored_jobs.append(r)
                        yield json.dumps({"type": "partial_result", "job": r}) + "\n"
            except Exception as pe:
                print(f"[find_matching_jobs] Direct portal scoring error for '{job.title}': {pe}")

    # Phase B: Scrape and score top external web listings (LinkedIn / Indeed)
    web_scored_batch = scraped_jobs[:DISCOVERY_JD_FETCH_CAP]
    title_only_batch = scraped_jobs[DISCOVERY_JD_FETCH_CAP:]

    if web_scored_batch:
        yield json.dumps({"type": "log", "message": f"📄 Fetching real job descriptions for {len(web_scored_batch)} web listings (LinkedIn / Indeed)..."}) + " " * 2048 + "\n"
        semaphore = asyncio.Semaphore(DISCOVERY_FETCH_CONCURRENCY)
        
        async def _score_and_stream(job, log_queue_stream):
            def _ui_logger(msg):
                log_queue_stream.append(json.dumps({"type": "log", "message": msg}) + " " * 2048 + "\n")
            try:
                if browser is not None:
                    res = await _score_job_with_real_jd(job, resume_data, browser, semaphore, on_log=_ui_logger)
                else:
                    try:
                        from playwright.async_api import async_playwright
                        async with async_playwright() as p:
                            b = await p.chromium.launch(headless=True)
                            try:
                                res = await _score_job_with_real_jd(job, resume_data, b, semaphore, on_log=_ui_logger)
                            finally:
                                await b.close()
                    except Exception as b_err:
                        print(f"[Job Searcher] Headless browser unavailable for '{job.title}': {b_err}")
                        res = await _score_job_with_real_jd(job, resume_data, None, semaphore, on_log=_ui_logger)
                return res
            except Exception as e:
                print(f"[Job Searcher] Error scoring job '{job.title}': {e}")
                return None

        log_queue_stream = []
        tasks = [asyncio.create_task(_score_and_stream(job, log_queue_stream)) for job in web_scored_batch]
        for completed_task in asyncio.as_completed(tasks):
            r = await completed_task
            while log_queue_stream:
                yield log_queue_stream.pop(0)
            if r is not None:
                log_msg = f"✓ Scored match: {r['title']} @ {r['company']} ({r['score']}% Match)"
                yield json.dumps({"type": "log", "message": log_msg}) + " " * 2048 + "\n"
                if r["score"] >= 55:
                    scored_jobs.append(r)
                    yield json.dumps({"type": "partial_result", "job": r}) + "\n"
            else:
                # Yield a progress heartbeat chunk to keep connection active
                yield json.dumps({"type": "log", "message": "⏳ Processing web listings..."}) + " " * 2048 + "\n"

    if title_only_batch:
        yield json.dumps({"type": "log", "message": f"📝 Estimating {len(title_only_batch)} additional matches from title only (beyond the {DISCOVERY_JD_FETCH_CAP}-job accurate-scan cap)..."}) + " " * 2048 + "\n"
        for job in title_only_batch:
            r = _score_job_with_title_heuristic(job, resume_data)
            if r["score"] >= 55:
                scored_jobs.append(r)
                yield json.dumps({"type": "partial_result", "job": r}) + "\n"

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

    # Save results to 5-minute TTL cache
    cache_key = (keywords or "", location or "Remote", timeframe or "48h")
    _job_search_cache.set(cache_key, scored_jobs)

    yield json.dumps({"type": "result", "jobs": scored_jobs, "est_jobs": est_jobs}) + "\n"

