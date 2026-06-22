#!/usr/bin/env python3
"""
Keller Williams Aruba property listing scraper.
Source: https://kw-aruba.com

Scrapes all for-sale listings across residential, condo/townhouse,
land, and commercial categories. Visits each detail page to pull
bathrooms and the full property description.

Usage:
    python3 scrape_kw_aruba.py

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

BASE_URL  = "https://kw-aruba.com"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/listings/for-sale/residential",           "house"),
    ("/listings/for-sale/condominium-townhouse",  "condo"),
    ("/listings/for-sale/land",                   "land"),
    ("/listings/for-sale/commercial",             "commercial"),
]


# ── helpers ──────────────────────────────────────────────────────────────────

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    """'USD 3.900.000 (AWG 6.942.000)' → 3900000"""
    # KW uses European dot-separator: 3.900.000 → strip dots
    m = re.search(r"USD\s*([\d.,]+)", text or "")
    if m:
        raw = m.group(1).replace(".", "").replace(",", "")
        return int(raw) if raw.isdigit() else None
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse_area(location_text):
    """'Malmok' → 'Malmok'  |  'Palm Beach, Noord' → 'Palm Beach'"""
    return clean(location_text.split(",")[0]) if location_text else ""


# ── card parser ───────────────────────────────────────────────────────────────

def parse_card(card, listing_type):
    url_el   = card.find("a", class_="card__overlay")
    href     = url_el["href"] if url_el else ""
    name_el  = card.find(class_="card__heading")
    loc_el   = card.find(class_="card__location")
    price_el = card.find(class_="card__price")
    img_el   = card.find("img", class_="card__image-img")

    # Options: first = size (ruler icon), second = bedrooms (door icon)
    opts = card.find_all(class_="option")
    size_text = clean(opts[0].find(class_="option__value").get_text()) if len(opts) > 0 else ""
    beds_text = clean(opts[1].find(class_="option__value").get_text()) if len(opts) > 1 else ""
    beds = None
    m = re.match(r"(\d+)", beds_text)
    if m:
        beds = int(m.group(1))

    location = clean(loc_el.get_text()) if loc_el else ""

    return {
        "name":       clean(name_el.get_text()) if name_el else "Unknown",
        "type":       listing_type,
        "image":      img_el["src"] if img_el else "",
        "location":   location,
        "area":       parse_area(location),
        "askPrice":   parse_price(price_el.get_text() if price_el else ""),
        "size":       size_text,
        "bedrooms":   beds,
        "sourceUrl":  BASE_URL + href if href.startswith("/") else href,
    }


# ── detail page ───────────────────────────────────────────────────────────────

def scrape_detail(page, url):
    """Return (bathrooms, description) from a KW listing detail page."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        # Bathrooms: "10 bathroom(s)"
        baths = None
        m = re.search(r"(\d+)\s*bathroom\(s\)", text, re.I)
        if m:
            baths = int(m.group(1))

        # Description: paragraphs that follow the "Description" tab heading
        description = ""
        idx = text.find("Description")
        if idx >= 0:
            after = text[idx + len("Description"):]
            # Skip over "Features" / "Map" tab headers
            stop = re.search(r"\b(Features|Map|Contact|Agent)\b", after)
            snippet = after[:stop.start()].strip() if stop else after[:2000].strip()
            description = re.sub(r"\s+", " ", snippet).strip()

        if not description:
            # Fallback: find the longest <p> on the page
            paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 80]
            description = max(paras, key=len, default="")

        return baths, description

    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, ""


# ── scraper ───────────────────────────────────────────────────────────────────

def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {section_path}")
        page.goto(BASE_URL + section_path, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("div.card", timeout=10000)
        except Exception:
            pass
        time.sleep(1.5)

        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all(class_="card")
        print(f"   {len(cards)} cards")

        for card in cards:
            data = parse_card(card, listing_type)
            url  = data["sourceUrl"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            print(f"     → {data['name'][:50]}")
            baths, desc = scrape_detail(page, url)
            data["bathrooms"] = baths
            data["notes"]     = desc
            time.sleep(0.4)

            results.append({
                "id":           url.rstrip("/").split("/")[-1],
                "name":         data["name"],
                "type":         data["type"],
                "image":        data["image"],
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "size":         data["size"],
                "bedrooms":     data["bedrooms"],
                "bathrooms":    data["bathrooms"],
                "agency":       "Keller Williams Aruba",
                "listedDate":   TODAY,
                "sourceUrl":    url,
                "status":       "active",
                "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                "notes":        data["notes"],
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
    # Remove old KW listings, keep others
    kept = [l for l in current if l.get("agency") != "Keller Williams Aruba"]
    merged = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       TODAY,
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} KW listings → {DATA_JSON} ({len(merged)} total)")


if __name__ == "__main__":
    print("Keller Williams Aruba scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
