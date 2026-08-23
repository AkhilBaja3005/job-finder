import os
import asyncio
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
import re

# ── Module-level shared Playwright browser ─────────────────────────────────
# Initialised once by init_shared_browser() (called from FastAPI lifespan).
# Every scrape call reuses this instance instead of launching a new Chromium
# process (~2-3s saved per request). Falls back to per-call browser when
# the shared one is not yet ready (e.g. during startup).
_shared_playwright = None
_shared_browser = None

# ── Pre-warmed browser context pool ─────────────────────────────────────────
# Context creation + stealth init script takes ~200-500ms; pre-creating a
# small pool of ready-to-use contexts avoids paying that cost on every scrape
# when several run concurrently against the shared browser.
CONTEXT_POOL_SIZE = 2
_context_pool = None  # asyncio.Queue[BrowserContext] once init_shared_browser() runs
_scrape_counter = 0    # Track total scrapes to periodically refresh contexts and release RAM
_STEALTH_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
_STEALTH_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

async def _create_stealth_context(browser):
    context = await browser.new_context(user_agent=_STEALTH_USER_AGENT)
    await context.add_init_script(_STEALTH_INIT_SCRIPT)
    return context

async def init_shared_browser():
    """Launch the persistent shared Playwright browser. Called once at startup."""
    global _shared_playwright, _shared_browser, _context_pool
    try:
        _shared_playwright = await async_playwright().start()
        _shared_browser = await _shared_playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--no-first-run",
                "--no-zygote",
            ]
        )
        print("[Scraper] ⚡ Shared Playwright browser ready")
        try:
            pool = asyncio.Queue()
            for _ in range(CONTEXT_POOL_SIZE):
                pool.put_nowait(await _create_stealth_context(_shared_browser))
            _context_pool = pool
            print(f"[Scraper] ⚡ Pre-warmed {CONTEXT_POOL_SIZE} browser contexts")
        except Exception as pool_err:
            print(f"[Scraper] Context pool warm-up failed: {pool_err}")
            _context_pool = None
    except Exception as e:
        print(f"[Scraper] Shared browser init failed: {e}")
        _shared_playwright = None
        _shared_browser = None

async def close_shared_browser():
    """Gracefully shut down the shared browser. Called on app shutdown."""
    global _shared_playwright, _shared_browser, _context_pool
    if _context_pool is not None:
        while not _context_pool.empty():
            try:
                ctx = _context_pool.get_nowait()
                try: await ctx.close()
                except Exception: pass
            except asyncio.QueueEmpty:
                break
        _context_pool = None
    if _shared_browser:
        try: await _shared_browser.close()
        except Exception: pass
        _shared_browser = None
    if _shared_playwright:
        try: await _shared_playwright.stop()
        except Exception: pass
        _shared_playwright = None
# ───────────────────────────────────────────────────────────────────────────
# oc-style Semantic DOM Distillation Engine (Python)
# ───────────────────────────────────────────────────────────────────────────

