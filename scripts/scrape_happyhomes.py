#!/usr/bin/env python3
"""
Aruba Happy Homes property listing scraper.
Source: https://arubahappyhomes.com

Scrapes LAND listings only — per product decision, Happy Homes contributes
only land to sales (Market Listings) and its own LTR/STR to the rentals page.
Houses, condos, and commercial are excluded.

Name format: "Land [Area] [Size]m²" built from real scraped fields.
$0 prices and 0/blank sizes are stored as null, not as misleading zeros.

Usage:
    python3 scrape_happyhomes.py

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
from deduplicate import dedup_within_site, parse_price_robust, parse_two_sizes, restore_user_fields

BASE_URL   = "https://arubahappyhomes.com"
AGENCY     = "Aruba Happy Homes"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

# Land only — houses/condos/commercial excluded by design
SEARCH_SECTIONS = [
    ("/listings/for-sale/land", "land"),
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_sqm(text):
    """Return integer m² from a size string like '970 m²', or None if absent/zero."""
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*m", text, re.I)
    if not m:
        return None
    val = int(m.group(1).replace(",", ""))
    return val if val > 0 else None


def format_size(sqm):
    """'970 m²' string for display, or None."""
    return f"{sqm:,} m²" if sqm else None


def make_name(area, sqm):
    """
    Consistent land listing name built from real fields only.
    Examples: "Land Savaneta 970 m²"  /  "Land Noord"  (no size if unknown)
    """
    parts = ["Land"]
    if area:
        parts.append(area)
    if sqm:
        parts.append(f"{sqm:,} m²")
    return " ".join(parts)


def parse_card(card):
    link_el  = card.find("a", class_="link-cover")
    area_el  = card.find(class_="area")
    price_el = card.find(class_="price")
    opts     = card.find_all(class_="option__value")

    href  = (link_el["href"] if link_el else "").strip()
    area  = clean(area_el.get_text()) if area_el else ""
    raw_price = parse_price_robust(price_el.get_text() if price_el else "")
    price = raw_price if raw_price else None          # $0 → None

    # First option value is size
    card_size_text = clean(opts[0].get_text()) if opts else ""
    card_sqm       = parse_sqm(card_size_text)

    return {
        "href":     href if href.startswith("http") else BASE_URL + href,
        "area":     area,
        "price":    price,
        "card_sqm": card_sqm,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        # Image
        img = soup.find("img", class_="listing")
        if not img:
            img = soup.select_one(".gallery img, .slider img, .photo img, article img")
        image = (img.get("src") or img.get("data-src") or "") if img else ""

        # Description
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc  = max(paras, key=len, default="")

        # Sizes from full page text
        building_size, lot_size = parse_two_sizes(soup.get_text(" ", strip=True))

        return image, desc, building_size, lot_size
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return "", "", "", ""


def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {BASE_URL}{section_path}")
        page.goto(BASE_URL + section_path, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)

        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all(class_="rent-contain")
        print(f"   {len(cards)} cards")

        for card in cards:
            data = parse_card(card)
            url  = data["href"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            image, desc, detail_building, detail_lot = scrape_detail(page, url)
            time.sleep(0.4)

            # Prefer detail-page sizes; fall back to card value
            lot_sqm      = parse_sqm(detail_lot) or parse_sqm(detail_building) or data["card_sqm"]
            building_sqm = parse_sqm(detail_building) or None

            size_str     = format_size(lot_sqm)
            building_str = format_size(building_sqm)
            lot_str      = format_size(lot_sqm)

            name = make_name(data["area"], lot_sqm)
            slug = url.rstrip("/").split("/")[-1]

            print(f"     → {name}  |  price={'${:,}'.format(data['price']) if data['price'] else 'N/A'}")

            results.append({
                "id":           slug,
                "name":         name,
                "type":         listing_type,
                "image":        image,
                "area":         data["area"],
                "location":     data["area"],
                "askPrice":     data["price"],
                "size":         size_str or "",
                "buildingSize": building_str or "",
                "lotSize":      lot_str or "",
                "bedrooms":     None,
                "bathrooms":    None,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    url,
                "status":       "active",
                "priceHistory": [{"date": TODAY, "price": data["price"]}],
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

    current    = existing.get("listings", [])
    # Match both old schema (agency) and new schema (source) to ensure full cleanup
    old_agency = [l for l in current if l.get("agency") == AGENCY or l.get("source") == AGENCY]
    kept       = [l for l in current if l.get("agency") != AGENCY and l.get("source") != AGENCY]
    new_listings = restore_user_fields(old_agency, new_listings)
    merged     = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} {AGENCY} land listings → {DATA_JSON} ({len(merged)} total)")


if __name__ == "__main__":
    print(f"{AGENCY} scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
