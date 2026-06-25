#!/usr/bin/env python3
"""
Century 21 Aruba property listing scraper.

Scrapes all for-sale listings and saves them into the `listings` array
in /Users/alan/Desktop/KD/Website/data.json, preserving all other
sections of that file (trackerItems, areaData, etc.).

Usage:
    python3 scrape_century21.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date, datetime, timezone
from pathlib import Path

# ── path setup for locally-installed packages ──────────────────────────────
sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import dedup_within_site, parse_price_robust, parse_two_sizes

# ── config ─────────────────────────────────────────────────────────────────
BASE_URL   = "https://century21aruba.com"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Search pages to scrape and how they map to our type field
SEARCH_SECTIONS = [
    ("/en/s/for-sale/single-family-homes", "house"),
    ("/en/s/for-sale/condos-apartments",   "condo"),
    ("/en/s/for-sale/vacant-land",         "land"),
    ("/en/s/commercial/for-sale",          "commercial"),
]

TODAY = date.today().isoformat()


# ── helpers ─────────────────────────────────────────────────────────────────

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)

def parse_size(text):
    """'5 · 3 · Ocean Front · 1,055 m²' → '1,055 m²'"""
    m = re.search(r"[\d,]+\s*m²", text or "")
    return m.group(0).strip() if m else None


def parse_beds(text):
    """'5 · 3 · Ocean Front · 1,055 m²' → 5"""
    parts = [p.strip() for p in text.split("·")]
    if len(parts) >= 2:
        m = re.match(r"^(\d+)$", parts[0].strip())
        return int(m.group(1)) if m else None
    return None


def parse_baths(text):
    parts = [p.strip() for p in text.split("·")]
    if len(parts) >= 2:
        # drop $ anchor so "8½+" and "8.5+" still yield 8
        m = re.match(r"^(\d+)", parts[1].strip())
        return int(m.group(1)) if m else None
    return None


C21_STATUS_MAP = {
    "sold":            "sold",
    "under contract":  "under offer",
    "pending offers":  "under offer",
    "price reduced":   "price reduced",
}

def parse_status(article):
    """Read the ribbon label on a C21 search card and map it to our status vocab."""
    ribbon = article.find(class_=lambda c: c and "ribbon" in c if c else False)
    if not ribbon:
        return "active"
    text = ribbon.get_text(strip=True).lower()
    return C21_STATUS_MAP.get(text, "active")


def parse_area(location_text):
    """'Pos Chiquito (Savaneta)' → 'Savaneta'"""
    m = re.search(r"\(([^)]+)\)", location_text or "")
    if m:
        return m.group(1).strip()
    return clean(location_text)


def best_image_url(img_tag):
    """Return the w780 JPEG src for a listing card image."""
    if not img_tag:
        return ""
    src = img_tag.get("src", "")
    # Prefer the w780 variant
    src_780 = re.sub(r"/w\d+/", "/w780/", src)
    # Strip the avif/webp srcset, keep jpeg
    src_jpg = re.sub(r"\.avif|\.webp", ".jpg", src_780)
    if src_jpg:
        return BASE_URL + src_jpg if src_jpg.startswith("/") else src_jpg
    return BASE_URL + src if src.startswith("/") else src


def get_pagination_urls(soup, section_path):
    """Return all paginated search URLs for a section."""
    urls = [BASE_URL + section_path]
    pager = soup.find("ul", class_="pagination")
    if not pager:
        return urls
    for a in pager.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/\d+$", href):
            full = BASE_URL + href if href.startswith("/") else href
            if full not in urls:
                urls.append(full)
    return urls


# ── card parser ──────────────────────────────────────────────────────────────

def parse_card(article, listing_type):
    """Extract fields from a search-results listing card."""
    mls_id = article.get("data-ad-id", "")

    # Price
    price_el = article.find(class_=lambda c: c and "card-header" in c)
    price     = parse_price(price_el.get_text() if price_el else "")

    # Name / location / sub-type from h2
    h2   = article.find("h2")
    spans = h2.find_all("span", recursive=False) if h2 else []
    name     = clean(spans[0].get_text()) if len(spans) > 0 else clean(article.get("data-ad-title", ""))
    location = clean(spans[1].get_text()) if len(spans) > 1 else ""

    # Bed / bath / size from the small detail span
    detail_el = article.find(class_=lambda c: c and "fs-80" in c.split())
    detail_text = clean(detail_el.get_text()) if detail_el else ""
    beds  = parse_beds(detail_text)
    baths = parse_baths(detail_text)
    size  = parse_size(detail_text)

    # Image
    img = article.find("img", class_=lambda c: c and "thumb" in c.split() if c else False)
    image_url = best_image_url(img)

    # Source URL
    link_el = article.find("a", class_=lambda c: c and "card-body" in c.split() if c else False)
    source_path = link_el["href"] if link_el and link_el.get("href") else ""
    source_url  = BASE_URL + source_path if source_path.startswith("/") else source_path

    return {
        "mls": mls_id,
        "name": name or article.get("data-ad-title", "Unknown"),
        "type": listing_type,
        "image": image_url,
        "location": location,
        "area": parse_area(location),
        "askPrice": price,
        "size": size or "",
        "bedrooms": beds,
        "bathrooms": baths,
        "status": parse_status(article),
        "sourceUrl": source_url,
    }


# ── detail page scraper ───────────────────────────────────────────────────────

def scrape_detail(page, url):
    """Visit a listing detail page and return (description, building_size, lot_size)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        soup = BeautifulSoup(page.content(), "html.parser")
        remarks = soup.find(class_=lambda c: c and "remarks" in c.lower() if c else False)
        desc = clean(remarks.get_text()) if remarks else ""
        building_size, lot_size = parse_two_sizes(soup.get_text(" ", strip=True))
        return desc, building_size, lot_size
    except Exception as e:
        print(f"    ⚠  Detail page failed ({url}): {e}")
        return "", "", ""


