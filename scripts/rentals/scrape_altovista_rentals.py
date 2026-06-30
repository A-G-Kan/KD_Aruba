#!/usr/bin/env python3
"""
Alto Vista Real Estate — long-term rental scraper.
Source: https://altovistarealestate.com/for-rent/
Plugin: WPL Pro (same as sale listings)

All listings show status "Rented" on the source — they are scraped as
status="rented" so they appear as historical LTR data, not available units.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_altovista_rentals.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import parse_price_robust

AGENCY    = "Alto Vista Real Estate"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://altovistarealestate.com"
LTR_URL   = f"{BASE_URL}/for-rent/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def area_from_alt(alt_text):
    """
    WPL img alt format:
      "Property Name, N Bedrooms..., Neighbourhood, ListingID"
    Neighbourhood is the second-to-last comma-separated segment.
    """
    parts = [p.strip() for p in (alt_text or "").split(",")]
    # Ignore segments that look like IDs (numeric) or status text
    skip = {"for rent", "for sale", "rented", "sold"}
    candidates = [p for p in parts[1:] if p and not p.isdigit() and p.lower() not in skip
                  and not re.match(r"^\d+\s*(bedroom|bathroom|sqft|m²)", p, re.I)
                  and "bedrooms" not in p.lower() and "bathrooms" not in p.lower()]
    # Last candidate is usually the neighbourhood
    return candidates[-1] if candidates else ""


def parse_card(card):
    # Link
    link_el = card.find("a", class_="view_detail", href=lambda h: h and "/properties/" in h)
    if not link_el:
        link_el = card.find("a", href=lambda h: h and "/properties/" in h)
    href = (link_el["href"] if link_el else "").strip()

    # Image and area (from alt text)
    img_el = card.find("img", class_="wpl_gallery_image")
    image  = img_el["src"] if img_el else ""
    alt    = img_el.get("alt", "") if img_el else ""
    area   = area_from_alt(alt)

    # Name: use wpl_prp_listing_location (property address) as the listing name
    loc_el = card.find("h4", class_="wpl_prp_listing_location")
    name   = clean(loc_el.get_text()) if loc_el else href.rstrip("/").split("/")[-1]

    # Beds / baths from icon box spans
    icon_box = card.find(class_="wpl_prp_listing_icon_box")
    beds  = None
    baths = None
    size  = ""
    if icon_box:
        bed_div  = icon_box.find(class_="bedroom")
        bath_div = icon_box.find(class_="bathroom")
        size_div = icon_box.find(class_="built_up_area")
        beds  = parse_int(bed_div.find(class_="value").get_text() if bed_div and bed_div.find(class_="value") else "")
        baths = parse_int(bath_div.find(class_="value").get_text() if bath_div and bath_div.find(class_="value") else "")
        if size_div:
            raw = clean(size_div.get_text())
            # Only keep if non-zero
            num = re.search(r"(\d+)", raw)
            if num and int(num.group(1)) > 0:
                size = raw

    # Price
    price_el = card.find(class_="price_box")
    price    = parse_price_robust(price_el.get_text() if price_el else "")

    # Short description from card body
    desc_el  = card.find(class_="wpl_prp_desc")
    desc     = clean(desc_el.get_text()) if desc_el else ""

    return {
        "href":  href,
        "name":  name,
        "area":  area,
        "image": image,
        "beds":  beds,
        "baths": baths,
        "size":  size,
        "price": price,
        "desc":  desc,
    }


def scrape_all():
    listings = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()

        pg_num = 1
        while True:
            url = LTR_URL if pg_num == 1 else f"{LTR_URL}page/{pg_num}/"
            print(f"\n▶  {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all(class_="wpl_prp_cont")
            print(f"   {len(cards)} cards (page {pg_num})")

            if not cards:
                break

            new_on_page = 0
            for card in cards:
                data = parse_card(card)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)
                new_on_page += 1

                slug = href.rstrip("/").split("/")[-1]
                print(f"     → {data['name'][:55]}  |  {data['area']}  |  ${data['price']:,}/mo" if data['price'] else f"     → {data['name'][:55]}")

                listings.append({
                    "id":           f"av-ltr-{slug}",
                    "name":         data["name"],
                    "type":         "ltr",
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["area"],
                    "askPrice":     data["price"],
                    "pricePeriod":  "monthly",
                    "size":         data["size"],
                    "buildingSize": data["size"],
                    "lotSize":      "",
                    "bedrooms":     data["beds"],
                    "bathrooms":    data["baths"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       "rented",
                    "priceHistory": [{"date": TODAY, "price": data["price"]}],
                    "notes":        data["desc"],
                })

            # If no new URLs found on this page, WPL is cycling — stop
            if new_on_page == 0:
                print("   No new listings on this page — pagination exhausted")
                break
            pg_num += 1

        ctx.close()
        browser.close()

    return listings


def save(new_rentals):
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current_rentals = existing.get("rentals", [])
    old_agency      = [r for r in current_rentals if r.get("agency") == AGENCY]
    kept            = [r for r in current_rentals if r.get("agency") != AGENCY]

    # Preserve user fields from previous run
    old_by_id = {r["id"]: r for r in old_agency}
    for r in new_rentals:
        old = old_by_id.get(r["id"])
        if old and old.get("archived"):
            r["archived"] = True

    merged = kept + new_rentals

    existing["rentals"] = merged
    existing["agentMeta"] = {
        "lastSync":       datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    total = len(existing.get("rentals", []))
    print(f"\n✓  Saved {len(new_rentals)} Alto Vista LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
