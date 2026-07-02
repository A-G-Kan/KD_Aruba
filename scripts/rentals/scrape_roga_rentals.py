#!/usr/bin/env python3
"""
Realty One Group (ROGA) Aruba — long-term rental scraper.
Source: https://rogaruba.com/listings/for-rent

All LTR listings (residential, commercial -- condo/apartment/land are empty
at the time of writing) load on a single aggregated page.

Card icon rows are NOT positionally fixed: some cards show only a size row,
some only a beds row, some both -- e.g. "Koyari Home" shows a single row
that's beds, while "Caya J. E. M. Arends 33" shows a single row that's size.
The for-sale scraper (scrape_roga_aruba.py) treats icon_rows[0] as size and
icon_rows[1] as beds unconditionally; on a card with a beds-only row, that
would misreport a bedroom count as a size figure. This scraper identifies
each row by its actual SVG icon (icon-ruler-triangle = size, icon-door =
beds) instead of position.

The status badge ("New Listing" seen; "Rented" not currently live on the
site but the same badge mechanism would carry it) is an absolutely
positioned overlay on the card's image, outside the text info block the
for-sale scraper parses -- which is why that scraper never reads it and
just hardcodes "active". Rentals need the real thing, so this scraper
finds the badge in the shared card wrapper instead.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_roga_rentals.py

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
from deduplicate import parse_price_robust

AGENCY    = "Realty One Group Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://rogaruba.com"
LTR_URL   = f"{BASE_URL}/listings/for-rent"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Anything not listed here (New Listing, or no badge at all) means the unit
# is still on the market -> "active".
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


def parse_thousands(text):
    """Like parse_int, but keeps comma thousands separators intact
    (e.g. '4,521 Sq Ft' -> 4521) instead of stopping at the first comma
    and silently truncating to '4'."""
    m = re.search(r"[\d,]*\d", text or "")
    return int(m.group().replace(",", "")) if m else None


def parse_card(card):
    """card is the shared wrapper (image+badge sibling of the items-start text block)."""
    info_div = next(
        (el for el in card.find_all("div")
         if el.get("class") and "items-start" in el.get("class")
         and el.find("a") and el.find("div", class_="font-bold")),
        None,
    )
    if not info_div:
        return None

    link_el = info_div.find("a")
    name    = clean(link_el.get_text()) if link_el else "Unknown"
    href    = link_el["href"] if link_el else ""
    href    = href if href.startswith("http") else BASE_URL + href

    loc_el   = info_div.find("div", class_=lambda c: c and "mb-2" in c if c else False)
    location = clean(loc_el.get_text()) if loc_el else ""

    price_el = info_div.find("div", class_="font-bold")
    price    = parse_price_robust(price_el.get_text() if price_el else "")

    beds = None
    size_sqft = None
    for row in info_div.select("div.text-xs.items-center"):
        use_el = row.find("use")
        icon   = (use_el.get("href", "") if use_el else "").split("#")[-1]
        val    = clean(row.get_text())
        if icon == "icon-door":
            beds = parse_int(val)
        elif icon == "icon-ruler-triangle":
            size_sqft = parse_thousands(val)

    building_size = ""
    if size_sqft and size_sqft > 0:
        building_size = f"{round(size_sqft * 0.0929)} m²"

    badge_el = card.find("div", class_=lambda c: c and "absolute" in c and "left-1" in c and "top-1" in c if c else False)
    badge    = badge_el.get_text(strip=True).lower() if badge_el else ""
    status   = STATUS_MAP.get(badge, "active")

    return {
        "href":         href,
        "name":         name,
        "location":     location,
        "area":         location.split(",")[-1].strip() if "," in location else location,
        "askPrice":     price,
        "buildingSize": building_size,
        "bedrooms":     beds,
        "status":       status,
    }


def scrape_detail(page, url):
    """Return (image, bathrooms, description) from a listing detail page."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        source = soup.find("source", srcset=True)
        img_el = soup.find("img", class_="object-cover")
        image  = (source["srcset"].split(",")[0].split()[0] if source else None) or (img_el["src"] if img_el else "")

        text  = soup.get_text(" ", strip=True)
        baths = None
        m = re.search(r"(\d+)\s*bathroom\(s\)", text, re.I)
        if m:
            baths = int(m.group(1))

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc  = max(paras, key=len, default="")

        return image, baths, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return "", None, ""


def scrape_all():
    listings  = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=USER_AGENT)
        page    = ctx.new_page()

        print(f"\n▶  {LTR_URL}")
        page.goto(LTR_URL, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2.5)

        soup = BeautifulSoup(page.content(), "html.parser")
        info_divs = [
            el for el in soup.find_all("div")
            if el.get("class") and "items-start" in el.get("class")
            and el.find("a") and el.find("div", class_="font-bold")
        ]
        cards = [d.parent for d in info_divs]
        print(f"   {len(cards)} cards")

        for card in cards:
            data = parse_card(card)
            if not data or not data["href"] or data["href"] in seen_urls:
                continue
            seen_urls.add(data["href"])

            price_str = f"${data['askPrice']:,}/mo" if data["askPrice"] else "price on request"
            print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

            image, baths, desc = scrape_detail(page, data["href"])
            time.sleep(0.5)

            slug = data["href"].rstrip("/").split("/")[-1]
            listings.append({
                "id":           f"roga-ltr-{slug}",
                "name":         data["name"],
                "type":         "ltr",
                "image":        image,
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "pricePeriod":  "monthly",
                "size":         data["buildingSize"],
                "buildingSize": data["buildingSize"],
                "lotSize":      "",
                "bedrooms":     data["bedrooms"],
                "bathrooms":    baths,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    data["href"],
                "status":       data["status"],
                "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                "notes":        desc,
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
    print(f"\n✓  Saved {len(new_rentals)} Realty One Group Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
