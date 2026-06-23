#!/usr/bin/env python3
"""
Coldwell Banker Aruba Realty property listing scraper.
Source: https://www.coldwellbanker.aw

Custom PHP CMS with no anti-bot protection.
Card has title, location, and a hidden raw-price div with numeric value.
Detail page adds image, beds, bathrooms, size, and description.

Usage:
    python3 scrape_coldwell_aruba.py

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

BASE_URL   = "https://www.coldwellbanker.aw"
AGENCY     = "Coldwell Banker Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_URL = (
    "/index.php?action=searchresults"
    "&pclass[]=1&pclass[]=2&pclass[]=6&pclass[]=4"
    "&start={start}"
)
PAGE_SIZE = 10


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(row):
    # Title
    h3 = row.find("h3")
    name = clean(h3.get_text()) if h3 else "Unknown"

    # Link
    img_area = row.find(class_="result_image")
    link_el  = img_area.find("a") if img_area else None
    href     = link_el["href"] if link_el else ""
    if href and not href.startswith("http"):
        href = BASE_URL + href

    # Image
    img_el = img_area.find("img") if img_area else None
    image  = img_el["src"] if img_el else ""
    if image and not image.startswith("http"):
        image = BASE_URL + "/" + image.lstrip("/")

    # Location: first <b> inside the price div
    price_div = row.find(id=re.compile(r"^price"))
    loc_el    = price_div.find("b") if price_div else None
    location  = clean(loc_el.get_text()) if loc_el else ""

    # Price from hidden rawprice div
    raw_div = row.find(id=re.compile(r"^rawprice"))
    price   = None
    if raw_div:
        digits = re.sub(r"[^\d]", "", raw_div.get_text())
        price = int(digits) if digits else None

    return {
        "name":     name,
        "href":     href,
        "image":    image,
        "location": location,
        "area":     location,
        "askPrice": price,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        beds = baths = None
        m = re.search(r"bed(?:room)?s?\s*[:\-]?\s*(\d+)|(\d+)\s*bed", text, re.I)
        if m:
            beds = int(m.group(1) or m.group(2))
        m = re.search(r"bath(?:room)?s?\s*[:\-]?\s*(\d+)|(\d+)\s*bath", text, re.I)
        if m:
            baths = int(m.group(1) or m.group(2))

        size = ""
        m = re.search(r"([\d,.]+)\s*(m²|m2|sqm|sq\.?\s*ft)", text, re.I)
        if m:
            size = m.group(0).strip()

        # Status
        status = "active"
        if re.search(r"\bsold\b", text, re.I):
            status = "sold"
        elif re.search(r"under\s*contract|under\s*offer", text, re.I):
            status = "under offer"

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return beds, baths, size, status, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, "", "active", ""


def scrape_all():
    results = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()

        start = 0
        while True:
            url = BASE_URL + SEARCH_URL.format(start=start)
            print(f"\n▶  Listings page (start={start})")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(1.5)

            soup = BeautifulSoup(page.content(), "html.parser")
            rows = soup.find_all(class_="search_result_row")
            print(f"   {len(rows)} cards")
            if not rows:
                break

            for row in rows:
                data = parse_card(row)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                print(f"     → {data['name'][:50]}")
                beds, baths, size, status, desc = scrape_detail(page, href)
                time.sleep(0.4)

                slug = re.sub(r"[^\w-]", "-", data["name"].lower())[:50]
                results.append({
                    "id":           slug,
                    "name":         data["name"],
                    "type":         "house",
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     data["askPrice"],
                    "size":         size,
                    "bedrooms":     beds,
                    "bathrooms":    baths,
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       status,
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        desc,
                })

            if len(rows) < PAGE_SIZE:
                break
            start += PAGE_SIZE
            time.sleep(1)

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
