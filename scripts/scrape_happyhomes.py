#!/usr/bin/env python3
"""
Aruba Happy Homes property listing scraper.
Source: https://arubahappyhomes.com

Scrapes all for-sale listings across residential, condo, land, and commercial.
Card contains name, location, price, size, beds. Detail page adds image + baths.

Usage:
    python3 scrape_happyhomes.py

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

BASE_URL   = "https://arubahappyhomes.com"
AGENCY     = "Aruba Happy Homes"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/listings/for-sale/residential",   "house"),
    ("/listings/for-sale/condominium",   "condo"),
    ("/listings/for-sale/land",          "land"),
    ("/listings/for-sale/commercial",    "commercial"),
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    m = re.search(r"USD\s*([\d.,]+)", text or "")
    if m:
        raw = m.group(1).replace(".", "").replace(",", "")
        return int(raw) if raw.isdigit() else None
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(card):
    name_el  = card.find(class_="name")
    link_el  = card.find("a", class_="link-cover")
    area_el  = card.find(class_="area")
    price_el = card.find(class_="price")

    opts = card.find_all(class_="option__value")
    size = clean(opts[0].get_text()) if len(opts) > 0 else ""
    beds = parse_int(opts[1].get_text()) if len(opts) > 1 else None

    name = clean(name_el.get_text()) if name_el else "Unknown"
    href = link_el["href"] if link_el else ""

    return {
        "name":     name,
        "href":     href if href.startswith("http") else BASE_URL + href,
        "area":     clean(area_el.get_text()) if area_el else "",
        "askPrice": parse_price(price_el.get_text() if price_el else ""),
        "size":     size,
        "bedrooms": beds,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        # Image: first listing photo
        img = soup.find("img", class_=lambda c: c and "listing" in " ".join(c) if c else False)
        if not img:
            img = soup.select_one(".gallery img, .slider img, .photo img, article img")
        image_url = img["src"] if img else ""

        # Bathrooms
        baths = None
        text = soup.get_text(" ", strip=True)
        m = re.search(r"(\d+)\s*bathroom", text, re.I)
        if m:
            baths = int(m.group(1))

        # Description: longest paragraph
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return image_url, baths, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return "", None, ""


def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {section_path}")
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

            print(f"     → {data['name'][:50]}")
            image_url, baths, desc = scrape_detail(page, url)
            time.sleep(0.5)

            slug = url.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         data["name"],
                "type":         listing_type,
                "image":        image_url,
                "area":         data["area"],
                "location":     data["area"],
                "askPrice":     data["askPrice"],
                "size":         data["size"],
                "bedrooms":     data["bedrooms"],
                "bathrooms":    baths,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    url,
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
