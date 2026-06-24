#!/usr/bin/env python3
"""
Realty One Group (ROGA) Aruba property listing scraper.
Source: https://rogaruba.com

Scrapes for-sale listings. Card info section contains name, location, price,
size, and beds. Detail page adds image and bathrooms.

Usage:
    python3 scrape_roga_aruba.py

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
from deduplicate import dedup_within_site, parse_price_robust

BASE_URL   = "https://rogaruba.com"
AGENCY     = "Realty One Group Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
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


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)

def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(info_div):
    """info_div is the .items-start div containing text content."""
    link_el  = info_div.find("a")
    name     = clean(link_el.get_text()) if link_el else "Unknown"
    href     = link_el["href"] if link_el else ""

    # Location: first plain div (after the link)
    loc_el = info_div.find("div", class_=lambda c: c and "mb-2" in c if c else False)
    location = clean(loc_el.get_text()) if loc_el else ""

    # Price: bold coloured div
    price_el = info_div.find("div", class_="font-bold")
    price = parse_price(price_el.get_text() if price_el else "")

    # Size + beds from icon rows
    icon_rows = info_div.select("div.text-xs.items-center")
    size = ""
    beds = None
    if len(icon_rows) > 0:
        size = re.sub(r"\s+", " ", icon_rows[0].get_text()).strip()
    if len(icon_rows) > 1:
        beds = parse_int(icon_rows[1].get_text())

    return {
        "name":     name,
        "href":     href if href.startswith("http") else BASE_URL + href,
        "location": location,
        "area":     location.split(",")[-1].strip() if "," in location else location,
        "askPrice": price,
        "size":     size,
        "bedrooms": beds,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        # Image
        source = soup.find("source", srcset=True)
        img_el = soup.find("img", class_="object-cover")
        image  = (source["srcset"].split(",")[0].split()[0] if source else None) or (img_el["src"] if img_el else "")

        # Bathrooms
        baths = None
        text  = soup.get_text(" ", strip=True)
        m = re.search(r"(\d+)\s*bath", text, re.I)
        if m:
            baths = int(m.group(1))

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return image, baths, desc
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
        time.sleep(2.5)

        soup = BeautifulSoup(page.content(), "html.parser")
        info_divs = [
            el for el in soup.find_all("div")
            if el.get("class") and "items-start" in el.get("class")
            and el.find("a") and el.find("div", class_="font-bold")
        ]
        print(f"   {len(info_divs)} cards")

        for info_div in info_divs:
            data = parse_card(info_div)
            url  = data["href"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            print(f"     → {data['name'][:50]}")
            image, baths, desc = scrape_detail(page, url)
            time.sleep(0.4)

            slug = url.rstrip("/").split("/")[-1]
            results.append({
                "id":           slug,
                "name":         data["name"],
                "type":         listing_type,
                "image":        image,
                "area":         data["area"],
                "location":     data["location"],
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
