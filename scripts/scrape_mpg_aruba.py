#!/usr/bin/env python3
"""
MPG Aruba property listing scraper.
Source: https://www.mpgaruba.com

Scrapes all for-sale listings across houses, condos, land, and commercial.
Handles JS-based pagination (changePage(n)) by calling it directly via
Playwright's page.evaluate(). Visits each detail page for full description.

Usage:
    python3 scrape_mpg_aruba.py

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
from deduplicate import dedup_within_site, parse_price_robust

BASE_URL   = "https://www.mpgaruba.com"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/houses-for-sale-aruba",          "house"),
    ("/condos-for-sale-in-aruba",       "condo"),
    ("/land-for-sale-in-aruba",         "land"),
    ("/commercial-property-for-sale-aruba", "commercial"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)

def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def get_page_count(soup):
    """Count pagination pages from the ul.pagination element."""
    pager = soup.find("ul", class_="pagination")
    if not pager:
        return 1
    page_items = [li for li in pager.find_all("li") if li.find("a") and re.match(r"^\d+$", li.find("a").get_text().strip())]
    return len(page_items) if page_items else 1


# ── card parser ───────────────────────────────────────────────────────────────

def parse_cards(soup, listing_type):
    """Parse all .properties-items cards on a page."""
    items = soup.find_all(class_="properties-items")
    results = []
    for item in items:
        link_el = item.find("a", class_="properties-link")
        href    = link_el["href"] if link_el else ""

        # First image in the slider
        img_el  = item.find("img", class_="core-image")
        img_url = img_el["src"] if img_el else ""

        # Text block
        text_el  = item.find(class_="properties-text")
        if not text_el:
            continue

        name_el  = text_el.find("h3")
        loc_el   = text_el.find(class_="prt-location")
        price_el = text_el.find(class_="prt-price")

        name     = clean(name_el.get_text())     if name_el  else "Unknown"
        location = clean(loc_el.get_text())      if loc_el   else ""
        price    = parse_price(price_el.get_text() if price_el else "")

        # Attributes: Beds, Baths, Lot size
        attrs    = text_el.find_all(class_="attr-item")
        beds, baths, size = None, None, ""
        for attr in attrs:
            t = clean(attr.get_text())
            b_val = attr.find("b")
            val   = clean(b_val.get_text()) if b_val else ""
            if "Beds" in t:
                beds  = parse_int(val)
            elif "Bath" in t:
                baths = parse_int(val)
            elif "size" in t.lower():
                # "1,218 m2 | 13,110 ft2" → "1,218 m²"
                m2 = re.search(r"([\d,]+)\s*m[²2]", val)
                size = m2.group(0).replace("m2", "m²") if m2 else val

        # Area: first part of location before comma
        area = location.split(",")[0].strip() if location else ""

        results.append({
            "name":      name,
            "type":      listing_type,
            "image":     img_url,
            "location":  location,
            "area":      area,
            "askPrice":  price,
            "size":      size,
            "bedrooms":  beds,
            "bathrooms": baths,
            "sourceUrl": href,
        })
    return results


# ── detail page ───────────────────────────────────────────────────────────────

def scrape_detail(page, url):
    """Return full description from an MPG listing detail page."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        # MPG description is usually in a div with class containing "description" or "about"
        for cls in ["property-description", "listing-description", "about-property", "description"]:
            el = soup.find(class_=lambda c: c and cls in c.lower() if c else False)
            if el and len(el.get_text(strip=True)) > 80:
                return clean(el.get_text())

        # Fallback: longest substantial <p> on page
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 80]
        return max(paras, key=len, default="")

    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return ""


# ── pagination handler ────────────────────────────────────────────────────────

def get_all_cards_for_section(page, url, listing_type):
    """Load all paginated results for a section using JS changePage()."""
    page.goto(url, timeout=30000, wait_until="networkidle")
    time.sleep(2)

    soup       = BeautifulSoup(page.content(), "html.parser")
    num_pages  = get_page_count(soup)
    print(f"   Pages: {num_pages}")

    all_cards = parse_cards(soup, listing_type)

    for pg in range(2, num_pages + 1):
        print(f"   Loading page {pg} …", end=" ", flush=True)
        try:
            page.evaluate(f"changePage({pg})")
            time.sleep(2)
            soup_n = BeautifulSoup(page.content(), "html.parser")
            cards_n = parse_cards(soup_n, listing_type)
            print(f"{len(cards_n)} cards")
            all_cards.extend(cards_n)
        except Exception as e:
            print(f"⚠  {e}")

    return all_cards


# ── scraper ───────────────────────────────────────────────────────────────────

def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        url = BASE_URL + section_path
        print(f"\n▶  {section_path}")

        cards = get_all_cards_for_section(page, url, listing_type)
        print(f"   Total cards scraped: {len(cards)}")

        for data in cards:
            listing_url = data["sourceUrl"]
            if not listing_url or listing_url in seen_urls:
                continue
            seen_urls.add(listing_url)

            print(f"     → {data['name'][:50]}")
            desc = scrape_detail(page, listing_url)
            time.sleep(0.4)

            slug = listing_url.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         data["name"],
                "type":         data["type"],
                "image":        data["image"],
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "size":         data["size"],
                "bedrooms":     data["bedrooms"],
                "bathrooms":    data["bathrooms"],
                "agency":       "MPG Aruba",
                "listedDate":   TODAY,
                "sourceUrl":    listing_url,
                "status":       "active",
                "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
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


# ── save ──────────────────────────────────────────────────────────────────────

def save(new_listings):
    new_listings, _ = dedup_within_site(new_listings, "MPG Aruba")
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    kept    = [l for l in current if l.get("agency") != "MPG Aruba"]
    merged  = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} MPG listings → {DATA_JSON} ({len(merged)} total)")


if __name__ == "__main__":
    print("MPG Aruba scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