def oc_distill_html(html_str: str, base_url: str = "") -> dict:
    """
    Distills raw HTML into a clean, noise-free Markdown job description
    by pruning boilerplate (scripts, styles, SVGs, nav, headers, footers, cookie banners)
    and isolating the high-density article/main job content.
    """
    if not html_str:
        return {"title": "", "company": "", "description": "", "markdown": ""}

    soup = BeautifulSoup(html_str, "html.parser")

    # 1. Extract Title & Company from OpenGraph / Metadata before pruning
    title = ""
    company = ""

    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].split(" | ")[0].split(" - ")[0].strip()

    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        company = og_site["content"].strip()

    # 2. Prune junk tags
    for junk in soup(["script", "style", "svg", "noscript", "iframe", "header", "footer", "nav", "meta", "link"]):
        junk.decompose()

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text().strip()

    # 3. Locate Main Job Container
    main_elem = None
    target_selectors = [
        "#job-details",
        ".jobs-description__content",
        "#jobDescriptionText",
        "[data-automation-id='jobPostingDescription']",
        "[data-ph-at-id='job-description']",
        ".job-description",
        ".job-details-description",
        "article",
        "main",
        "[role='main']"
    ]
    for sel in target_selectors:
        found = soup.select_one(sel)
        if found and len(found.get_text(strip=True)) > 150:
            main_elem = found
            break

    if not main_elem:
        # Score content density among div/section candidates
        best_elem = soup.body or soup
        max_score = 0
        for candidate in soup.find_all(["div", "section"]):
            c_text = candidate.get_text(strip=True)
            c_len = len(c_text)
            if 300 < c_len < 25000:
                p_count = len(candidate.find_all(["p", "li"]))
                score = c_len * (1 + p_count * 0.1)
                if score > max_score:
                    max_score = score
                    best_elem = candidate
        main_elem = best_elem

    # 4. Convert DOM to clean Markdown
    lines = []
    for elem in main_elem.descendants:
        if elem.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            lvl = int(elem.name[1])
            txt = elem.get_text().strip()
            if txt:
                lines.append(f"\n\n{'#' * lvl} {txt}\n")
        elif elem.name == "li":
            txt = elem.get_text().strip()
            if txt:
                lines.append(f"\n• {txt}")
        elif elem.name == "p":
            txt = elem.get_text().strip()
            if txt:
                lines.append(f"\n\n{txt}\n")
        elif elem.name == "br":
            lines.append("\n")

    if lines:
        distilled = "".join(lines)
    else:
        distilled = main_elem.get_text(separator="\n")

    cleaned_md = re.sub(r'\n{3,}', '\n\n', distilled).strip()
    return {
        "title": title or "Target Job",
        "company": company or "",
        "description": cleaned_md,
        "markdown": cleaned_md
    }


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

    # ── Normalise LinkedIn search-results URLs ─────────────────────────────
    # URLs like /jobs/search-results/?currentJobId=4441065098&...
    # are just the search page with a highlighted job — rewrite to canonical
    # /jobs/view/{id} so the guest-API fast path below can handle it.
    if "linkedin.com" in url and "currentJobId=" in url:
        cj_match = re.search(r'currentJobId=(\d+)', url)
        if cj_match:
            job_id = cj_match.group(1)
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            if on_log:
                on_log(f"[Scraper] Rewrote LinkedIn search URL → /jobs/view/{job_id}/")

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
                user_agents = [
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
                ]
                endpoints = [
                    f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
                    f"https://www.linkedin.com/jobs/view/{job_id}"
                ]
                for api_url in endpoints:
                    for ua in user_agents:
                        try:
                            req = urllib.request.Request(
                                api_url,
                                headers={
                                    "User-Agent": ua,
                                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                    "Accept-Language": "en-US,en;q=0.5",
                                    "Referer": "https://www.google.com/"
                                }
                            )
                            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=8) as resp:
                                html_bytes = resp.read()
                                html = html_bytes.decode("utf-8", errors="ignore")
                                soup = BeautifulSoup(html, "html.parser")

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
                        except Exception:
                            continue
        except Exception as li_err:
            from services.log_queue import log_ist
            log_ist(f"[Scraper] LinkedIn guest API error ({li_err}), falling back to Playwright")

    # Fast path for Indeed URLs via direct viewjob REST endpoint / viewjob parser
    if "indeed.com" in url:
        try:
            import urllib.request, json
            from utils.ssl_utils import SSL_CONTEXT
            from services.log_queue import log_ist
            # Extract Indeed job key (jk=...) — supports /rc/clk?jk=, /viewjob?jk=, and bare jk= params
            jk_match = (
                re.search(r'[?&]jk=([a-f0-9]{16})', url) or
                re.search(r'/rc/clk\?jk=([a-f0-9]{16})', url) or
                re.search(r'jk=([a-f0-9]{16})', url)
            )
            if jk_match:
                jk = jk_match.group(1)
                # Try mobile & desktop viewjob endpoints to bypass Cloudflare 403 blocks
                for direct_url in [
                    f"https://m.indeed.com/rpc/jobdescs?jks={jk}",
                    f"https://www.indeed.com/viewjob?jk={jk}",
                    f"https://m.indeed.com/viewjob?jk={jk}"
                ]:
                    try:
                        req = urllib.request.Request(
                            direct_url,
                            headers={
                                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
                                "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": "en-US,en;q=0.9",
                                "Referer": "https://www.google.com/"
                            }
                        )
                        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=8) as resp:
                            content_type = resp.headers.get("Content-Type", "")
                            raw_data = resp.read().decode("utf-8", errors="ignore")

                            # Handle mobile JSON API endpoint response
                            if "json" in content_type:
                                jdata = json.loads(raw_data)
                                if isinstance(jdata, dict) and jk in jdata:
                                    html_desc = jdata[jk]
                                    distilled = oc_distill_html(html_desc, url)
                                    parsed_text = distilled["description"] or BeautifulSoup(html_desc, "html.parser").get_text(separator="\n").strip()
                                    if len(parsed_text) > 50:
                                        log_ist(f"[Scraper] ⚡ Instantly distilled Indeed JD via oc-engine for JK: {jk}")
                                        return {
                                            "title": "Indeed Job",
                                            "description": parsed_text,
                                            "raw_text": parsed_text,
                                            "company": "Indeed Employer",
                                            "url": url,
                                            "html": html_desc
                                        }

                            # Handle HTML response — check for bot-block / error pages first
                            bot_block_phrases = [
                                "error processing your request",
                                "just a moment",
                                "access denied",
                                "verify you are human",
                                "verification required",
                                "enable javascript",
                                "checking your browser",
                                "please wait",
                                "security check",
                            ]
                            raw_lower = raw_data[:2000].lower()
                            if any(p in raw_lower for p in bot_block_phrases):
                                log_ist(f"[Scraper] Indeed bot-block detected on {direct_url}, trying next endpoint")
                                continue

                            soup = BeautifulSoup(raw_data, "html.parser")
                            jd_elem = (
                                soup.select_one("#jobDescriptionText") or
                                soup.select_one(".jobsearch-JobComponent-description") or
                                soup.select_one("[class*='JobComponent-description']") or
                                soup.select_one(".fastItem")
                            )
                            if jd_elem and len(jd_elem.get_text().strip()) > 100:
                                title_elem = soup.select_one("h1.jobsearch-JobInfoHeader-title") or soup.select_one("h1")
                                cmp_anchor = soup.select_one("a[href*='/cmp/']") or soup.select_one("[data-company-name='true']")
                                jd_text = jd_elem.get_text(separator="\n").strip()
                                raw_title = title_elem.get_text().strip() if title_elem else "Indeed Job"
                                # Guard against bot-block page titles leaking into job title
                                error_titles = {"error processing your request", "just a moment", "access denied", "attention required"}
                                title = raw_title if raw_title.lower() not in error_titles else "Indeed Job"
                                company = cmp_anchor.get_text().strip() if cmp_anchor else "Indeed Employer"
                                log_ist(f"[Scraper] ⚡ Instantly fetched Indeed JD via direct HTML for JK: {jk}")
                                return {
                                    "title": title,
                                    "description": jd_text,
                                    "raw_text": jd_text,
                                    "company": company,
                                    "url": url,
                                    "html": raw_data
                                }
                    except Exception:
                        continue
            else:
                log_ist(f"[Scraper] Indeed URL has no jk= key, cannot use fast path: {url}")
        except Exception as indeed_err:
            from services.log_queue import log_ist
            log_ist(f"[Scraper] Indeed direct fetch error ({indeed_err}), falling back to Playwright")



    own_playwright = None
    own_browser = None
    # Prefer the module-level shared browser (zero startup overhead),
    # then the caller-supplied browser, then spin up a temporary one.
    effective_browser = browser or _shared_browser
    if effective_browser is None:
        own_playwright = await async_playwright().start()
        effective_browser = await own_playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        own_browser = effective_browser
    browser = effective_browser

    # Pull a pre-warmed context from the pool when scraping against the
    # shared browser (skips new_context + add_init_script, ~200-500ms saved).
    context = None
    from_pool = False
    if browser is _shared_browser and _context_pool is not None:
        try:
            context = _context_pool.get_nowait()
            from_pool = True
        except asyncio.QueueEmpty:
            context = None
    if context is None:
        context = await _create_stealth_context(browser)

    page = await context.new_page()

    # Block heavy resource downloads (images, fonts, media, stylesheets) to reduce RAM/network load by 60%
    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "font", "media", "stylesheet"] else route.continue_())

    try:
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

                # ── Bot-block / error page detection ──────────────────────────
                # Indeed (and Cloudflare) show "Error Processing Request", "Just a moment",
                # or CAPTCHA pages to datacenter IPs. Detect these early and skip retries.
                _bot_block_phrases = [
                    "error processing your request",
                    "just a moment",
                    "access denied",
                    "verify you are human",
                    "enable javascript and cookies",
                    "checking your browser",
                    "please enable cookies",
                ]
                _page_lower = (title + " " + html[:3000]).lower()
                if "indeed.com" in url and any(p in _page_lower for p in _bot_block_phrases):
                    log_ist(f"[Scraper] Indeed bot-block page detected via Playwright (title='{title}'). Stopping retries.")
                    break  # No point retrying — datacenter IP is blocked by Indeed
                # ──────────────────────────────────────────────────────────────

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
                        raw_title = indeed_title_elem.get_text().strip()
                        # Guard: don't use error-page h1 as a job title
                        _error_h1s = {"error processing your request", "just a moment", "access denied", "attention required"}
                        if raw_title.lower() not in _error_h1s:
                            title = raw_title

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

            response_text = await asyncio.to_thread(generate_content_with_fallback, prompt, CleanedJobInfo)
            import json
            cleaned_info = json.loads(response_text)

            # Ensure we have a valid description
            description = cleaned_info.get("description", "") or cleaned_text
            if not description or len(description.strip()) < 100:
                description = cleaned_text

            # Detect bot-block / Cloudflare verification text leaking into extracted description
            _bot_block_indicators = [
                "cloudflare security verification",
                "anti-bot challenge",
                "security verification page",
                "verify you are human",
                "checking your browser",
                "enable javascript and cookies",
                "access denied",
                "just a moment",
                "error processing your request"
            ]
            desc_lower = description.lower()
            is_blocked = any(ind in desc_lower for ind in _bot_block_indicators) or any(ind in (cleaned_info.get("title") or title).lower() for ind in _bot_block_indicators)

            return {
                "title": cleaned_info.get("title", title) or title,
                "description": description,
                "raw_text": cleaned_text,
                "company": extracted_company,
                "url": url,
                "html": html,
                "is_bot_blocked": is_blocked
            }
        except Exception as e:
            print(f"[Scraper] Gemini cleanup failed ({e}), falling back to raw extracted text.")
            _bot_block_indicators = [
                "cloudflare security verification",
                "anti-bot challenge",
                "security verification page",
                "verify you are human",
                "checking your browser",
                "enable javascript and cookies",
                "access denied",
                "just a moment",
                "error processing your request"
            ]
            cleaned_lower = cleaned_text.lower()
            is_blocked = any(ind in cleaned_lower for ind in _bot_block_indicators) or any(ind in title.lower() for ind in _bot_block_indicators)
            return {
                "title": title,
                "description": cleaned_text,
                "raw_text": cleaned_text,
                "company": extracted_company,
                "url": url,
                "html": html,
                "is_bot_blocked": is_blocked
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
        global _scrape_counter
        _scrape_counter += 1

        if page is not None:
            try: await page.close()
            except Exception: pass
        if context is not None:
            # Every 25 scrapes, destroy the context instead of returning it to pool to flush Chromium memory
            if from_pool and _context_pool is not None and (_scrape_counter % 25 != 0):
                try:
                    await context.clear_cookies()
                    _context_pool.put_nowait(context)
                except Exception:
                    try: await context.close()
                    except Exception: pass
            else:
                try: await context.close()
                except Exception: pass
                # Replenish context pool if we destroyed a pooled context
                if from_pool and _context_pool is not None and _shared_browser:
                    try:
                        new_ctx = await _create_stealth_context(_shared_browser)
                        _context_pool.put_nowait(new_ctx)
                        print("[Scraper] 🧹 Memory cleanup: Recycled Chromium browser context after 25 operations")
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

