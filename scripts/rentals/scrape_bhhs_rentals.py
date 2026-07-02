#!/usr/bin/env python3
"""
Berkshire Hathaway HomeServices (BHHS) Aruba — long-term rental scraper.
Source: https://www.bhhsaruba.com/for-rent

All LTR listings (residential, commercial, apartment, condominium) load on a
single aggregated page. Price, status, and (when the source shows it) beds/
baths/size are all present on the card itself — no detail-page visit needed.
BHHS has no vacation/short-term rental offering, so every listing here is LTR.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_bhhs_rentals.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   # find deduplicate.py in scripts/
sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import parse_price_robust, parse_two_sizes

AGENCY    = "BHHS Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://www.bhhsaruba.com"
LTR_URL   = f"{BASE_URL}/for-rent"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Anything not listed here (New listing, Must see!, Price upon request, or no
# tag at all) means the unit is still on the market -> "active".
STATUS_MAP = {
    "rented":  "rented",
    "on hold": "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_card(card):
    link_el = card.find("a", class_="preview-property__image")
    href    = (link_el["href"] if link_el else "").strip()

    img_el = card.find("img", class_="preview-property__image-img")
    image  = img_el["src"] if img_el else ""

    name = (link_el.get("title") or "").strip() if link_el else ""
    if not name:
        name = href.rstrip("/").split("/")[-1]

    tag_el     = card.find(class_="preview-property__tag")
    tag_text   = clean(tag_el.get_text()).lower() if tag_el else ""
    status     = STATUS_MAP.get(tag_text, "active")

    # "Property type: X", "Bedrooms: N", "Bathrooms: N", "Lot size: N M2",
    # "Built up size: N M2" — whichever the source chose to show for this unit.
    details_items = card.select(".preview-property__details-item")
    detail_text   = " ".join(clean(d.get_text()) for d in details_items)

    beds = baths = None
    m = re.search(r"Bedrooms:\s*(\d+)", detail_text)
    if m:
        beds = int(m.group(1))
    m = re.search(r"Bathrooms:\s*(\d+)", detail_text)
    if m:
        baths = int(m.group(1))

    building_size, lot_size = parse_two_sizes(detail_text)

    price_el = card.find(class_="preview-property__price")
    price    = parse_price_robust(price_el.get_text() if price_el else "")

    return {
        "href":          href,
        "name":          name,
        "image":         image,
        "status":        status,
        "beds":          beds,
        "baths":         baths,
        "building_size": building_size,
        "lot_size":      lot_size,
        "price":         price,
    }


def scrape_all():
    listings  = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=USER_AGENT)
        page    = ctx.new_page()

        print(f"\n▶  {LTR_URL}")
        page.goto(LTR_URL, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all(class_="preview-properties__item")
        print(f"   {len(cards)} LTR cards found")

        for card in cards:
            data = parse_card(card)
            href = data["href"]
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            price_str = f"${data['price']:,}/mo" if data["price"] else "price on request"
            print(f"     → {data['name'][:55]}  |  {price_str}  |  {data['status']}")

            slug = href.rstrip("/").split("/")[-1]
            listings.append({
                "id":           f"bhhs-ltr-{slug}",
                "name":         data["name"],
                "type":         "ltr",
                "image":        data["image"],
                "area":         "",   # BHHS shows no structured neighbourhood/area field for rentals
                "location":     "",
                "askPrice":     data["price"],
                "pricePeriod":  "monthly",
                "size":         data["building_size"] or data["lot_size"],
                "buildingSize": data["building_size"],
                "lotSize":      data["lot_size"],
                "bedrooms":     data["beds"],
                "bathrooms":    data["baths"],
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    href,
                "status":       data["status"],
                "priceHistory": [{"date": TODAY, "price": data["price"]}],
                "notes":        "",
            })

        ctx.close()
        browser.close()

    return listings


def save(new_rentals):
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current_rentals = existing.get("rentals", [])
    old_agency       = [r for r in current_rentals if r.get("agency") == AGENCY]
    kept             = [r for r in current_rentals if r.get("agency") != AGENCY]

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
    print(f"\n✓  Saved {len(new_rentals)} BHHS Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
