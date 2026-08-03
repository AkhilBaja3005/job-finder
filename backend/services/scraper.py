import asyncio
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
import re

async def scrape_job_description(url: str, browser=None) -> dict:
    """
    Scrapes a job posting page from LinkedIn, Indeed, or any MNC career portal.
    Extracts job title, company name, location, and the full job description text.
    Runs up to 3 attempts with progressive delay fallbacks to ensure dynamic JavaScript content loads.

    If `browser` is provided (an already-launched Playwright Browser instance),
    it's reused instead of launching a new Chromium process — callers that scrape
    many URLs in a row (e.g. job discovery) should launch one browser and pass it
    in for every call to avoid the ~1-2s startup cost per job.
    """
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
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        body_text = ""
        title = "Unknown Role"
        soup = None

        # Execute up to 3 retry attempts
        for attempt in range(3):
            try:
                print(f"[Scraper] Attempt {attempt + 1}/3 to scrape: {url}")
                # Always use domcontentloaded for fast page loads; networkidle hangs on analytics/tracking scripts
                await page.goto(url, wait_until="domcontentloaded", timeout=10000)

                # Scroll to trigger lazy content safely
                await page.wait_for_timeout(500)
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                except Exception:
                    pass
                await page.wait_for_timeout(500 * (attempt + 1))

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                title = await page.title()

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
                    print(f"[Scraper] Success on attempt {attempt + 1}! Length: {len(body_text)}")
                    break
            except Exception as attempt_err:
                print(f"[Scraper] Attempt {attempt + 1} failed: {attempt_err}")
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
        await page.close()
        await context.close()
        if own_browser is not None:
            await own_browser.close()
        if own_playwright is not None:
            await own_playwright.stop()
        
        # Explicitly invoke garbage collection to clear unneeded browser context resources
        import gc
        gc.collect()

if __name__ == "__main__":
    # Test run
    test_url = "https://www.wikipedia.org"
    result = asyncio.run(scrape_job_description(test_url))
    print(result["title"])

