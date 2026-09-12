"""
Recruiter extraction service for LinkedIn and Indeed job postings.
Parses job URLs to extract recruiter name, profile URL, and company info.
"""

import re
import unicodedata
import urllib.parse
from typing import Optional, Dict, Any
# pyrefly: ignore [missing-import]
from utils.ttl_cache import TTLCache


def _clean_text(s):
    """
    LinkedIn's markup frequently embeds invisible/zero-width Unicode characters
    (category "Cf" — format chars like U+200B, U+200C, U+200D, U+FEFF) around
    text nodes. str.strip() only trims real whitespace, so a naive text ==
    "Job poster" comparison silently fails even though the visible text
    matches — strip all Cf chars before any text comparison/extraction.
    """
    if not s:
        return s
    return ''.join(c for c in s if unicodedata.category(c) != 'Cf').strip()


def _parse_recruiter_html(html: str) -> Dict[str, Optional[str]]:
    """Parses a LinkedIn job posting page's HTML for recruiter + company info."""
    # pyrefly: ignore [missing-import]
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    recruiter_name = None
    recruiter_profile_url = None

    # LinkedIn serves a different DOM depending on whether the scraping
    # session is logged in:
    #  - Logged-in view: a "Job poster" label inside the hiring-team card
    #  - Logged-out/public view (what an unauthenticated scrape actually
    #    sees): a ".message-the-recruiter" section with the name in
    #    h3.base-main-card__title and the profile link in
    #    a.base-card__full-link
    # Try the public-view selector first since that's what we hit in practice.
    # 1. Check for public message-the-recruiter section
    recruiter_section = soup.select_one(".message-the-recruiter") or soup.select_one("[class*='message-the-recruiter']") or soup.select_one(".hirer-card") or soup.select_one("[class*='hiring-team']")
    if recruiter_section:
        name_tag = (
            recruiter_section.select_one("h3.base-main-card__title") or 
            recruiter_section.select_one("[class*='title']") or 
            recruiter_section.select_one("h3") or 
            recruiter_section.select_one("h4")
        )
        link_tag = recruiter_section.select_one("a.base-card__full-link") or recruiter_section.find(
            'a', href=re.compile(r'linkedin\.com/in/')
        )
        if name_tag:
            recruiter_name = _clean_text(name_tag.get_text()) or None
        if link_tag:
            _href_val = link_tag.get('href')
            recruiter_profile_url = str(_href_val) if _href_val is not None else None

    # 2. Check for "Job poster" / "Hiring team" / "Meet the hiring team" text labels
    if not recruiter_name:
        job_poster_label = None
        for tag in soup.find_all(['p', 'span', 'div', 'h2', 'h3', 'h4']):
            cleaned = _clean_text(tag.get_text())
            if any(cleaned.lower() == k for k in ["job poster", "hiring team", "meet the hiring team", "hiring manager"]):
                job_poster_label = tag
                break

        if job_poster_label:
            container = job_poster_label
            for _ in range(6):
                if container.parent is None:
                    break
                container = container.parent
                candidates = container.find_all('a', href=re.compile(r'linkedin\.com/in/'))
                if candidates:
                    best = min(candidates, key=lambda a: len(_clean_text(a.get_text())))
                    recruiter_profile_url = recruiter_profile_url or str(best.get('href') or "")
                    recruiter_name = _clean_text(best.get_text()) or None
                    break

    # 3. Comprehensive Regex Fallbacks for public / embedded profile links
    if not recruiter_profile_url:
        profile_match = re.search(r'href="(https://[a-z]{2,3}\.linkedin\.com/in/[^"?#/]+)', html) or re.search(r'href="(https://www\.linkedin\.com/in/[^"?#/]+)', html)
        recruiter_profile_url = profile_match.group(1) if profile_match else None

    if not recruiter_name:
        # Fallback 1: "Posted by Name" or "Meet Name"
        recruiter_match = re.search(r'(?:Posted by|Meet|Hiring Manager:?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', html)
        if recruiter_match:
            recruiter_name = _clean_text(recruiter_match.group(1))
        elif recruiter_profile_url:
            # Fallback 2: Extract name from profile link anchor tag or URL path slug
            profile_anchor = soup.find('a', href=re.compile(re.escape(str(recruiter_profile_url))))
            if profile_anchor and _clean_text(profile_anchor.get_text()):
                recruiter_name = _clean_text(profile_anchor.get_text())
            else:
                # Extract slug e.g. "owen-thomas-12345" -> "Owen Thomas"
                slug_match = re.search(r'/in/([a-zA-Z0-9-]+)', str(recruiter_profile_url))
                if slug_match:
                    slug = slug_match.group(1)
                    # Strip numerical ID suffix if present
                    name_parts = [p.capitalize() for p in slug.split('-') if not p.isdigit() and len(p) > 1]
                    if name_parts:
                        recruiter_name = " ".join(name_parts)

    # Extract company name. LinkedIn's public job page renders the company
    # name directly in the topcard org-name link — prefer that over the page
    # <title>, since the title's format varies ("X hiring Y in Z | LinkedIn",
    # "Y at X | LinkedIn", etc.) and a single regex can't reliably cover all
    # of them.
    company_name = None
    org_tag = soup.select_one("a.topcard__org-name-link") or soup.select_one(".topcard__org-name-link")
    if org_tag:
        company_name = _clean_text(org_tag.get_text()) or None

    if not company_name:
        title_tag = soup.find('title')
        page_title = _clean_text(title_tag.get_text()) if title_tag else ""
        company_match = re.search(r'at\s+([A-Za-z0-9\s&.,\'-]+?)\s+\|', page_title)
        company_name = company_match.group(1).strip() if company_match else None

    print(f"[recruiter_extractor] Found recruiter: {recruiter_name}, profile: {recruiter_profile_url}, company: {company_name}")

    return {
        "recruiter_name": recruiter_name,
        "recruiter_profile_url": recruiter_profile_url,
        "company_name": company_name,
        "platform": "linkedin"
    }


