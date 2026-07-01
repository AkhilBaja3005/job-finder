import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def scrape_job_description(url: str) -> dict:
    """
    Scrapes a job posting page from LinkedIn, Indeed, or any MNC career portal.
    Extracts job title, company name, location, and the full job description text.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Emulate a real browser to bypass basic anti-bot scripts
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # Clean up the previous scrapingbee blocks and focus on free stealth browser emulation
            # Disable webdriver flag and mock navigator plugins to pass anti-bot tests
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            """)
            
            # Navigate to target page
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Emulate realistic human delay and micro-scrolling to trigger lazy loading
            await page.wait_for_timeout(1500)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await page.wait_for_timeout(1000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 1.5)")
            await page.wait_for_timeout(1000)
            
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Basic parsing logic for generic pages
            title = await page.title()
            
            # Clean up text content
            # Try to locate the main text container
            body_text = ""
            
            # LinkedIn specific
            if "linkedin.com" in url:
                # LinkedIn job page selectors
                jd_elem = soup.select_one(".jobs-description__container") or soup.select_one(".show-more-less-html__markup")
                if jd_elem:
                    body_text = jd_elem.get_text(separator="\n")
            
            # Indeed specific
            elif "indeed.com" in url:
                jd_elem = soup.select_one("#jobDescriptionText")
                if jd_elem:
                    body_text = jd_elem.get_text(separator="\n")
            
            # Fallback for general MNC pages
            if not body_text:
                # Remove script and style elements
                for script in soup(["script", "style", "nav", "footer", "header"]):
                    script.extract()
                body_text = soup.get_text(separator="\n")
            
            # Post-processing: clean up excessive whitespace/newlines
            lines = [line.strip() for line in body_text.splitlines() if line.strip()]
            cleaned_text = "\n".join(lines)
            
            # Use Gemini to clean and extract only the relevant job title and JD
            prompt = f"""
            You are an expert recruiter. Extract ONLY the Job Title and the actual detailed Job Description (role, responsibilities, requirements, skills, location, etc.) from the raw web page text below.
            
            CRITICAL: Strip out all cookies, consent warnings, website navigation links, cookie policy popups, and irrelevant footer/header corporate boilerplate.
            
            Raw Web Page Text:
            ---
            {cleaned_text}
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
