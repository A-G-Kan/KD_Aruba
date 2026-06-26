#!/usr/bin/env python3
"""
CC Real Estate Aruba property listing scraper.
Source: https://www.ccrealestatearuba.com

Wix-based site. 73 listings load via JavaScript into
.wixui-repeater__item elements.

Usage:
    python3 scrape_cc_realestate.py

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
from deduplicate import dedup_within_site, parse_price_robust, parse_two_sizes, infer_listing_type, restore_user_fields

BASE_URL   = "https://www.ccrealestatearuba.com"
AGENCY     = "CC Real Estate Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

CC_STATUS_MAP = {
    "sold":          "sold",
    "under offer":   "under offer",
    "price reduced": "price reduced",
    "on hold":       "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)

def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(item):
    text = item.get_text(" ")

    # Name: usually in an h1/h2/h3 or the first prominent text
    h = item.find(["h1", "h2", "h3", "h4"])
    name = clean(h.get_text()) if h else ""
    if not name:
        # Grab first non-empty text node
        for el in item.descendants:
            t = clean(getattr(el, "string", "") or "")
            if t and len(t) > 5 and not re.match(r"^(FOR SALE|FOR RENT|\$|AWG|\d)", t):
                name = t
                break
    if not name:
        name = "Unknown"

    # Image
    img_el = item.find("img") or item.find("wix-image")
    image  = ""
    if img_el:
        image = img_el.get("src") or img_el.get("data-src") or ""

    price = parse_price(text)

    # Beds / baths / size
    beds  = parse_int(re.search(r"(\d+)\s*[Bb]ed", text).group(1) if re.search(r"(\d+)\s*[Bb]ed", text) else "")
    baths = parse_int(re.search(r"(\d+)\s*[Bb]ath", text).group(1) if re.search(r"(\d+)\s*[Bb]ath", text) else "")
    m = re.search(r"([\d,.]+)\s*(m²|m2|sqm|sq\.?\s*ft)", text, re.I)
    size = m.group(0).strip() if m else ""

    building_size, lot_size = parse_two_sizes(text)
    # If parse_two_sizes found nothing but regex got a raw m² value, it's likely building size
    if not building_size and not lot_size and size:
        building_size = size

    # Status
    status = "active"
    for key, val in CC_STATUS_MAP.items():
        if key in text.lower():
            status = val
            break

    # Link — Wix items often don't have standard <a> tags in the repeater
    link_el = item.find("a", href=True)
    href    = link_el["href"] if link_el else ""
    if href and not href.startswith("http"):
        href = BASE_URL + href

    return {
        "name":         name,
        "href":         href,
        "image":        image,
        "area":         "",
        "location":     "",
        "askPrice":     price,
        "size":         size,
        "buildingSize": building_size,
        "lotSize":      lot_size,
        "bedrooms":     beds,
        "bathrooms":    baths,
        "status":       status,
        "_text":        text,   # full card text for type inference
    }


def scrape_all():
    results = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()

        url = f"{BASE_URL}/properties-1"
        print(f"\n▶  {url}")
        try:
            page.goto(url, timeout=40000, wait_until="domcontentloaded")
            # Wix needs extra time to hydrate
            time.sleep(6)

            # Scroll to trigger lazy loading
            for _ in range(5):
                page.keyboard.press("End")
                time.sleep(1.5)

            soup  = BeautifulSoup(page.content(), "html.parser")
            items = soup.find_all(class_="wixui-repeater__item")
            print(f"   {len(items)} cards")

            for i, item in enumerate(items):
                data = parse_card(item)
                if not data["name"] or data["name"] == "Unknown":
                    continue

                key = data["href"] or data["name"]
                if key in seen:
                    continue
                seen.add(key)

                print(f"     → {data['name'][:50]}")

                slug = re.sub(r"[^\w-]", "-", data["name"].lower())[:50] + f"-{i}"
                results.append({
                    "id":           slug,
                    "name":         data["name"],
                    "type":         infer_listing_type(data["name"], data.get("_text", "")),
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     data["askPrice"],
                    "size":         data["size"],
                    "buildingSize": data["buildingSize"],
                    "lotSize":      data["lotSize"],
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    data["href"] or url,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        "",
                })

        finally:
            ctx.close()
        browser.close()

    return results


def save(new_listings):
    new_listings, _ = dedup_within_site(new_listings, AGENCY)
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    old_agency   = [l for l in current if l.get("agency") == AGENCY]
    kept    = [l for l in current if l.get("agency") != AGENCY]
    new_listings = restore_user_fields(old_agency, new_listings)
    merged       = kept + new_listings

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
