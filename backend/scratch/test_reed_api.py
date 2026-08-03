import urllib.request
import urllib.parse
import json
import base64
import ssl

def test_reed_api(api_key: str, keywords: str = "Data Scientist", location: str = "London"):
    url = f"https://www.reed.co.uk/api/1.0/search?keywords={urllib.parse.quote(keywords)}&locationName={urllib.parse.quote(location)}"
    
    # Reed API uses HTTP Basic Auth with API Key as the Username and empty password
    auth_str = f"{api_key}:"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "User-Agent": "JobFinderApp/1.0"
    }
    
    ssl_ctx = ssl._create_unverified_context()
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"✓ Reed API Success! Total Results: {data.get('totalResults', 0)}")
            for idx, job in enumerate(data.get("results", [])[:5], 1):
                print(f"[{idx}] {job.get('jobTitle')} at {job.get('employerName')} ({job.get('locationName')})")
                print(f"    URL: {job.get('jobUrl')}")
            return data
    except Exception as e:
        print(f"Reed API Test Error: {e}")
        return None

if __name__ == "__main__":
    test_reed_api("8cd9848f-8afd-4376-adf7-f8958c7a89f2")
