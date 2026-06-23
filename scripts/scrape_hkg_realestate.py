#!/usr/bin/env python3
"""
HKG Real Estate Aruba property listing scraper.
Source: https://hkgrealestatearuba.com

Uses the Houzez WordPress theme. 10 listings currently active.

Usage:
    python3 scrape_hkg_realestate.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from scrape_houzez import scrape_houzez_site, save_houzez

AGENCY     = "HKG Real Estate Aruba"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

LISTING_PAGES = [
    ("https://hkgrealestatearuba.com/property/",                      "house"),
    ("https://hkgrealestatearuba.com/property-type/residential/",     "house"),
    ("https://hkgrealestatearuba.com/property-type/condominium/",     "condo"),
    ("https://hkgrealestatearuba.com/property-type/land/",            "land"),
    ("https://hkgrealestatearuba.com/property-type/commercial/",      "commercial"),
]


if __name__ == "__main__":
    print(f"{AGENCY} scraper …")
    seen_urls = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listings = scrape_houzez_site(browser, "https://hkgrealestatearuba.com",
                                      AGENCY, LISTING_PAGES, USER_AGENT, seen_urls)
        browser.close()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save_houzez(listings, AGENCY)