async def extract_recruiter_from_linkedin(job_url: str, html: Optional[str] = None, browser=None) -> Dict[str, Optional[str]]:
    """
    Extract recruiter info from a LinkedIn job posting URL.

    LinkedIn job URLs typically look like:
    https://www.linkedin.com/jobs/view/1234567890/

    If `html` is already available (e.g. the discovery pipeline already fetched
    this page's HTML for the job description), it's parsed directly and no
    Playwright navigation happens at all. Otherwise this launches its own
    browser (or reuses `browser` if provided) and scrapes the page itself.

    Returns:
        {
            "recruiter_name": str or None,
            "recruiter_profile_url": str or None,
            "company_name": str or None,
            "platform": "linkedin"
        }
    """
    if html is not None:
        try:
            # pyrefly: ignore [missing-import]
            from services.log_queue import log_ist
            log_ist(f"[extract_recruiter_from_linkedin] Using pre-fetched HTML for: {job_url}")
            result = _parse_recruiter_html(html)
            log_ist(f"[recruiter_extractor] Found recruiter: {result.get('recruiter_name')}, profile: {result.get('recruiter_profile_url')}, company: {result.get('company_name')}")
            return result
        except Exception as e:
            # pyrefly: ignore [missing-import]
            from services.log_queue import log_ist
            log_ist(f"[extract_recruiter_from_linkedin] Error parsing pre-fetched HTML: {e}")
            return {
                "recruiter_name": None,
                "recruiter_profile_url": None,
                "company_name": None,
                "platform": "linkedin"
            }

    try:
        # pyrefly: ignore [missing-import]
        from playwright.async_api import async_playwright
        # pyrefly: ignore [missing-import]
        from services.log_queue import log_ist
        log_ist(f"[extract_recruiter_from_linkedin] Scraping: {job_url}")

        own_playwright = None
        own_browser = None
        if browser is None:
            own_playwright = await async_playwright().start()
            browser = await own_playwright.chromium.launch(headless=True)
            own_browser = browser

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1500)
            # The "Meet the hiring team" card renders further down the page —
            # scroll to trigger it into view/load before reading the DOM.
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await page.wait_for_timeout(1500)

            html = await page.content()
            result = _parse_recruiter_html(html)
            # pyrefly: ignore [missing-import]
            from services.log_queue import log_ist
            log_ist(f"[recruiter_extractor] Found recruiter: {result.get('recruiter_name')}, profile: {result.get('recruiter_profile_url')}, company: {result.get('company_name')}")
            return result

        except Exception as e:
            # pyrefly: ignore [missing-import]
            from services.log_queue import log_ist
            log_ist(f"[extract_recruiter_from_linkedin] Scraping error: {e}")
            return {
                "recruiter_name": None,
                "recruiter_profile_url": None,
                "company_name": None,
                "platform": "linkedin"
            }
        finally:
            await page.close()
            await context.close()
            if own_browser is not None:
                await own_browser.close()
            if own_playwright is not None:
                await own_playwright.stop()

    except Exception as e:
        # pyrefly: ignore [missing-import]
        from services.log_queue import log_ist
        log_ist(f"[extract_recruiter_from_linkedin] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "recruiter_name": None,
            "recruiter_profile_url": None,
            "company_name": None,
            "platform": "linkedin"
        }


