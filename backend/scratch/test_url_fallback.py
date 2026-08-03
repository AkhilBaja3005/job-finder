import sys
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import _extract_company_from_jd

def test_url_parser():
    url = "https://www.indeed.com/cmp/Apple?campaignid=mobvjcmp&from=mobviewjob&tk=1jv1dk83ah3l3800&fromjk=4c1018a1d2d2bf7e"
    print("Testing URL parsing for Indeed /cmp/ link:", url)
    
    company = _extract_company_from_jd("Failed to retrieve full job details automatically.", url)
    print("✓ Extracted Company from /cmp/ link:", company)

if __name__ == "__main__":
    test_url_parser()
