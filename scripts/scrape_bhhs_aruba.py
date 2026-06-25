#!/usr/bin/env python3
"""
Berkshire Hathaway HomeServices (BHHS) Aruba property listing scraper.
Source: https://www.bhhsaruba.com

All 116 residential listings load on a single page.
Card has image, name, property type, lot size, built-up size.
Detail page adds price, beds, bathrooms, and description.

Usage:
    python3 scrape_bhhs_aruba.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import dedup_within_site, parse_price_robust, parse_two_sizes

BASE_URL   = "https://www.bhhsaruba.com"
AGENCY     = "BHHS Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/residential-for-sale",   "house"),
    ("/commercial-for-sale",    "commercial"),
    ("/condominium-for-sale",   "condo"),
    ("/land-for-sale",          "land"),
]

BHHS_STATUS_MAP = {
    "price reduced": "price reduced",
    "sold":          "sold",
    "under offer":   "under offer",
    "on hold":       "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def _valid_size(s):
    """Return s if it parses to ≥ 10 m², otherwise '' (rejects floor counts etc.)."""
    if not s:
        return ""
    m = re.search(r"[\d,.]+", s)
    if not m:
        return ""
    try:
        v = float(m.group().replace(",", ""))
        return s if v >= 10 else ""
    except ValueError:
        return ""


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        price = parse_price_robust(text)

        beds = baths = None
        m = re.search(r"(\d+)\s*bed", text, re.I)
        if m:
            beds = int(m.group(1))
        m = re.search(r"(\d+)\s*bath", text, re.I)
        if m:
            baths = int(m.group(1))

        building_size, lot_size = parse_two_sizes(text)
        building_size = _valid_size(building_size)
        lot_size      = _valid_size(lot_size)

        # Status tag
        status = "active"
        for span in soup.find_all(class_="preview-property__tag"):
            t = span.get_text(strip=True).lower()
            status = BHHS_STATUS_MAP.get(t, status)

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return price, beds, baths, building_size, lot_size, status, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, None, "", "", "active", ""


def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {section_path}")
        page.goto(BASE_URL + section_path, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2.5)

        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all(class_="preview-properties__item")
        print(f"   {len(cards)} cards")

        for card in cards:
            link_el = card.find("a", class_="preview-property__image")
            href    = link_el["href"] if link_el else ""
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            img_el = card.find("img", class_="preview-property__image-img")
            image  = img_el["src"] if img_el else ""
            name   = (link_el.get("title") or "").strip() or "Unknown"

            print(f"     → {name[:50]}")
            price, beds, baths, building_size, lot_size, status, desc = scrape_detail(page, href)
            time.sleep(0.4)

            slug = href.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         name,
                "type":         listing_type,
                "image":        image,
                "area":         "",
                "location":     "",
                "askPrice":     price,
                "size":         building_size or lot_size,
                "buildingSize": building_size,
                "lotSize":      lot_size,
                "bedrooms":     beds,
                "bathrooms":    baths,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    href,
                "status":       status,
                "priceHistory": [{"date": TODAY, "price": price}],
                "notes":        desc,
            })
    finally:
        ctx.close()

    return results


def scrape_all():
    listings = []
    seen_urls = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for section_path, listing_type in SEARCH_SECTIONS:
            listings.extend(scrape_section(browser, section_path, listing_type, seen_urls))
            time.sleep(2)
        browser.close()
    return listings


def save(new_listings):
    new_listings, _ = dedup_within_site(new_listings, AGENCY)
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    kept    = [l for l in current if l.get("agency") != AGENCY]
    merged  = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} {AGENCY} listings → {DATA_JSON} ({len(merged)} total)")


if __name__ == "__main__":
    print(f"{AGENCY} scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
