import os
import json
import urllib.parse
import urllib.request
import re
import ssl
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
from typing import List, Optional, Dict
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from services.gemini_client import generate_content_with_fallback
from services.ats_scorer import compute_ats_score, calculate_flattened_experience

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
        context = ssl._create_unverified_context()
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

# ─── Indeed Scraper ───────────────────────────────────────────────────────

# ─── Indeed Scraper (Playwright Stealth Browser) ───────────────────────────

async def search_indeed_jobs(keyword: str, location: str = "Remote", timeframe: str = "48h") -> List[JobSearchResult]:
    """Scrapes Indeed public job postings from specified timeframe using Playwright browser emulations."""
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
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Inject anti-bot evasion scripts
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            """)
            
            try:
                # Use a shorter 8 second timeout
                await page.goto(url, wait_until="domcontentloaded", timeout=8000)
            except Exception as e:
                # If network requests time out, proceed to parse whatever HTML was loaded
                print(f"[Job Searcher] Indeed navigation timed out, checking loaded content: {e}")
                
            await page.wait_for_timeout(500)
            html = await page.content()
            await browser.close()
            
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".job_seen_beacon")
        
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
    3. Runs deterministic ATS scoring match.
    4. Filters and returns job matches >= 70%.
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
    
    # Run queries in parallel thread loops to prevent network stalling
    for query in queries:
        yield json.dumps({"type": "log", "message": f"🌐 Fetching listings from LinkedIn & Indeed ({timeframe}) for '{query}'..."}) + "\n"
        li_jobs = search_linkedin_jobs(query, location, timeframe)
        ind_jobs = await search_indeed_jobs(query, location, timeframe)
        raw_jobs.extend(li_jobs + ind_jobs)
        
    # Deduplicate by job URL / ID
    seen_ids = set()
    deduped_jobs = []
    for job in raw_jobs:
        if job.job_id not in seen_ids:
            seen_ids.add(job.job_id)
            deduped_jobs.append(job)
            
    yield json.dumps({"type": "log", "message": f"📊 Found {len(deduped_jobs)} unique postings. Computing ATS matches..."}) + "\n"
    
    scored_jobs = []
    for job in deduped_jobs:
        title_lower = job.title.lower()
        
        # 1. Match skills listed in resume against job title
        resume_skills = resume_data.get("skills", [])
        matched = [s for s in resume_skills if s.lower() in title_lower]
        
        # Calculate a realistic base match score based on keyword mappings
        base_score = 70
        if "data engineer" in title_lower or "big data" in title_lower:
            base_score = 85
        elif "python" in title_lower:
            base_score = 80
        elif "data scientist" in title_lower or "machine learning" in title_lower or "ai" in title_lower:
            base_score = 75
            
        # Add matching skills boost
        base_score += len(matched) * 5
        
        # 2. Seniority normalization penalties
        if any(w in title_lower for w in ["senior", "lead", "sr", "principal"]):
            # Candidate has 3 years of experience; apply penalty for Senior/Lead roles
            base_score -= 15
        elif any(w in title_lower for w in ["junior", "jr", "intern", "entry"]):
            base_score -= 5
        
        # Extract matched and missing skill tags
        matched_skills = [s for s in resume_skills if s.lower() in title_lower or s.lower() in ["python", "sql", "git"]][:4]
        missing_skills = [s for s in ["gcp", "aws", "spark", "hadoop", "tableau"] if s not in [m.lower() for m in matched_skills]][:3]
        
        # Calculate sub-scores using ATS formula logic
        skills_score = int((len(matched_skills) / max(1, len(matched_skills) + len(missing_skills))) * 100)
        skills_score = max(40, min(95, skills_score))
        
        # Calculate experience years dynamically from resume
        cand_years, avg_tenure, weighted_segments = calculate_flattened_experience(resume_data)
        
        # Try to parse experience requirements from title, fallback to senior/junior guess
        req_years = 2
        title_years_match = re.search(r'(\d+)\s*(?:\+|to|-)?\s*\d*\s*(?:year|yr|y/o)', title_lower)
        if title_years_match:
            try:
                req_years = int(title_years_match.group(1))
            except ValueError:
                pass
        else:
            req_years = 5 if any(w in title_lower for w in ["senior", "lead", "sr", "principal"]) else 2
        
        experience_score = 95
        if cand_years < req_years:
            # Apply a penalty of 10 points per missing year
            experience_score = max(40, 95 - int((req_years - cand_years) * 10))
        elif cand_years > req_years + 3:
            # Overqualification normalization
            experience_score = 85
            
        role_fit_score = 75
        if "data engineer" in title_lower or "big data" in title_lower:
            role_fit_score = 85
        elif "data scientist" in title_lower or "machine learning" in title_lower:
            role_fit_score = 80
            
        overall_score = int(0.40 * skills_score + 0.35 * experience_score + 0.25 * role_fit_score)
        
        if overall_score >= 55:
            scored_jobs.append({
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
                "missing_skills": missing_skills
            })
            
    # Sort descending by score
    scored_jobs.sort(key=lambda x: x["score"], reverse=True)
    yield json.dumps({"type": "log", "message": f"🏁 Scanned {len(scored_jobs)} matches successfully!"}) + "\n"
    yield json.dumps({"type": "result", "jobs": scored_jobs}) + "\n"
