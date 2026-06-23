#!/usr/bin/env python3
"""
Prima Casa Real Estate Group property listing scraper.
Source: https://aruba-realty.com

Scrapes active sales listings. Card has link, image, status, price, and location.
Detail page adds beds, bathrooms, size, and description.

Usage:
    python3 scrape_primacasa.py

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

BASE_URL   = "https://aruba-realty.com"
AGENCY     = "Prima Casa Real Estate"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

PRIMACASA_STATUS_MAP = {
    "price upon request": "active",
    "for sale":           "active",
    "sold":               "sold",
    "under offer":        "under offer",
    "price reduced":      "price reduced",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    text = text or ""
    if re.search(r"price\s*(upon|on)\s*request", text, re.I):
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_status(status_text):
    st = clean(status_text).lower()
    return PRIMACASA_STATUS_MAP.get(st, "active")


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        beds = baths = None
        m = re.search(r"(\d+)\s*bed", text, re.I)
        if m:
            beds = int(m.group(1))
        m = re.search(r"(\d+)\s*bath", text, re.I)
        if m:
            baths = int(m.group(1))

        size = ""
        m = re.search(r"([\d,.]+)\s*(m²|sqm|sq\.?\s*ft)", text, re.I)
        if m:
            size = m.group(0).strip()

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return beds, baths, size, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, "", ""


def scrape_all():
    results = []
    seen_urls = set()
    url = f"{BASE_URL}/listings/active-sales"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()

        try:
            print(f"\n▶  {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all("a", class_="property")
            print(f"   {len(cards)} cards")

            for card in cards:
                href = card.get("href", "")
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                img_el   = card.find("img")
                image    = img_el["src"] if img_el else ""
                status_el = card.find(class_="status")
                price_el  = card.find(class_="price")
                loc_el    = card.find(class_="location")
                title_el  = card.find(class_="title")

                status_raw = clean(status_el.get_text()) if status_el else ""
                price_raw  = clean(price_el.get_text())  if price_el  else ""
                name       = clean(title_el.get_text())  if title_el  else "Unknown"
                location   = clean(loc_el.get_text())    if loc_el    else ""

                # strip the inline price-status label from the price text
                price_clean = re.sub(r"price upon request", "", price_raw, flags=re.I).strip()
                price = parse_price(price_clean or price_raw)
                status = parse_status(status_raw or price_raw)

                print(f"     → {name[:50]}")
                beds, baths, size, desc = scrape_detail(page, href)
                time.sleep(0.4)

                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":           slug,
                    "name":         name,
                    "type":         "house",
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
        browser.close()

    return results


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
