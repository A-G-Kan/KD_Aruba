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
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import dedup_within_site, parse_price_robust, parse_two_sizes, infer_listing_type

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
    return parse_price_robust(text)

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

        # WPL plugin uses wpl_prp_cont as the card container
        rows = soup.find_all(class_="wpl_prp_cont")
        print(f"   {len(rows)} cards")

        for row in rows:
            # Link (view_detail anchor has the property URL and name)
            link_el = row.find("a", class_="view_detail", href=lambda h: h and "/properties/" in h)
            if not link_el:
                link_el = row.find("a", href=lambda h: h and "/properties/" in h)
            href = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = BASE_URL + href
            if not href or href == BASE_URL or href in seen_urls:
                continue
            seen_urls.add(href)

            # Image — WPL stores the gallery image as a background or img inside the flip card
            img_el = row.find("img")
            image  = (img_el.get("src") or img_el.get("data-src") or "") if img_el else ""

            # Name
            h = row.find("h3", class_="wpl_prp_title") or row.find(["h2", "h3", "h4"])
            name = clean(h.get_text() if h else (link_el.get_text() if link_el else "Unknown"))

            # Price
            price_el = row.find(class_="price_box")
            price = parse_price(price_el.get_text() if price_el else "")

            # Size from built_up_area → buildingSize (skip zero values from WPL placeholder)
            size_el = row.find(class_="built_up_area")
            size_raw = clean(size_el.get_text()) if size_el else ""
            m = re.search(r"([\d,.]+)\s*(m²|m2|sqm|sq\.?\s*ft)", size_raw or row.get_text(), re.I)
            if m:
                raw_num = float(re.sub(r"[^\d.]", "", m.group(1).replace(",", "")) or "0")
                building_size = m.group(0).strip() if raw_num > 0 else ""
            else:
                building_size = ""

            # Lot size from WPL lot-area classes
            lot_size = ""
            for lot_cls in ("lot_area", "wpl_prp_listing_lot_size", "land_area"):
                lot_el = row.find(class_=lot_cls)
                if lot_el:
                    lot_raw = clean(lot_el.get_text())
                    ml = re.search(r"([\d,.]+)\s*(m²|m2|sqm|sq\.?\s*ft)", lot_raw, re.I)
                    if ml:
                        raw_num = float(re.sub(r"[^\d.]", "", ml.group(1).replace(",", "")) or "0")
                        lot_size = ml.group(0).strip() if raw_num > 0 else ""
                    break

            # Beds / baths from text
            text = row.get_text(" ")
            beds  = parse_int(re.search(r"(\d+)\s*[Bb]ed", text).group(1) if re.search(r"(\d+)\s*[Bb]ed", text) else "")
            baths = parse_int(re.search(r"(\d+)\s*[Bb]ath", text).group(1) if re.search(r"(\d+)\s*[Bb]ath", text) else "")

            # Status from tag
            status = "active"
            for tag in row.find_all(class_="wpl-listing-tag"):
                st = clean(tag.get_text()).lower()
                if st in ALTOVISTA_STATUS_MAP:
                    status = ALTOVISTA_STATUS_MAP[st]
                    break

            # Location
            loc_el = row.find("h4", class_="wpl_prp_listing_location")
            location = clean(loc_el.get_text()) if loc_el else ""

            print(f"     → {name[:50]}")

            # Detail page for description + supplement sizes
            try:
                page.goto(href, timeout=20000, wait_until="domcontentloaded")
                time.sleep(0.8)
                detail = BeautifulSoup(page.content(), "html.parser")
                paras  = [p.get_text(strip=True) for p in detail.find_all("p") if len(p.get_text(strip=True)) > 60]
                desc   = max(paras, key=len, default="")
                detail_text = detail.get_text(" ", strip=True)
                detail_building, detail_lot = parse_two_sizes(detail_text)
                if not building_size and detail_building:
                    building_size = detail_building
                if not lot_size and detail_lot:
                    lot_size = detail_lot
            except Exception:
                desc = ""
            time.sleep(0.4)

            size = building_size or lot_size
            # /for-sale/ is a catch-all; infer actual type from name + description.
            # Dedicated /condominium/ and /land-for-sale/ sections stay as-is.
            effective_type = (infer_listing_type(name, desc)
                              if listing_type == "house" else listing_type)
            slug = href.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         name,
                "type":         effective_type,
                "image":        image,
                "area":         location,
                "location":     location,
                "askPrice":     price,
                "size":         size,
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
        for url, listing_type in LISTING_PAGES:
            try:
                listings.extend(scrape_listing_page(browser, url, listing_type, seen_urls))
            except Exception as e:
                print(f"  ⚠  Section {url} skipped: {e}")
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
