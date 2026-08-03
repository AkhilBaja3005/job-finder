import urllib.request
import re
from bs4 import BeautifulSoup

urls = [
    "https://www.indeed.com/viewjob?jk=bc648143fe26ee4f",
    "https://www.indeed.com/viewjob?jk=059945040a6a3e85",
    "https://www.indeed.com/viewjob?jk=472525ccef9e96fd",
    "https://www.indeed.com/viewjob?jk=ea2c5e32ab039b3c"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

print("\n" + "=" * 65)
print("🔎 INDEED LINK COMPANY NAME & TITLE EXTRACTION")
print("=" * 65)

for idx, url in enumerate(urls, 1):
    print(f"\n[{idx}] URL: {url}")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            
            # Title
            title_tag = soup.find('title')
            raw_title = title_tag.get_text() if title_tag else "Unknown"
            
            # Company /cmp/ anchor or meta
            company = "Target Hiring Company"
            cmp_match = re.search(r'/cmp/([a-zA-Z0-9%_\-]+)', html)
            if cmp_match:
                company = cmp_match.group(1).replace('+', ' ').replace('-', ' ').title()
            
            print(f"    🏷️ Title/Meta: {raw_title.strip()[:80]}")
            print(f"    🏢 Company:    {company}")
    except Exception as e:
        print(f"    ⚠️ HTTP Request failed ({e}). Extracting from URL ID fallback:")
        jk_val = url.split("jk=")[1]
        print(f"    🏷️ Fallback Title: Indeed Job ({jk_val[:8]})")
        print(f"    🏢 Fallback Company: Target Hiring Company")

print("=" * 65 + "\n")
