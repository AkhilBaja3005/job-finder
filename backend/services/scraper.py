import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def scrape_job_description(url: str) -> dict:
    """
    Scrapes a job posting page from LinkedIn, Indeed, or any MNC career portal.
    Extracts job title, company name, location, and the full job description text.
    Runs up to 3 attempts with progressive delay fallbacks to ensure dynamic JavaScript content loads.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
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
            
            # Execute up to 3 retry attempts
            for attempt in range(3):
                try:
                    print(f"[Scraper] Attempt {attempt + 1}/3 to scrape: {url}")
                    # On retry attempts, wait longer for network resources to resolve
                    wait_strategy = "networkidle" if attempt > 0 else "domcontentloaded"
                    await page.goto(url, wait_until=wait_strategy, timeout=12000)
                    
                    # Scroll to trigger lazy content
                    await page.wait_for_timeout(500)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
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
                        jd_elem = (
                            soup.select_one("#jobDescriptionText") or 
                            soup.select_one(".jobsearch-JobComponent-description") or
                            soup.select_one("[class*='JobComponent-description']")
                        )
                        if jd_elem:
                            body_text = jd_elem.get_text(separator="\n")
                    
                    # Generic fallback selectors if specific ones failed
                    if not body_text:
                        for selector in [".job-description", "#job-description", "article", ".main-content"]:
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
            if not body_text:
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
                from pydantic import BaseModel
                
                class CleanedJobInfo(BaseModel):
                    title: str
                    description: str
                    
                response_text = generate_content_with_fallback(prompt, CleanedJobInfo)
                import json
                cleaned_info = json.loads(response_text)
                return {
                    "title": cleaned_info.get("title", title) or title,
                    "url": url,
                    "description": cleaned_info.get("description", cleaned_text)
                }
            except Exception as e:
                print(f"Gemini cleaning failed, returning raw text: {e}")
                return {
                    "title": title,
                    "url": url,
                    "description": cleaned_text
                }
        except Exception as e:
            return {
                "title": "Failed to Parse",
                "url": url,
                "description": f"Failed to retrieve job details automatically. Error: {str(e)}"
            }
        finally:
            await browser.close()

if __name__ == "__main__":
    # Test run
    test_url = "https://www.wikipedia.org"
    result = asyncio.run(scrape_job_description(test_url))
    print(result["title"])
