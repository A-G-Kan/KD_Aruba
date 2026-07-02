#!/usr/bin/env python3
"""
HKG Real Estate Aruba — long-term rental scraper.
Source: https://hkgrealestatearuba.com/property-type/rental/ (Houzez WordPress theme)

The list page's cards give reliable price/status/beds/baths, but their size
field is raw and unit-ambiguous ("1689 sq ft" vs "90 m2"), and the address
isn't present on cards at all. Whole-page text scraping of the detail page
(the approach the sale scraper uses) is unsafe here: HKG's detail pages embed
"similar listings" widgets whose own sizes get picked up as false matches.

Instead each detail page carries a `RealEstateListing` JSON-LD block scoped
to that one listing — floorSize (value + unit), address, and an ordered
photo array. That's used for size/area/photo instead of free-text scraping.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_hkg_rentals.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time, math
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   # find deduplicate.py in scripts/
sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import parse_price_robust

AGENCY    = "HKG Real Estate Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://hkgrealestatearuba.com"
LTR_URL   = f"{BASE_URL}/property-type/rental/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Anything not listed here (For Rent, or no label at all) means the unit is
# still on the market -> "active".
STATUS_MAP = {
    "rented":         "rented",
    "under offer":    "under offer",
    "under contract": "under offer",
    "on hold":        "on hold",
    "price reduced":  "price reduced",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_count(text):
    """Like parse_int, but a decimal count (e.g. a '0.5' half-bath) is
    rounded UP rather than truncated -- truncating would misreport a real
    half-bath as having no bathroom at all."""
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return math.ceil(float(m.group())) if m else None


def parse_card(card):
    title_el = card.find(class_="item-title") or card.find("h2") or card.find("h3")
    link_el  = title_el.find("a") if title_el else card.find("a", href=True)
    name     = clean(link_el.get_text()) if link_el else ""
    href     = (link_el["href"] if link_el else "").strip()

    # Image: data-images JSON attribute, fall back to a plain <img>
    image = ""
    try:
        images = json.loads(card.get("data-images", "[]"))
        image = images[0]["image"] if images else ""
    except Exception:
        pass
    if not image:
        img = card.find("img")
        image = (img.get("src") or img.get("data-src") or "") if img else ""

    price_el   = card.find(class_="item-price")
    price_span = price_el.find(class_="price") if price_el else None
    price      = parse_price_robust((price_span or price_el).get_text() if (price_span or price_el) else "")

    beds_el  = card.find(class_="h-beds")
    baths_el = card.find(class_="h-baths")
    beds  = parse_int(beds_el.get_text()  if beds_el  else "")
    baths = parse_count(baths_el.get_text() if baths_el else "")

    status = "active"
    first_label = card.find(class_="label-status")
    if first_label:
        status = STATUS_MAP.get(clean(first_label.get_text()).lower(), "active")

    return {
        "href":   href,
        "name":   name,
        "image":  image,
        "price":  price,
        "beds":   beds,
        "baths":  baths,
        "status": status,
    }


def parse_area(street_address):
    """'Diamante 300, Noord, Aruba' -> area='Noord', location=original string.

    A handful of HKG listings carry a mis-geocoded JSON-LD address (e.g.
    "Washington, DC, USA" or a Panama address) for what is definitely an
    Aruba property -- the source's own autocomplete/geocoder error, not
    ours. Every real HKG rental is in Aruba, so any address that doesn't
    say so is untrustworthy; showing the wrong country is worse than
    showing nothing, so it's dropped rather than propagated.
    """
    if not street_address:
        return "", ""
    if "aruba" not in street_address.lower():
        return "", ""
    location = clean(street_address)
    parts = [p.strip() for p in location.split(",") if p.strip()]
    parts = [p for p in parts if p.lower() != "aruba"]
    parts = [re.sub(r"\s+Aruba$", "", p, flags=re.I).strip() for p in parts]
    parts = [p for p in parts if p]
    area = parts[-1] if parts else ""
    return area, location


def convert_floor_size(value, unit_text):
    """floorSize {value, unitText} -> normalised 'NNN m²' string, or '' if absent."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    unit = (unit_text or "").upper()
    if "SQFT" in unit or "SQ FT" in unit or "FT" in unit:
        v *= 0.0929
    return f"{round(v)} m²"


def scrape_detail(page, url):
    """Return (area, location, building_size, image) from the listing's own
    RealEstateListing JSON-LD block, or blanks/None when a field is absent."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if not (isinstance(data, dict) and data.get("@type") == "RealEstateListing"):
                continue

            addr = (data.get("address") or {}).get("streetAddress", "")
            area, location = parse_area(addr)

            floor = data.get("floorSize") or {}
            building_size = convert_floor_size(floor.get("value"), floor.get("unitText"))

            images = data.get("image") or []
            image = images[0] if images else ""

            return area, location, building_size, image

        return "", "", "", ""
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return "", "", "", ""


def scrape_all():
    listings  = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=USER_AGENT)
        page    = ctx.new_page()

        pg_num = 1
        while True:
            url = LTR_URL if pg_num == 1 else f"{LTR_URL}page/{pg_num}/"
            print(f"\n▶  {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all(class_="item-listing-wrap")
            print(f"   {len(cards)} cards (page {pg_num})")

            if not cards:
                break

            for card in cards:
                data = parse_card(card)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                price_str = f"${data['price']:,}/mo" if data["price"] else "price on request"
                print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

                area, location, building_size, detail_image = scrape_detail(page, href)
                time.sleep(0.4)

                image = detail_image or data["image"]
                slug  = href.rstrip("/").split("/")[-1]

                listings.append({
                    "id":           f"hkg-ltr-{slug}",
                    "name":         data["name"],
                    "type":         "ltr",
                    "image":        image,
                    "area":         area,
                    "location":     location,
                    "askPrice":     data["price"],
                    "pricePeriod":  "monthly",
                    "size":         building_size,
                    "buildingSize": building_size,
                    "lotSize":      "",
                    "bedrooms":     data["beds"],
                    "bathrooms":    data["baths"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["price"]}],
                    "notes":        "",
                })

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
    print(f"\n✓  Saved {len(new_rentals)} HKG Real Estate Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
