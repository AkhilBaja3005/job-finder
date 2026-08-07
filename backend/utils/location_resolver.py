"""
Location parser & country resolver for routing job scrapers (Indeed regional domains, Reed UK gating).
"""

import re
from typing import Tuple

# Country ISO2 code -> Indeed domain mapping
INDEED_DOMAINS = {
    "IN": "in.indeed.com",
    "GB": "uk.indeed.com",
    "UK": "uk.indeed.com",
    "US": "www.indeed.com",
    "CA": "ca.indeed.com",
    "AU": "au.indeed.com",
    "DE": "de.indeed.com",
    "FR": "fr.indeed.com",
    "SG": "sg.indeed.com",
    "AE": "ae.indeed.com",
    "IE": "ie.indeed.com",
    "NZ": "nz.indeed.com",
    "ZA": "za.indeed.com",
    "JP": "jp.indeed.com",
    "BR": "br.indeed.com",
    "MX": "mx.indeed.com",
    "NL": "nl.indeed.com",
    "ES": "es.indeed.com",
    "IT": "it.indeed.com",
    "CH": "ch.indeed.com",
    "SE": "se.indeed.com",
    "PL": "pl.indeed.com",
    "MY": "malaysia.indeed.com",
    "PH": "ph.indeed.com",
    "HK": "hk.indeed.com",
    "KR": "kr.indeed.com",
    "SA": "sa.indeed.com",
    "QA": "qa.indeed.com",
}

# Subcountry / Region / City mapping to ISO2
LOCATION_COUNTRY_MAP = {
    # India States / Cities / Identifiers
    "hyderabad": "IN",
    "telangana": "IN",
    "bengaluru": "IN",
    "bangalore": "IN",
    "karnataka": "IN",
    "mumbai": "IN",
    "maharashtra": "IN",
    "pune": "IN",
    "delhi": "IN",
    "new delhi": "IN",
    "noida": "IN",
    "gurgaon": "IN",
    "gurugram": "IN",
    "chennai": "IN",
    "tamil nadu": "IN",
    "kolkata": "IN",
    "west bengal": "IN",
    "ahmedabad": "IN",
    "gujarat": "IN",
    "kochi": "IN",
    "kerala": "IN",
    "india": "IN",
    "in": "IN",

    # UK Cities / Regions
    "london": "GB",
    "manchester": "GB",
    "birmingham": "GB",
    "edinburgh": "GB",
    "glasgow": "GB",
    "bristol": "GB",
    "leeds": "GB",
    "cambridge": "GB",
    "oxford": "GB",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "gb": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",

    # Canada
    "toronto": "CA",
    "vancouver": "CA",
    "montreal": "CA",
    "calgary": "CA",
    "ottawa": "CA",
    "ontario": "CA",
    "quebec": "CA",
    "british columbia": "CA",
    "alberta": "CA",
    "canada": "CA",
    "ca": "CA",

    # Australia
    "sydney": "AU",
    "melbourne": "AU",
    "brisbane": "AU",
    "perth": "AU",
    "adelaide": "AU",
    "australia": "AU",
    "au": "AU",

    # US Cities / States
    "new york": "US",
    "san francisco": "US",
    "austin": "US",
    "seattle": "US",
    "boston": "US",
    "chicago": "US",
    "los angeles": "US",
    "california": "US",
    "texas": "US",
    "washington": "US",
    "united states": "US",
    "usa": "US",
    "us": "US",

    # Germany
    "berlin": "DE",
    "munich": "DE",
    "frankfurt": "DE",
    "hamburg": "DE",
    "germany": "DE",
    "deutschland": "DE",
    "de": "DE",

    # Singapore
    "singapore": "SG",
    "sg": "SG",

    # UAE
    "dubai": "AE",
    "abu dhabi": "AE",
    "uae": "AE",
    "united arab emirates": "AE",
    "ae": "AE",

    # Japan
    "tokyo": "JP",
    "osaka": "JP",
    "japan": "JP",
    "jp": "JP",

    # Ireland
    "dublin": "IE",
    "cork": "IE",
    "ireland": "IE",
    "ie": "IE",
}


def resolve_location_country(location_str: str) -> str:
    """
    Parses a location string (e.g. 'Hyderabad, Telangana', 'London, UK', 'San Francisco, CA')
    and returns the 2-letter ISO country code. Defaults to 'US' if unknown.
    """
    if not location_str:
        return "US"

    loc_clean = location_str.lower().strip()
    
    # Split by comma or whitespace
    parts = [p.strip() for p in re.split(r'[,/-]+', loc_clean) if p.strip()]

    # Check parts from right to left (since country/state usually appears at the end)
    for part in reversed(parts):
        if part in LOCATION_COUNTRY_MAP:
            return LOCATION_COUNTRY_MAP[part]

    # Also check full string matches or token presence
    for token, country_code in LOCATION_COUNTRY_MAP.items():
        if re.search(r'\b' + re.escape(token) + r'\b', loc_clean):
            return country_code

    return "US"


def get_indeed_domain_for_location(location_str: str) -> Tuple[str, str]:
    """
    Returns tuple of (domain_name, country_code) for a given location string.
    Example: 'Hyderabad, Telangana' -> ('in.indeed.com', 'IN')
    """
    country_code = resolve_location_country(location_str)
    domain = INDEED_DOMAINS.get(country_code, "www.indeed.com")
    return domain, country_code
