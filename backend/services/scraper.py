import os
import asyncio
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
import re

async def scrape_job_description(url: str, browser=None, on_log=None) -> dict:
    """
    Scrapes a job posting page from LinkedIn, Indeed, Reed, or any MNC career portal.
    Uses official Reed Jobs Details REST API when scraping Reed URLs for instant zero-latency JD extraction.
    """
    import re
    import json
    import base64
    import urllib.request
    # pyrefly: ignore [missing-import]
    from bs4 import BeautifulSoup
    from utils.ssl_utils import SSL_CONTEXT
    from services.log_queue import log_ist
    # Fast path for Reed URLs via official REST API
    if "reed.co.uk" in url:
        job_id_match = re.search(r'/(\d+)(?:\?|$)', url)
        if job_id_match:
            job_id = job_id_match.group(1)
            reed_key = os.getenv("REED_API_KEY")
            if reed_key:
                try:
                    auth_str = f"{reed_key}:"
                    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
                    req = urllib.request.Request(
                        f"https://www.reed.co.uk/api/1.0/jobs/{job_id}",
                        headers={"Authorization": f"Basic {b64_auth}", "User-Agent": "JobFinderApp/1.0"}
                    )
                    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        raw_html_desc = data.get("jobDescription", "")
                        parsed_text = BeautifulSoup(raw_html_desc, "html.parser").get_text(separator="\n").strip()
                        if parsed_text and len(parsed_text) > 50:
                            from services.log_queue import log_ist
                            log_ist(f"[Scraper] ⚡ Instantly fetched Reed JD via Official Details API for Job ID: {job_id}")
                            return {
                                "title": data.get("jobTitle", "Job Posting"),
                                "description": parsed_text,
                                "raw_text": raw_html_desc + "\n" + parsed_text,
                                "company": data.get("employerName", "Reed Employer"),
                                "url": url,
                                "html": raw_html_desc
                            }
                except Exception as reed_err:
                    from services.log_queue import log_ist
                    log_ist(f"[Scraper] Reed Details API fallback to Playwright browser ({reed_err})")

    # Fast path for LinkedIn URLs via public guest jobs-posting API.
    # LinkedIn blocks Playwright on GCP/datacenter IPs, but this public API endpoint
    # works with plain HTTP requests from any IP — no browser needed.
    if "linkedin.com/jobs/view/" in url:
        try:
            import urllib.request, json
            from utils.ssl_utils import SSL_CONTEXT
            from services.log_queue import log_ist
            # Extract numeric job ID from URL: .../jobs/view/title-at-company-{jobId}
            li_id_match = re.search(r'/jobs/view/[^/]*?-?(\d{7,13})(?:/|\?|$)', url)
            if not li_id_match:
                # fallback: last segment numeric
                li_id_match = re.search(r'-(\d{7,13})(?:/|\?|$)', url)
            if li_id_match:
                job_id = li_id_match.group(1)
                api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
                req = urllib.request.Request(
                    api_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                    }
                )
                with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=8) as resp:
                    html_bytes = resp.read()
                    html = html_bytes.decode("utf-8", errors="ignore")
                    soup = BeautifulSoup(html, "html.parser")

                    # Extract JD from LinkedIn guest API response
                    jd_elem = (
                        soup.select_one(".show-more-less-html__markup") or
                        soup.select_one(".description__text") or
                        soup.select_one("[class*='description__text']") or
                        soup.select_one("section.description") or
                        soup.select_one(".jobs-description__container")
                    )
                    title_elem = soup.select_one("h2.top-card-layout__title") or soup.select_one("h1")
                    company_elem = soup.select_one("a.topcard__org-name-link") or soup.select_one(".topcard__flavor")

                    jd_text = jd_elem.get_text(separator="\n").strip() if jd_elem else ""
                    title = title_elem.get_text().strip() if title_elem else "LinkedIn Job"
                    company = company_elem.get_text().strip() if company_elem else ""

                    if jd_text and len(jd_text) > 100:
                        log_ist(f"[Scraper] ⚡ Instantly fetched LinkedIn JD via guest API for Job ID: {job_id}")
                        return {
                            "title": title,
                            "description": jd_text,
                            "raw_text": jd_text,
                            "company": company,
                            "url": url,
                            "html": html
                        }
                    else:
                        log_ist(f"[Scraper] LinkedIn guest API returned thin content for {job_id}, falling back to Playwright")
        except Exception as li_err:
            from services.log_queue import log_ist
            log_ist(f"[Scraper] LinkedIn guest API error ({li_err}), falling back to Playwright")

    # Fast path for Indeed URLs via direct viewjob REST endpoint / viewjob parser
    if "indeed.com" in url:
        try:
            import urllib.request, json
            from utils.ssl_utils import SSL_CONTEXT
            from services.log_queue import log_ist
            # Extract Indeed job key (jk=...)
            jk_match = re.search(r'[?&]jk=([a-f0-9]{16})', url) or re.search(r'/rc/clk\?jk=([a-f0-9]{16})', url) or re.search(r'jk=([a-f0-9]{16})', url)
            if jk_match:
                jk = jk_match.group(1)
                direct_url = f"https://www.indeed.com/viewjob?jk={jk}"
                req = urllib.request.Request(
                    direct_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                    }
                )
                with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=8) as resp:
                    html_bytes = resp.read()
                    html = html_bytes.decode("utf-8", errors="ignore")
                    soup = BeautifulSoup(html, "html.parser")

                    jd_elem = (
                        soup.select_one("#jobDescriptionText") or
                        soup.select_one(".jobsearch-JobComponent-description") or
                        soup.select_one("[class*='JobComponent-description']") or
                        soup.select_one(".fastItem")
                    )
                    title_elem = soup.select_one("h1.jobsearch-JobInfoHeader-title") or soup.select_one("h1")
                    cmp_anchor = soup.select_one("a[href*='/cmp/']") or soup.select_one("[data-company-name='true']")

                    jd_text = jd_elem.get_text(separator="\n").strip() if jd_elem else ""
                    title = title_elem.get_text().strip() if title_elem else "Indeed Job"
                    company = cmp_anchor.get_text().strip() if cmp_anchor else "Indeed Employer"

                    if jd_text and len(jd_text) > 100:
                        log_ist(f"[Scraper] ⚡ Instantly fetched Indeed JD via direct viewjob endpoint for JK: {jk}")
                        return {
                            "title": title,
                            "description": jd_text,
                            "raw_text": jd_text,
                            "company": company,
                            "url": url,
                            "html": html
                        }
        except Exception as indeed_err:
            from services.log_queue import log_ist
            log_ist(f"[Scraper] Indeed direct fetch error ({indeed_err}), falling back to Playwright")



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

    # Block heavy resource downloads (images, fonts, media, stylesheets) to reduce RAM/network load by 60%
    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "font", "media", "stylesheet"] else route.continue_())

    try:
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        body_text = ""
        title = "Unknown Role"
        extracted_company = ""
        soup = None

        # Execute up to 3 retry attempts
        for attempt in range(3):
            try:
                from services.log_queue import log_ist
                msg_attempt = f"[Scraper] Attempt {attempt + 1}/3 to scrape: {url}"
                log_ist(msg_attempt)
                if on_log:
                    on_log(msg_attempt)

                async def _do_attempt():
                    # Always use domcontentloaded for fast page loads; networkidle hangs on analytics/tracking scripts
                    await page.goto(url, wait_until="domcontentloaded", timeout=10000)

                    # Scroll to trigger lazy content safely
                    await page.wait_for_timeout(500)
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                    except Exception:
                        pass
                    await page.wait_for_timeout(500 * (attempt + 1))
                    return await page.content(), await page.title()

                # Hard cap: 20s per attempt — prevents GCP from hanging on stalled LinkedIn JS
                try:
                    html, title = await asyncio.wait_for(_do_attempt(), timeout=20)
                except asyncio.TimeoutError:
                    log_ist(f"[Scraper] Attempt {attempt + 1} timed out after 20s: {url}")
                    if attempt == 2:
                        break
                    continue

                soup = BeautifulSoup(html, 'html.parser')

                # LinkedIn specific selector matches
                if "linkedin.com" in url:
                    jd_elem = (
                        soup.select_one(".jobs-description__container") or
                        soup.select_one(".show-more-less-html__markup") or
                        soup.select_one("[class*='description__text']") or
                        soup.select_one(".description__text")
                    )
                    if jd_elem:
                        body_text = jd_elem.get_text(separator="\n")

                # Indeed specific selector matches
                elif "indeed.com" in url:
                    # Try to extract title from Indeed DOM elements
                    indeed_title_elem = (
                        soup.select_one("h1.jobsearch-JobInfoHeader-title") or
                        soup.select_one("[data-testid='jobsearch-JobInfoHeader-title']") or
                        soup.select_one("h1")
                    )
                    if indeed_title_elem and indeed_title_elem.get_text().strip():
                        title = indeed_title_elem.get_text().strip()

                    # Try to extract company name from Indeed /cmp/ link (e.g. href="https://www.indeed.com/cmp/Apple?...")
                    cmp_anchor = soup.select_one("a[href*='/cmp/']")
                    if cmp_anchor:
                        cmp_href = cmp_anchor.get("href", "")
                        cmp_match = re.search(r'/cmp/([a-zA-Z0-9%_\-]+)', cmp_href)
                        if cmp_match:
                            extracted_cmp = cmp_match.group(1).replace('+', ' ').replace('-', ' ').title()
                            if extracted_cmp:
                                title = f"{title} at {extracted_cmp}"

                    jd_elem = (
                        soup.select_one("#jobDescriptionText") or
                        soup.select_one(".jobsearch-JobComponent-description") or
                        soup.select_one("[class*='JobComponent-description']") or
                        soup.select_one(".fastItem")
                    )
                    if jd_elem:
                        body_text = jd_elem.get_text(separator="\n")

                # Reed.co.uk specific selector matches
                elif "reed.co.uk" in url:
                    jd_elem = (
                        soup.select_one(".description") or
                        soup.select_one("[itemprop='description']") or
                        soup.select_one(".job-description") or
                        soup.select_one("span[itemprop='description']")
                    )
                    if jd_elem:
                        body_text = jd_elem.get_text(separator="\n")

                # Generic fallback selectors if specific ones failed
                if not body_text:
                    for selector in [".job-description", "#job-description", "article", ".main-content", ".description", "[itemprop='description']"]:
                        jd_elem = soup.select_one(selector)
                        if jd_elem:
                            body_text = jd_elem.get_text(separator="\n")
                            break

                # Check if we successfully got a substantial block of text
                if body_text and len(body_text.strip()) > 200:
                    from services.log_queue import log_ist
                    log_ist(f"[Scraper] Success on attempt {attempt + 1}! Length: {len(body_text)}")
                    break
            except Exception as attempt_err:
                from services.log_queue import log_ist
                log_ist(f"[Scraper] Attempt {attempt + 1} failed: {attempt_err}")
                if attempt == 2:
                    raise attempt_err
                await page.wait_for_timeout(1000)

        # Universal fallback for general MNC pages if no container matched
        if not body_text and soup is not None:
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.extract()
            body_text = soup.get_text(separator="\n")

        # Clean up whitespace
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines)

        # Extract and format using Gemini
        prompt = f"""
        You are an expert recruiter. Extract ONLY the Job Title and the actual detailed Job Description (role, responsibilities, requirements, skills, location, etc.) from the raw web page text below.

        CRITICAL: Strip out all cookies, consent warnings, website navigation links, cookie policy popups, and irrelevant footer/header corporate boilerplate.

        Raw Web Page Text:
        ---
        {cleaned_text[:12000]}
        ---
        """
        try:
            from services.gemini_client import generate_content_with_fallback
            # pyrefly: ignore [missing-import]
            from pydantic import BaseModel

            class CleanedJobInfo(BaseModel):
                title: str
                description: str

            response_text = generate_content_with_fallback(prompt, CleanedJobInfo)
            import json
            cleaned_info = json.loads(response_text)

            # Ensure we have a valid description
            description = cleaned_info.get("description", "") or cleaned_text
            if not description or len(description.strip()) < 100:
                # If Gemini returned empty or too short, use the raw cleaned text
                description = cleaned_text

            return {
                "title": cleaned_info.get("title", title) or title,
                "description": description,
                "raw_text": cleaned_text,
                "company": extracted_company,
                "url": url,
                "html": html
            }
        except Exception as e:
            print(f"[Scraper] Gemini cleanup failed ({e}), falling back to raw extracted text.")
            return {
                "title": title,
                "description": cleaned_text,
                "raw_text": cleaned_text,
                "company": extracted_company,
                "url": url,
                "html": html
            }
    except Exception as e:
        # Fallback: extract title slug and query search metadata if Playwright gets blocked
        fallback_title = "Tailored Job Application"
        fallback_company = ""
        
        try:
            # 1. Check if Indeed JK key is present
            if "jk=" in url:
                jk_val = url.split("jk=")[1].split("&")[0]
                fallback_title = f"Indeed Job ({jk_val[:8]})"
                
                # Fetch metadata fallback from DuckDuckGo/Google search index
                try:
                    import urllib.request
                    import json
                    search_req_url = f"https://html.duckduckgo.com/html/?q={jk_val}+site:indeed.com"
                    req = urllib.request.Request(search_req_url, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    })
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        search_html = resp.read().decode("utf-8", errors="ignore")
                        search_soup = BeautifulSoup(search_html, "html.parser")
                        snippet_elem = search_soup.select_one(".result__snippet") or search_soup.select_one(".result__title")
                        if snippet_elem:
                            snip_text = snippet_elem.get_text()
                            if " - " in snip_text:
                                parts = snip_text.split(" - ")
                                fallback_title = parts[0].strip()
                                if len(parts) > 1:
                                    fallback_company = parts[1].split("|")[0].split("Job")[0].strip()
                except Exception as meta_err:
                    print(f"[Scraper] Search metadata fallback error: {meta_err}")

            elif "/jobs/view/" in url:
                slug = url.split("/jobs/view/")[1].split("/")[0].replace("-", " ").title()
                if slug: fallback_title = slug
        except Exception:
            pass

        return {
            "title": fallback_title,
            "company": fallback_company,
            "url": url,
            "description": f"Retrieved metadata for {fallback_title}. Auto-scraping dropped to fallback.",
            "html": ""
        }
    finally:
        if page is not None:
            try: await page.close()
            except Exception: pass
        if context is not None:
            try: await context.close()
            except Exception: pass
        if own_browser is not None:
            try: await own_browser.close()
            except Exception: pass
        if own_playwright is not None:
            try: await own_playwright.stop()
            except Exception: pass
        
        # Explicitly invoke garbage collection to clear unneeded browser context resources
        import gc
        gc.collect()

if __name__ == "__main__":
    # Test run
    test_url = "https://www.wikipedia.org"
    result = asyncio.run(scrape_job_description(test_url))
    print(result["title"])

