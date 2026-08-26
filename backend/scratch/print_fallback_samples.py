import urllib.request
import urllib.parse
import ssl
import re
from bs4 import BeautifulSoup

def test_indeed_fallback_live():
    keyword = "Data Scientist"
    location = "UK"
    g_query = f"site:indeed.com/viewjob \"{keyword}\" {location}"
    g_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(g_query)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    ssl_ctx = ssl._create_unverified_context()
    
    print("\n" + "=" * 70)
    print("🔎 LIVE TEST: INDEED SEARCH FALLBACK RESULTS")
    print("=" * 70)
    
    try:
        req = urllib.request.Request(g_url, headers=headers)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
            g_html = resp.read().decode("utf-8", errors="ignore")
            g_soup = BeautifulSoup(g_html, "html.parser")
            
            results = []
            for a_tag in g_soup.select("a.result__url"):
                href = a_tag.get("href") or ""
                snip_td = a_tag.find_parent("td")
                title_text = ""
                if snip_td:
                    t_elem = snip_td.select_one(".result__title")
                    if t_elem:
                        title_text = t_elem.get_text(strip=True)
                
                if "indeed.com" in href or "jk=" in href:
                    clean_title = title_text.split(" - ")[0].split(" | ")[0] if title_text else f"{keyword} Role"
                    comp_name = title_text.split(" - ")[1].strip() if (" - " in title_text and len(title_text.split(" - ")) > 1) else "Indeed Employer"
                    results.append({
                        "title": clean_title,
                        "company": comp_name,
                        "url": href
                    })
            
            print(f"\nFound {len(results)} Indeed Jobs:\n")
            for idx, job in enumerate(results[:10], 1):
                print(f"[{idx}] 🏷️ Title:   {job['title']}")
                print(f"    🏢 Company: {job['company']}")
                print(f"    🔗 URL:     {job['url']}\n")
    except Exception as e:
        print(f"Error fetching live fallback results: {e}")

    print("=" * 70 + "\n")

if __name__ == "__main__":
    test_indeed_fallback_live()
