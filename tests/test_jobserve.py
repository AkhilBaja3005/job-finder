#!/usr/bin/env python3
"""
test_jobserve.py - Independent verification script for Jobserve discovery and JD extraction.

Tests:
1. Public Search Endpoint / RSS Query for UK/Global tech roles
2. HTML / DOM parsing of job cards (Title, Company, Rate/Salary, Location, Date, URL)
3. Detail Page Scraping (Full JD extraction, skills, recruiter contact)
"""

import sys
import os
import re
import json
import asyncio
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup

try:
    sys.path.insert(0, os.path.abspath("backend"))
    from utils.ssl_utils import SSL_CONTEXT
except Exception:
    SSL_CONTEXT = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
}


def test_rss_feed(keyword: str = "Python", location: str = "London"):
    """Tests Jobserve's RSS feed endpoint."""
    print(f"\n[1] Testing Jobserve RSS Feed for '{keyword}' in '{location}'...")
    encoded_kw = urllib.parse.quote(keyword)
    encoded_loc = urllib.parse.quote(location)
    
    rss_urls = [
        f"https://www.jobserve.com/MyJobServe/rss.ashx?kw={encoded_kw}&loc={encoded_loc}",
        f"https://www.jobserve.com/gb/en/Job-Search/rss.ashx?kw={encoded_kw}&loc={encoded_loc}",
    ]
    
    for url in rss_urls:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                content = resp.read().decode("utf-8", errors="ignore")
                print(f"  -> RSS ({url}): Status {status}, Length: {len(content)} bytes")
                if "<item>" in content:
                    soup = BeautifulSoup(content, "xml") if "xml" in BeautifulSoup.builder_registry.builders else BeautifulSoup(content, "html.parser")
                    items = soup.find_all("item")
                    print(f"  ✓ Found {len(items)} jobs via RSS!")
                    for idx, it in enumerate(items[:3], 1):
                        title = it.find("title").get_text(strip=True) if it.find("title") else "N/A"
                        link = it.find("link").get_text(strip=True) if it.find("link") else "N/A"
                        pub_date = it.find("pubDate").get_text(strip=True) if it.find("pubDate") else "N/A"
                        print(f"    {idx}. {title} | {pub_date}\n       URL: {link}")
                    return True
        except Exception as e:
            print(f"  ✕ RSS error on {url}: {e}")
    return False


def test_http_search(keyword: str = "Python", location: str = "London"):
    """Tests standard HTTP HTML Search request."""
    print(f"\n[2] Testing Direct HTTP Search for '{keyword}' in '{location}'...")
    encoded_kw = urllib.parse.quote(keyword)
    encoded_loc = urllib.parse.quote(location)
    
    # Common search URLs for Jobserve
    search_urls = [
        f"https://www.jobserve.com/gb/en/Job-Search/?keywords={encoded_kw}&location={encoded_loc}",
        f"https://www.jobserve.com/gb/en/jobsearch.aspx?kw={encoded_kw}&loc={encoded_loc}",
    ]
    
    for url in search_urls:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                html = resp.read().decode("utf-8", errors="ignore")
                print(f"  -> HTTP Search ({url}): Status {status}, Length: {len(html)} bytes")
                soup = BeautifulSoup(html, "html.parser")
                
                # Check for job list elements
                job_elements = soup.select(".jobList .jobItem, .jobItem, .searchResult, .job-result, li.job, div.job")
                print(f"  Found {len(job_elements)} potential job card elements with basic CSS selectors.")
                
                # Let's inspect titles or links
                links = [a.get("href") for a in soup.find_all("a", href=True) if "/job/" in a.get("href", "").lower() or "/Job/" in a.get("href", "")]
                print(f"  Found {len(links)} job link anchors matching '/job/'.")
                if links:
                    for l in links[:3]:
                        print(f"    Link: {l}")
                    return True
        except Exception as e:
            print(f"  ✕ HTTP Search error on {url}: {e}")
    return False


