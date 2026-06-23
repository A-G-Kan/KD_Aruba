#!/usr/bin/env python3
"""
Alto Vista Real Estate Aruba property listing scraper.
Source: https://altovistarealestate.com

Uses WP-Property / WPL plugin.

Usage:
    python3 scrape_altovista.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BASE_URL   = "https://altovistarealestate.com"
AGENCY     = "Alto Vista Real Estate"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

LISTING_PAGES = [
    (f"{BASE_URL}/for-sale/",        "house"),
    (f"{BASE_URL}/condominium/",     "condo"),
    (f"{BASE_URL}/land-for-sale/",   "land"),
]

ALTOVISTA_STATUS_MAP = {
    "sold":          "sold",
    "under offer":   "under offer",
    "price reduced": "price reduced",
    "on hold":       "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    text = text or ""
    m = re.search(r"\$\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"([\d.]+)\s*(?:AWG|Afl)", text)
    if m:
        raw = m.group(1).replace(".", "")
        return int(raw) if raw.isdigit() else None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits and len(digits) > 4 else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def scrape_listing_page(browser, url, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {url}")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

        soup = BeautifulSoup(page.content(), "html.parser")

        # WPL property rows
        rows = soup.find_all(class_=re.compile(r"wpl_property_listing_row|wpl-listing-row|property_row", re.I))
        if not rows:
            # Try generic list items with price info
            rows = [el for el in soup.find_all(["div", "article", "li"])
                    if el.find(class_=re.compile(r"wpl-listing-tags|price", re.I))]

        print(f"   {len(rows)} cards")

        for row in rows:
            # Link
            link_el = row.find("a", href=True)
            href    = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = BASE_URL + href
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            # Image
            img_el = row.find("img")
            image  = (img_el.get("src") or img_el.get("data-src") or "") if img_el else ""

            # Name
            h = row.find(["h2", "h3", "h4"])
            name = clean(h.get_text() if h else link_el.get_text())

            # Price
            price_el = row.find(class_=re.compile(r"wpl-price|price", re.I))
            price = parse_price(price_el.get_text() if price_el else row.get_text())

            # Beds / baths / size
            text = row.get_text(" ")
            beds  = parse_int(re.search(r"(\d+)\s*[Bb]ed", text).group(1) if re.search(r"(\d+)\s*[Bb]ed", text) else "")
            baths = parse_int(re.search(r"(\d+)\s*[Bb]ath", text).group(1) if re.search(r"(\d+)\s*[Bb]ath", text) else "")
            m = re.search(r"([\d,.]+)\s*(m²|m2|sqm|sq\.?\s*ft)", text, re.I)
            size = m.group(0).strip() if m else ""

            # Status from tag
            status = "active"
            for tag in row.find_all(class_=re.compile(r"wpl-listing-tags|status-tag|label", re.I)):
                st = clean(tag.get_text()).lower()
                if st in ALTOVISTA_STATUS_MAP:
                    status = ALTOVISTA_STATUS_MAP[st]
                    break

            # Location
            loc_el = row.find(class_=re.compile(r"location|address|area", re.I))
            location = clean(loc_el.get_text()) if loc_el else ""

            print(f"     → {name[:50]}")

            # Detail page for description
            try:
                page.goto(href, timeout=20000, wait_until="domcontentloaded")
                time.sleep(0.8)
                detail = BeautifulSoup(page.content(), "html.parser")
                paras  = [p.get_text(strip=True) for p in detail.find_all("p") if len(p.get_text(strip=True)) > 60]
                desc   = max(paras, key=len, default="")
            except Exception:
                desc = ""
            time.sleep(0.4)

            slug = href.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         name,
                "type":         listing_type,
                "image":        image,
                "area":         location,
                "location":     location,
                "askPrice":     price,
                "size":         size,
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
        for url, listing_type in LISTING_PAGES:
            listings.extend(scrape_listing_page(browser, url, listing_type, seen_urls))
            time.sleep(2)
        browser.close()
    return listings


def save(new_listings):
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    kept    = [l for l in current if l.get("agency") != AGENCY]
    merged  = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       TODAY,
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