# ── main scraper ──────────────────────────────────────────────────────────────

def scrape_section(browser, section_path, listing_type, seen_ids):
    """Scrape one section in its own browser context to avoid WAF throttling."""
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  Scraping {section_path}")

        page.goto(BASE_URL + section_path, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("article.card-listing", timeout=15000)
        except Exception:
            pass
        time.sleep(1)

        first_soup = BeautifulSoup(page.content(), "html.parser")
        page_urls  = get_pagination_urls(first_soup, section_path)
        print(f"   Pages found: {len(page_urls)}")

        for page_url in page_urls:
            print(f"   Loading {page_url} …", end=" ", flush=True)
            if page_url != BASE_URL + section_path:
                page.goto(page_url, timeout=30000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector("article.card-listing", timeout=10000)
                except Exception:
                    pass
                time.sleep(0.8)
                soup = BeautifulSoup(page.content(), "html.parser")
            else:
                soup = first_soup

            cards = soup.find_all("article", class_="card-listing")
            print(f"{len(cards)} cards")

            for card in cards:
                data = parse_card(card, listing_type)
                mls  = data.pop("mls")
                if mls in seen_ids:
                    continue
                seen_ids.add(mls)

                print(f"     {mls}  {data['name'][:45]}")

                detail_building = detail_lot = ""
                if data["sourceUrl"]:
                    data["notes"], detail_building, detail_lot = scrape_detail(page, data["sourceUrl"])
                    time.sleep(0.5)

                # Card parse_size → buildingSize for residential; supplement with detail page
                card_size = data["size"] or ""
                building_size = detail_building or card_size
                lot_size = detail_lot

                results.append({
                    "id":           int(mls) if mls.isdigit() else mls,
                    "name":         data["name"],
                    "type":         data["type"],
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     data["askPrice"],
                    "size":         building_size or lot_size or card_size,
                    "buildingSize": building_size,
                    "lotSize":      lot_size,
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       "Century 21 Aruba",
                    "listedDate":   TODAY,
                    "sourceUrl":    data["sourceUrl"],
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        data.get("notes", ""),
                })
    finally:
        ctx.close()

    return results


def scrape_all():
    listings = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for section_path, listing_type in SEARCH_SECTIONS:
            listings.extend(scrape_section(browser, section_path, listing_type, seen_ids))
            time.sleep(2)  # brief pause between sections
        browser.close()

    return listings


# ── save to data.json ─────────────────────────────────────────────────────────

def save(new_listings):
    new_listings, _ = dedup_within_site(new_listings, "Century 21 Aruba")
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current  = existing.get("listings", [])
    kept     = [l for l in current if l.get("agency") != "Century 21 Aruba"]
    merged   = kept + new_listings
    existing["listings"] = merged
    existing["agentMeta"]         = {
        "lastSync":       datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} C21 listings → {DATA_JSON} ({len(merged)} total)")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Century 21 Aruba scraper starting …")
    listings = scrape_all()
    save(listings)
    print(f"\nDone — {len(listings)} listings scraped.")