async def test_playwright_discovery_and_scrape(keyword: str = "Python Developer", location: str = "London"):
    """Tests Headless Playwright interactive search on Jobserve and parses results."""
    print(f"\n[3] Testing Playwright Interactive Search on Jobserve for '{keyword}' in '{location}'...")
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  ✕ Playwright not installed. Skipping Playwright test.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()

        # Intercept AJAX / XHR responses to catch any JSON/XML search data
        async def handle_response(response):
            if "retrievejobs" in response.url.lower():
                print(f"\n  [★ XHR Hit] {response.request.method} {response.url}")
                try:
                    data = await response.json()
                    if isinstance(data, dict) and "d" in data:
                        d_val = data["d"]
                        if isinstance(d_val, dict):
                            for k, v in d_val.items():
                                if isinstance(v, list):
                                    print(f"  Field '{k}' -> List with {len(v)} items")
                                    if v:
                                        print(f"  Sample from '{k}':\n{json.dumps(v[0], indent=2)[:800]}")
                                else:
                                    print(f"  Field '{k}' -> {type(v)}")
                except Exception as ex:
                    print(f"  Could not parse JSON from RetrieveJobs: {ex}")
            elif "retrievesinglejobdetail" in response.url.lower():
                print(f"\n  [★ XHR Hit] {response.request.method} {response.url}")
                try:
                    data = await response.json()
                    print(f"  ✓ RetrieveSingleJobDetail Keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    if isinstance(data, dict) and "d" in data:
                        print(f"  ✓ Sample Job Detail excerpt:\n{json.dumps(data['d'], indent=2)[:600]}")
                except Exception as ex:
                    print(f"  Could not parse JSON from RetrieveSingleJobDetail: {ex}")
        page.on("response", handle_response)

        home_url = "https://www.jobserve.com/gb/en/Job-Search/"
        print(f"  -> Navigating to: {home_url}")
        
        try:
            await page.goto(home_url, wait_until="networkidle", timeout=20000)
            
            # Dismiss cookie banner
            try:
                cookie_accept = page.locator("a:has-text('Accept All'), button:has-text('Accept'), #onetrust-accept-btn-handler, #btnAccept, a.cookieConsentOK")
                if await cookie_accept.count() > 0:
                    await cookie_accept.first.click()
                    print("  ✓ Clicked Cookie consent banner")
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Inspect search inputs on page
            inputs = await page.query_selector_all("input[type='text'], input[type='search'], input:not([type='hidden'])")
            print(f"  Found {len(inputs)} input fields on page:")
            for inp in inputs:
                inp_id = await inp.get_attribute("id") or ""
                inp_name = await inp.get_attribute("name") or ""
                inp_ph = await inp.get_attribute("placeholder") or ""
                print(f"    - ID: '{inp_id}', Name: '{inp_name}', Placeholder: '{inp_ph}'")

            # Fill Keywords
            kw_input = page.locator("#txtKey, input[name*='txtKey'], input[placeholder*='Skills'], input[placeholder*='Keywords'], #keywords").first
            if await kw_input.count() > 0:
                await kw_input.fill(keyword)
                print(f"  ✓ Filled Keywords: '{keyword}'")

            # Fill Location
            loc_input = page.locator("#txtLoc, input[name*='txtLoc'], input[placeholder*='Location'], #location").first
            if await loc_input.count() > 0:
                await loc_input.fill(location)
                print(f"  ✓ Filled Location: '{location}'")

            # Click Search
            search_btn = page.locator("#btnSearch, input[value='Search'], button:has-text('Search'), #btnSearchJobs, input[type='submit']").first
            if await search_btn.count() > 0:
                print("  ✓ Clicking Search Button...")
                await search_btn.click()
                await page.wait_for_timeout(4000)
            else:
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(4000)

            # Analyze the results page
            current_url = page.url
            print(f"  -> Results Page URL: {current_url}")
            
            # Wait for job items to render in the results list
            await page.wait_for_selector(".jobList, .jobItem, #td_jobpositionlink, .job_header, [id^='job_']", timeout=8000)
            
            # Extract job cards directly from the live DOM
            cards_data = await page.evaluate('''() => {
                const results = [];
                // Look for job title links or job result containers
                const elements = document.querySelectorAll("a[id*='jobposition'], a[href*='job'], .jobListItem, .job_header, div.jobItem, tr[id*='job']");
                
                // Jobserve search results table / list items
                const jobListItems = document.querySelectorAll(".jobItem, .jobListItem, tr[id^='job_'], div[id^='job_'], .jobResult");
                if (jobListItems.length > 0) {
                    jobListItems.forEach(el => {
                        const titleEl = el.querySelector("a, .title, .position, h2, h3, [id*='title']");
                        const compEl = el.querySelector(".company, .recruiter, .employer, [id*='company']");
                        const locEl = el.querySelector(".location, [id*='loc']");
                        const rateEl = el.querySelector(".rate, .salary, [id*='rate'], [id*='salary']");
                        results.push({
                            title: titleEl ? titleEl.innerText.trim() : el.innerText.split('\\n')[0],
                            company: compEl ? compEl.innerText.trim() : "",
                            location: locEl ? locEl.innerText.trim() : "",
                            rate: rateEl ? rateEl.innerText.trim() : "",
                            html: el.outerHTML.substring(0, 300)
                        });
                    });
                } else {
                    // Fallback to all title links
                    document.querySelectorAll("a").forEach(a => {
                        if (a.innerText && a.innerText.length > 10 && (a.id.includes('position') || a.href.includes('job') || a.title)) {
                            results.push({
                                title: a.title || a.innerText.trim(),
                                href: a.href,
                                id: a.id,
                                html: a.outerHTML
                            });
                        }
                    });
                }
                return results;
            }''')
            
            print(f"\n  ✓ Found {len(cards_data)} job elements in live DOM via evaluate!")
            for idx, c in enumerate(cards_data[:5], 1):
                print(f"    {idx}. Title: {c.get('title')}\n       Info: {c.get('company')} | {c.get('location')} | {c.get('rate')}\n       HTML snippet: {c.get('html')[:200]}")


        except Exception as e:
            print(f"  ✕ Playwright error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()


def main():
    print("=" * 70)
    print(" Jobserve Integration Independent Test Script")
    print("=" * 70)
    
    test_rss_feed("Python", "London")
    test_http_search("Python", "London")
    asyncio.run(test_playwright_discovery_and_scrape("Python Developer", "London"))
    print("\n" + "=" * 70)
    print(" Test execution complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()

