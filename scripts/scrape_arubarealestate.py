#!/usr/bin/env python3
"""
ArubaRealEstate.com property listing scraper.
Source: https://www.arubarealestate.com

Scrapes all for-sale listings across houses, condos, land, and commercial.
Cards already contain beds, baths, size, location, and an excerpt.
Visits each detail page to pull the full property description.

Usage:
    python3 scrape_arubarealestate.py

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

BASE_URL   = "https://www.arubarealestate.com"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/aruba-houses-for-sale/",       "house"),
    ("/aruba-condominiums-for-sale/", "condo"),
    ("/aruba-land-for-sale/",         "land"),
    ("/aruba-commercial-for-sale/",   "commercial"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    """'$1,938,202' → 1938202"""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_area(location_text):
    """'Noord' → 'Noord'  (already clean on this site)"""
    return clean(location_text)


# ── card parser ───────────────────────────────────────────────────────────────

def parse_card(result_div, listing_type):
    # Image
    img_wrap = result_div.find(class_="featured")
    img_el   = img_wrap.find("img") if img_wrap else None
    img_url  = img_el["src"] if img_el else ""

    # Title + link
    title_el = result_div.find(class_="title")
    link_el  = title_el.find("a") if title_el else None
    name     = clean(link_el.get_text()) if link_el else ""
    href     = link_el["href"] if link_el else ""

    # Price
    price_el = result_div.find(class_="price")
    price    = parse_price(price_el.get_text() if price_el else "")

    # Location
    loc_el   = result_div.find(class_="location")
    location = clean(loc_el.get_text()) if loc_el else ""

    # Excerpt (short description already on card)
    exc_el  = result_div.find(class_="excerpt")
    excerpt = clean(exc_el.get_text()) if exc_el else ""

    # Beds / Baths / Area
    beds_el  = result_div.find(class_="beds")
    baths_el = result_div.find(class_="baths")
    area_el  = result_div.find(class_="area")

    beds  = parse_int(beds_el.get_text()  if beds_el  else "")
    baths = parse_int(baths_el.get_text() if baths_el else "")
    size  = clean(area_el.get_text())     if area_el  else ""

    return {
        "name":      name or "Unknown",
        "type":      listing_type,
        "image":     img_url,
        "location":  location,
        "area":      parse_area(location),
        "askPrice":  price,
        "size":      size,
        "bedrooms":  beds,
        "bathrooms": baths,
        "excerpt":   excerpt,
        "sourceUrl": href,
    }


# ── detail page ───────────────────────────────────────────────────────────────

def scrape_detail(page, url):
    """Return full description from an arubarealestate.com listing detail page."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        # Description follows "Description:" heading
        idx = text.find("Description:")
        if idx >= 0:
            snippet = text[idx + len("Description:"):idx + 2500].strip()
            # Stop at next section header pattern
            stop = re.search(r"\n\s*\n|\b(Features|Amenities|Map|Location|Contact|Agent|Gallery)\b", snippet)
            description = snippet[:stop.start()].strip() if stop else snippet
            return re.sub(r"\s+", " ", description).strip()

        # Fallback: longest <p>
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 80]
        return max(paras, key=len, default="")

    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return ""


# ── scraper ───────────────────────────────────────────────────────────────────

def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        url = BASE_URL + section_path
        print(f"\n▶  {section_path}")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(".fwpl-result", timeout=12000)
        except Exception:
            pass
        time.sleep(1.5)

        soup    = BeautifulSoup(page.content(), "html.parser")
        results_els = soup.find_all(class_="fwpl-result")
        print(f"   {len(results_els)} cards")

        for res in results_els:
            data = parse_card(res, listing_type)
            listing_url = data["sourceUrl"]
            if not listing_url or listing_url in seen_urls:
                continue
            seen_urls.add(listing_url)

            print(f"     → {data['name'][:50]}")

            # Use excerpt as base description, enrich with full detail
            desc = data["excerpt"]
            if listing_url:
                full_desc = scrape_detail(page, listing_url)
                if full_desc:
                    desc = full_desc
                time.sleep(0.4)

            results.append({
                "id":           listing_url.rstrip("/").split("/")[-1],
                "name":         data["name"],
                "type":         data["type"],
                "image":        data["image"],
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "size":         data["size"],
                "bedrooms":     data["bedrooms"],
                "bathrooms":    data["bathrooms"],
                "agency":       "Aruba Real Estate",
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
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    kept    = [l for l in current if l.get("agency") != "Aruba Real Estate"]
    merged  = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       TODAY,
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} ArubaRealEstate listings → {DATA_JSON} ({len(merged)} total)")


if __name__ == "__main__":
    print("ArubaRealEstate.com scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