def extract_recruiter_from_indeed(job_url: str) -> Dict[str, Optional[str]]:
    """
    Extract recruiter info from an Indeed job posting URL.

    Indeed job URLs typically look like:
    https://www.indeed.com/viewjob?jk=abc123def456

    Similar to LinkedIn, the recruiter info is embedded in the page HTML.

    Returns:
        {
            "recruiter_name": str or None,
            "recruiter_profile_url": str or None,
            "company_name": str or None,
            "platform": "indeed"
        }
    """
    try:
        # Extract job key from URL
        parsed = urllib.parse.urlparse(job_url)
        params = urllib.parse.parse_qs(parsed.query)
        job_key = params.get('jk', [None])[0]

        if not job_key:
            return {
                "recruiter_name": None,
                "recruiter_profile_url": None,
                "company_name": None,
                "platform": "indeed"
            }

        # In a real implementation, you'd use Playwright to scrape the page
        # and extract recruiter info from the job posting HTML.
        return {
            "recruiter_name": None,
            "recruiter_profile_url": None,
            "company_name": None,
            "platform": "indeed",
            "job_key": job_key,
            "requires_scraping": "true"
        }
    except Exception as e:
        print(f"Error extracting Indeed recruiter info: {e}")
        return {
            "recruiter_name": None,
            "recruiter_profile_url": None,
            "company_name": None,
            "platform": "indeed"
        }


# Module-level bounded cache for grounded recruiter lookups (max 200 entries, 1 hr TTL).
_recruiter_cache = TTLCache(ttl_seconds=3600, max_size=200)

# Circuit breaker flag for grounded recruiter queries across the current run
_recruiter_grounding_quota_exhausted = False


def is_recruiter_grounding_quota_exhausted() -> bool:
    return _recruiter_grounding_quota_exhausted


def reset_recruiter_grounding_quota() -> None:
    global _recruiter_grounding_quota_exhausted
    _recruiter_grounding_quota_exhausted = False


