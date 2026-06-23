#!/usr/bin/env python3
"""
RE/MAX Aruba property listing scraper.
Source: https://remaxaruba.com

Scrapes residential, condo, land, and commercial for-sale listings.
Card contains image, name, location, price, size, beds, status tags.
Detail page adds bathrooms and description.

Usage:
    python3 scrape_remax_aruba.py

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
from deduplicate import dedup_within_site

BASE_URL   = "https://remaxaruba.com"
AGENCY     = "RE/MAX Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/property/residential-for-sale",  "house"),
    ("/property/condominium-for-sale",  "condo"),
    ("/property/land-for-sale",         "land"),
    ("/property/commercial-for-sale",   "commercial"),
]

REMAX_STATUS_MAP = {
    "price reduced": "price reduced",
    "under offer":   "under offer",
    "sold":          "sold",
    "on hold":       "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    m = re.search(r"USD\s*([\d,]+)", text or "")
    if m:
        return int(m.group(1).replace(",", ""))
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(card):
    # Image
    source = card.find("source")
    img_el = card.find("img")
    image  = (source["srcset"] if source else None) or (img_el["src"] if img_el else "")

    # Link + name
    link_el = card.find("a", class_=lambda c: c and "font-bold" in " ".join(c) if c else False)
    if not link_el:
        link_el = card.find("a")
    name = clean(link_el.get_text()) if link_el else "Unknown"
    href = link_el["href"] if link_el else ""

    # Location: div with "grow" and "mb-1"
    loc_el = card.find("div", class_=lambda c: c and "grow" in c and "mb-1" in c if c else False)
    location = clean(loc_el.get_text()) if loc_el else ""

    # Price: div with "mb-3" containing "USD"
    price_el = None
    for div in card.find_all("div", class_=lambda c: c and "mb-3" in c if c else False):
        if "USD" in div.get_text():
            price_el = div
            break
    price = parse_price(price_el.get_text() if price_el else "")

    # Size + beds from icon rows
    icon_rows = card.find_all("div", class_=lambda c: c and "text-xs" in " ".join(c) and "items-center" in " ".join(c) if c else False)
    size = ""
    beds = None
    if len(icon_rows) > 0:
        size_text = clean(icon_rows[0].get_text())
        size = re.sub(r"\s+", " ", size_text).strip()
    if len(icon_rows) > 1:
        beds = parse_int(icon_rows[1].get_text())

    # Status from tag classes
    status = "active"
    for tag in card.find_all("div", class_=lambda c: c and "tag-" in " ".join(c) if c else False):
        tag_classes = " ".join(tag.get("class", []))
        for key, val in REMAX_STATUS_MAP.items():
            if key.replace(" ", "-") in tag_classes:
                status = val
                break

    return {
        "name":     name,
        "href":     href if href.startswith("http") else BASE_URL + href,
        "image":    image,
        "location": location,
        "area":     location.split(",")[0].strip() if "," in location else location,
        "askPrice": price,
        "size":     size,
        "bedrooms": beds,
        "status":   status,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        baths = None
        m = re.search(r"(\d+)\s*bath", text, re.I)
        if m:
            baths = int(m.group(1))

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return baths, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, ""


def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {section_path}")
        page.goto(BASE_URL + section_path, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

        soup = BeautifulSoup(page.content(), "html.parser")
        cards = [el for el in soup.find_all("div")
                 if el.get("class") and "bg-white" in el.get("class") and "border-gray-300" in el.get("class")]
        print(f"   {len(cards)} cards")

        for card in cards:
            data = parse_card(card)
            url  = data["href"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            print(f"     → {data['name'][:50]}")
            baths, desc = scrape_detail(page, url)
            time.sleep(0.4)

            slug = url.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         data["name"],
                "type":         listing_type,
                "image":        data["image"],
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "size":         data["size"],
                "bedrooms":     data["bedrooms"],
                "bathrooms":    baths,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    url,
                "status":       data["status"],
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
