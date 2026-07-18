"""
Recruiter extraction service for LinkedIn and Indeed job postings.
Parses job URLs to extract recruiter name, profile URL, and company info.
"""

import re
import urllib.parse
from typing import Optional, Dict
import json


async def extract_recruiter_from_linkedin(job_url: str) -> Dict[str, Optional[str]]:
    """
    Extract recruiter info from a LinkedIn job posting URL by scraping the page.

    LinkedIn job URLs typically look like:
    https://www.linkedin.com/jobs/view/1234567890/

    Returns:
        {
            "recruiter_name": str or None,
            "recruiter_profile_url": str or None,
            "company_name": str or None,
            "platform": "linkedin"
        }
    """
    try:
        from playwright.async_api import async_playwright
        from bs4 import BeautifulSoup
        import re

        print(f"[extract_recruiter_from_linkedin] Scraping: {job_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
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

                # Get page HTML
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")

                # LinkedIn's markup frequently embeds invisible/zero-width Unicode
                # characters (category "Cf" — format chars like U+200B, U+200C,
                # U+200D, U+FEFF) around text nodes. str.strip() only trims real
                # whitespace, so a naive text == "Job poster" comparison silently
                # fails even though the visible text matches — strip all Cf chars
                # before any text comparison/extraction.
                import unicodedata

                def _clean_text(s):
                    if not s:
                        return s
                    return ''.join(c for c in s if unicodedata.category(c) != 'Cf').strip()

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
                recruiter_section = soup.select_one(".message-the-recruiter")
                if recruiter_section:
                    name_tag = recruiter_section.select_one("h3.base-main-card__title")
                    link_tag = recruiter_section.select_one("a.base-card__full-link") or recruiter_section.find(
                        'a', href=re.compile(r'linkedin\.com/in/')
                    )
                    if name_tag:
                        recruiter_name = _clean_text(name_tag.get_text()) or None
                    if link_tag:
                        recruiter_profile_url = link_tag.get('href')

                # LinkedIn's logged-in layout labels the poster card "Job poster"
                # (previously "Posted by Name" in older markup). Class names are
                # hashed/rotate per deploy, so anchor on this stable text label
                # and find the nearest profile link instead of relying on CSS.
                if not recruiter_name:
                    job_poster_label = None
                    for tag in soup.find_all(['p', 'span', 'div']):
                        if _clean_text(tag.get_text()) == "Job poster":
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
                                # The card has both an outer wrapping link (whose text
                                # is the whole card) and an inner link around just the
                                # name — the shortest text is the name itself.
                                best = min(candidates, key=lambda a: len(_clean_text(a.get_text())))
                                recruiter_profile_url = recruiter_profile_url or best.get('href')
                                recruiter_name = _clean_text(best.get_text()) or None
                                break

                # Fallback: older "Posted by Name" layout
                if not recruiter_name:
                    recruiter_match = re.search(r'Posted by\s+([A-Za-z\s]+?)(?:\s*\||<|$)', html)
                    recruiter_name = _clean_text(recruiter_match.group(1)) if recruiter_match else None

                if not recruiter_profile_url:
                    profile_match = re.search(r'href="(https://www\.linkedin\.com/in/[^"]+)"', html)
                    recruiter_profile_url = profile_match.group(1) if profile_match else None

                # Extract company name from page title or meta tags
                page_title = _clean_text(await page.title())
                company_match = re.search(r'at\s+([A-Za-z0-9\s&.,\'-]+?)\s+\|', page_title)
                company_name = company_match.group(1).strip() if company_match else None

                print(f"[extract_recruiter_from_linkedin] Found recruiter: {recruiter_name}, profile: {recruiter_profile_url}, company: {company_name}")

                await browser.close()

                return {
                    "recruiter_name": recruiter_name,
                    "recruiter_profile_url": recruiter_profile_url,
                    "company_name": company_name,
                    "platform": "linkedin"
                }

            except Exception as e:
                print(f"[extract_recruiter_from_linkedin] Scraping error: {e}")
                await browser.close()
                return {
                    "recruiter_name": None,
                    "recruiter_profile_url": None,
                    "company_name": None,
                    "platform": "linkedin"
                }

    except Exception as e:
        print(f"[extract_recruiter_from_linkedin] Error: {e}")
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
            "requires_scraping": True
        }
    except Exception as e:
        print(f"Error extracting Indeed recruiter info: {e}")
        return {
            "recruiter_name": None,
            "recruiter_profile_url": None,
            "company_name": None,
            "platform": "indeed"
        }


async def extract_recruiter(job_url: str, platform: Optional[str] = None) -> Dict[str, Optional[str]]:
    """
    Unified interface to extract recruiter info from a job posting URL.

    Automatically detects the platform if not provided.

    Args:
        job_url: The job posting URL
        platform: Optional platform hint ('linkedin' or 'indeed')

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
        if 'linkedin.com' in job_url.lower():
            platform = 'linkedin'
        elif 'indeed.com' in job_url.lower():
            platform = 'indeed'
        else:
            platform = 'unknown'

    if platform == 'linkedin':
        return await extract_recruiter_from_linkedin(job_url)
    elif platform == 'indeed':
        return extract_recruiter_from_indeed(job_url)
    else:
        return {
            "recruiter_name": None,
            "recruiter_profile_url": None,
            "company_name": None,
            "platform": platform
        }