async def discover_recruiter_via_grounding(company_name: str, custom_api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Uses Gemini with Google Search Grounding to discover a technical recruiter
    or talent acquisition lead for companies when posting via Greenhouse, Lever, Ashby, etc.
    Caches lookups by company name for 1 hour to prevent redundant LLM search requests.
    """
    global _recruiter_grounding_quota_exhausted

    if not company_name or len(company_name.strip()) < 2:
        return {"recruiter_name": None, "recruiter_profile_url": None}

    cache_key = company_name.strip().lower()
    cached = _recruiter_cache.get(cache_key)
    if cached is not None:
        return cached

    if _recruiter_grounding_quota_exhausted and not custom_api_key:
        return {"recruiter_name": None, "recruiter_profile_url": None, "quota_exhausted": True}

    try:
        # pyrefly: ignore [missing-import]
        from services.gemini_client import call_gemini_grounded
        clean_company = re.sub(r'[^a-zA-Z0-9\s]', '', company_name).strip()
        query = (
            f"Find a currently active Technical Recruiter or Head of Talent at {clean_company}. "
            f"Search specifically for: \"{clean_company}\" (\"technical recruiter\" OR \"talent partner\" OR \"recruiter\") site:linkedin.com/in\n"
            f"Return ONLY a valid JSON object with the format:\n"
            f"{{\"name\": \"Full Name\", \"linkedin_url\": \"https://linkedin.com/in/...\", \"title\": \"Title\"}}\n"
            f"If no specific recruiter is verified with high certainty, return {{\"name\": null, \"linkedin_url\": null}}"
        )
        res = call_gemini_grounded(query, custom_api_key=custom_api_key)
        text = res.get("text", "")
        # Extract JSON from response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            import json
            data = json.loads(match.group(0))
            name = data.get("name")
            url = data.get("linkedin_url")
            # If citations contain a linkedin profile, use that as url fallback
            if name and not url:
                for cit in res.get("citations", []):
                    c_url = cit.get("url", "")
                    if "linkedin.com/in/" in c_url:
                        url = c_url
                        break
            if name and name.lower() not in ["null", "none", "unknown", "n/a"]:
                found = {
                    "recruiter_name": name.strip(),
                    "recruiter_profile_url": url.strip() if url else None
                }
                _recruiter_cache.set(cache_key, found)
                return found
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            _recruiter_grounding_quota_exhausted = True
            print(f"[discover_recruiter_via_grounding] Gemini search quota exhausted (429).")
            return {"recruiter_name": None, "recruiter_profile_url": None, "quota_exhausted": True}
        print(f"[discover_recruiter_via_grounding] Search grounding fallback failed: {e}")

    result = {"recruiter_name": None, "recruiter_profile_url": None}
    _recruiter_cache.set(cache_key, result)
    return result


async def extract_recruiter(job_url: str, platform: Optional[str] = None, html: Optional[str] = None, browser=None, company_hint: Optional[str] = None, custom_api_key: Optional[str] = None, allow_grounding: bool = True) -> Dict[str, Any]:
    """
    Unified interface to extract recruiter info from a job posting URL.

    Automatically detects the platform if not provided.
    If platform is a direct ATS (Greenhouse, Lever, Ashby, Workday) or no recruiter
    is directly on the page, uses Gemini Google Search Grounding to find an active recruiter
    ONLY if allow_grounding is True.

    Args:
        job_url: The job posting URL
        platform: Optional platform hint ('linkedin' or 'indeed')
        html: Optional pre-fetched page HTML (LinkedIn only) to avoid a
            redundant Playwright navigation when the caller already has it
        browser: Optional already-launched Playwright Browser to reuse
            (LinkedIn only) instead of launching a new one
        company_hint: Optional company name hint for grounded search
        custom_api_key: Optional custom Gemini API key
        allow_grounding: When False, skips heavy LLM search grounding (essential during batch discovery)

    Returns:
        {
            "recruiter_name": str or None,
            "recruiter_profile_url": str or None,
            "company_name": str or None,
            "platform": str
        }
    """
    if not job_url:
        return {
            "recruiter_name": None,
            "recruiter_profile_url": None,
            "company_name": None,
            "platform": "unknown"
        }

    # Auto-detect platform if not provided
    if not platform:
        j_lower = job_url.lower()
        if 'linkedin.com' in j_lower:
            platform = 'linkedin'
        elif 'indeed.com' in j_lower:
            platform = 'indeed'
        elif 'greenhouse.io' in j_lower:
            platform = 'greenhouse'
        elif 'lever.co' in j_lower:
            platform = 'lever'
        elif 'ashbyhq.com' in j_lower:
            platform = 'ashby'
        elif 'workday' in j_lower:
            platform = 'workday'
        else:
            platform = 'unknown'

    res: Dict[str, Any] = {
        "recruiter_name": None,
        "recruiter_profile_url": None,
        "company_name": None,
        "platform": platform
    }

    if platform == 'linkedin':
        res = dict(await extract_recruiter_from_linkedin(job_url, html=html, browser=browser))
    elif platform == 'indeed':
        res = dict(extract_recruiter_from_indeed(job_url))

    # If recruiter wasn't found on the page, only discover recruiter via Google Search Grounding
    # when allow_grounding is explicitly enabled (e.g. on-demand in outreach modal, NOT batch discovery)
    if allow_grounding and not res.get("recruiter_name"):
        comp = company_hint or res.get("company_name")
        if not comp:
            # Try to derive company name from job URL domain or subpaths (e.g. boards.greenhouse.io/stripe)
            m_gh = re.search(r'(?:boards\.greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com)/([^/?#]+)', job_url)
            if m_gh:
                comp = m_gh.group(1).replace('-', ' ').title()

        if comp:
            grounded_res = await discover_recruiter_via_grounding(comp, custom_api_key=custom_api_key)
            if grounded_res.get("quota_exhausted"):
                res["quota_exhausted"] = True
            if grounded_res.get("recruiter_name"):
                res["recruiter_name"] = grounded_res["recruiter_name"]
                res["recruiter_profile_url"] = grounded_res.get("recruiter_profile_url")
                if not res.get("company_name"):
                    res["company_name"] = comp

    return res
