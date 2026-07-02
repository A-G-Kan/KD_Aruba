#!/usr/bin/env python3
"""
RE/MAX Aruba — long-term rental scraper (remaxaruba.com).
Source: https://remaxaruba.com/property/{residential,condominium,apartment,commercial}-rental

Card icon rows and status/type tag badges share the exact same CSS classes
("text-xs items-center"), so the for-sale scraper's positional read of
icon_rows[0]=size / icon_rows[1]=beds is unreliable here -- a tag badge like
"Rented" or "Luxury" often occupies position 0. Real data rows (size/beds/
baths) are identified by their SVG icon (icon-ruler-triangle / icon-bed /
icon-bath) instead; tag badges have no <use> icon at all and are skipped.

The card's single size figure doesn't reliably mean the same thing across
listings -- cross-checked against detail pages, it matched a residential
listing's LOT size on one and matched BOTH lot and build-up (identical
values) on an apartment. Rather than guess, this scraper reads each
detail page's separately labelled "Lot size" / "Build up size" text
instead of trusting the card figure for that distinction.

A property can carry multiple tags at once (e.g. "New Listing" + "Rented");
"Rented" is treated as authoritative over freshness tags like "New Listing".

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_remax_rentals.py

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

AGENCY    = "RE/MAX Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://remaxaruba.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_SECTIONS = [
    "property/residential-rental",
    "property/condominium-rental",
    "property/apartment-rental",
    "property/commercial-rental",
]

# Checked in this priority order -- "rented" wins over a freshness tag like
# "new listing" when a card carries both. Anything not listed here (New
# Listing, Commercial [a type label, not a status], or no tag at all) means
# the unit is still on the market -> "active".
STATUS_PRIORITY = [
    ("tag-rented",         "rented"),
    ("tag-under-contract", "under offer"),
    ("tag-on-hold",        "on hold"),
    ("tag-reduced",        "price reduced"),
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def valid_size(s):
    """Reject placeholder sizes like '-1 m²' / '1 m²' the site renders when
    no real figure was entered -- a wrong number is worse than none."""
    if not s:
        return ""
    m = re.search(r"[\d,.]+", s)
    if not m:
        return ""
    try:
        v = float(m.group().replace(",", ""))
        return s if v >= 10 else ""
    except ValueError:
        return ""


def parse_card(card):
    link_el = card.find("a", class_="font-bold") or card.find("a")
    name    = clean(link_el.get_text()) if link_el else "Unknown"
    href    = link_el["href"] if link_el else ""
    href    = href if href.startswith("http") else BASE_URL + href

    loc_el   = card.select_one("div.grow.mb-1")
    location = clean(loc_el.get_text()) if loc_el else ""

    price_el = None
    for div in card.find_all("div", class_="mb-3"):
        if "USD" in div.get_text():
            price_el = div
            break
    price = parse_price_robust(price_el.get_text() if price_el else "")

    beds = baths = None
    card_size = ""
    for row in card.select("div.text-xs.items-center"):
        use_el = row.find("use")
        if not use_el:
            continue   # tag badges (status/type/amenity pills) have no icon
        icon = use_el.get("href", "").split("#")[-1]
        val  = clean(row.get_text())
        if icon == "icon-bed":
            beds = parse_int(val)
        elif icon == "icon-bath":
            baths = parse_int(val)
        elif icon == "icon-ruler-triangle":
            m2 = re.search(r"([\d,]+)\s*m[²2]", val)
            card_size = f"{m2.group(1)} m²" if m2 else ""

    # NOTE: when class_ is a callable, bs4 invokes it once per individual
    # class token (not the full class list), so the check below must treat
    # `c` as a single string -- iterating over its characters was the bug
    # caught in testing (`for cl in c` off a string, not a list).
    status = "active"
    tag_classes = " ".join(
        " ".join(tag.get("class", []))
        for tag in card.find_all("div", class_=lambda c: c and c.startswith("tag-"))
    )
    for key, val in STATUS_PRIORITY:
        if key in tag_classes:
            status = val
            break

    return {
        "href":      href,
        "name":      name,
        "location":  location,
        "area":      location.split(",")[0].strip() if "," in location else location,
        "askPrice":  price,
        "cardSize":  valid_size(card_size),
        "bedrooms":  beds,
        "bathrooms": baths,
        "status":    status,
    }


def scrape_detail(page, url):
    """Return (image, description, building_size, lot_size)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1)
        soup = BeautifulSoup(page.content(), "html.parser")

        source = soup.find("source")
        img_el = soup.find("img")
        image  = (source["srcset"] if source else None) or (img_el["src"] if img_el else "")

        # Scoped to the "Property Type / Area / Bedrooms / ... / Lot size /
        # Build up size" specs <table>, not the whole page: the page also
        # embeds "similar listings" cards elsewhere, and with no-separator
        # get_text() (needed because RE/MAX renders "m²" as "m" + a separate
        # <sup>2</sup>, which a space-joined get_text() would break apart)
        # a price like "USD 1,700" sitting next to an unrelated listing's
        # "739 m²" merges into a fabricated "1,700739 m²" if the whole page
        # is scanned instead of just this table.
        specs_table = soup.find("table", class_="table")
        specs_text  = specs_table.get_text(strip=True) if specs_table else ""

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc  = max(paras, key=len, default="")

        building_size, lot_size = parse_two_sizes(specs_text)
        return image, desc, valid_size(building_size), valid_size(lot_size)
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

        print(f"\n▶  {BASE_URL}/  (session warm-up)")
        page.goto(BASE_URL + "/", timeout=30000, wait_until="domcontentloaded")
        time.sleep(4)

        for section_path in SEARCH_SECTIONS:
            url = f"{BASE_URL}/{section_path}"
            print(f"\n▶  {url}")
            resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            print(f"   status: {resp.status if resp else None}")
            time.sleep(2.5)

            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = [el for el in soup.find_all("div")
                     if el.get("class") and "bg-white" in el.get("class") and "border-gray-300" in el.get("class")]
            print(f"   {len(cards)} cards")

            for card in cards:
                data = parse_card(card)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                price_str = f"${data['askPrice']:,}/mo" if data["askPrice"] else "price on request"
                print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

                time.sleep(1.5)
                image, desc, building_size, lot_size = scrape_detail(page, href)

                slug = href.rstrip("/").split("/")[-1]
                listings.append({
                    "id":           f"remax-ltr-{slug}",
                    "name":         data["name"],
                    "type":         "ltr",
                    "image":        image,
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     data["askPrice"],
                    "pricePeriod":  "monthly",
                    "size":         building_size or lot_size or data["cardSize"],
                    "buildingSize": building_size,
                    "lotSize":      lot_size,
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        desc,
                })

            time.sleep(3)

        ctx.close()
        browser.close()

    return listings


def save(new_rentals):
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current_rentals = existing.get("rentals", [])
    old_agency       = [r for r in current_rentals if r.get("agency") == AGENCY and r.get("id", "").startswith("remax-ltr-")]
    kept             = [r for r in current_rentals if not (r.get("agency") == AGENCY and r.get("id", "").startswith("remax-ltr-"))]

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
    print(f"\n✓  Saved {len(new_rentals)} RE/MAX Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} LTR rental scraper (remaxaruba.com) …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
