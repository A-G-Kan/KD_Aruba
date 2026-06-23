#!/usr/bin/env python3
"""
Bon Choice Aruba Realty (BCA) property listing scraper.
Source: https://bcarubarealty.com

Uses WP Real Estate 7 plugin. 15 listings on the sales page.
Cards contain image, name, location, price, beds, baths, size, status.

Usage:
    python3 scrape_bca_aruba.py

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

BASE_URL   = "https://bcarubarealty.com"
AGENCY     = "Bon Choice Aruba Realty"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

BCA_STATUS_MAP = {
    "sales":       "active",
    "for sale":    "active",
    "sold":        "sold",
    "new offer":   "active",
    "under offer": "under offer",
    "price reduced":"price reduced",
    "on hold":     "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    text = text or ""
    m = re.search(r"Afl\.?\s*([\d.,]+)", text)
    if m:
        raw = m.group(1).replace(".", "").replace(",", "")
        return int(raw) if raw.isdigit() else None
    m = re.search(r"\$\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits and len(digits) > 3 else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(card):
    # Link
    link_el = card.find("a", href=lambda h: h and "/properties/" in h)
    href    = link_el["href"] if link_el else ""
    if href and not href.startswith("http"):
        href = BASE_URL + href

    # Image
    img_el = card.find("img")
    image  = (img_el.get("src") or img_el.get("data-original") or "") if img_el else ""
    if image and not image.startswith("http"):
        image = BASE_URL + "/" + image.lstrip("/")

    # Name (title)
    h3 = card.find("h3") or card.find("h2")
    name_link = h3.find("a") if h3 else None
    name = clean(name_link.get_text() if name_link else (h3.get_text() if h3 else "Unknown"))

    # Location
    loc_el = card.find(class_=re.compile(r"property_location|listing_location|item_location", re.I))
    location = clean(loc_el.get_text()) if loc_el else ""
    if not location:
        loc_link = card.find("a", href=lambda h: h and "/area/" in h if h else False)
        location = clean(loc_link.get_text()) if loc_link else ""

    # Price
    price_el = card.find(class_=re.compile(r"listing_unit_price|listing-unit-price|item_price", re.I))
    price = parse_price(price_el.get_text() if price_el else "")
    if not price:
        price = parse_price(card.get_text())

    # Beds / baths / size
    bed_el  = card.find(class_=re.compile(r"listing_unit_bed|h-beds|beds-num", re.I))
    bath_el = card.find(class_=re.compile(r"listing_unit_bath|h-baths|baths-num", re.I))
    size_el = card.find(class_=re.compile(r"listing_unit_size|item_area|h-area", re.I))

    beds  = parse_int(bed_el.get_text()  if bed_el  else "")
    baths = parse_int(bath_el.get_text() if bath_el else "")
    size  = clean(size_el.get_text())    if size_el else ""

    # Status
    status = "active"
    status_el = card.find(class_=re.compile(r"action_tag|status-wrapper|ribbon", re.I))
    if status_el:
        st = clean(status_el.get_text()).lower()
        status = BCA_STATUS_MAP.get(st, "active")

    return {
        "name":      name,
        "href":      href,
        "image":     image,
        "location":  location,
        "area":      location,
        "askPrice":  price,
        "size":      size,
        "bedrooms":  beds,
        "bathrooms": baths,
        "status":    status,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        return max(paras, key=len, default="")
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return ""


def scrape_all():
    results = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()

        url = f"{BASE_URL}/action/sales/"
        try:
            print(f"\n▶  {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all(class_="property_card_default")
            print(f"   {len(cards)} cards")

            for card in cards:
                data = parse_card(card)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                print(f"     → {data['name'][:50]}")
                desc = scrape_detail(page, href)
                time.sleep(0.4)

                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":           slug,
                    "name":         data["name"],
                    "type":         "house",
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     data["askPrice"],
                    "size":         data["size"],
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        desc,
                })
        finally:
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
