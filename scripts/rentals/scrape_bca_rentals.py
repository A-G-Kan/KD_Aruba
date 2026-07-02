#!/usr/bin/env python3
"""
Bon Choice Aruba Realty (BCA) — long-term rental scraper.
Source: https://bcarubarealty.com/action/rentals/

LTR only. The site's "Vacation Rental" nav item (/listings/vacation-rental/)
was checked and does not contain genuine STR inventory: of its 6 cards, 4
carry status="Sales" with million-AWG for-sale prices, and the other 2 are
the exact same long-term rentals already listed on /action/rentals/ (same
names, same monthly AWG pricing -- no nightly or weekly rate anywhere on
the site). This looks like a mistagging bug on Bon Choice's own site, not
a scraping gap, and including it would mean either double-counting LTR
units under a fabricated "STR" label or writing sale prices into the
rentals dataset. Per explicit direction, this scraper covers LTR only.

The page's pagination widget claims a page 2 exists
(/action/rentals/page/2/), but that page renders zero cards even with a
long wait and networkidle -- a real quirk on the source's end, not a
scraping bug (this is exactly the kind of silent-pagination trap Prima
Casa's scraper hit earlier, so it was checked directly rather than
assumed). The scraper's own pagination loop naturally handles this by
stopping when a page yields zero new cards.

Size isn't on the card, but detail pages label it "Property Size" /
"Property Lot Size" (an alias deduplicate.py's parse_two_sizes didn't
recognize until this scraper needed it -- added there, not duplicated
here). Reading it needs a bare get_text(strip=True) rather than a
space-joined one: this site renders "m²" as "m" + a separate <sup>2</sup>
element, and a space-joined get_text() would insert a fake gap ("462
m 2") that breaks the "m²"-adjacency regex, same issue hit with
RE/MAX and MPG earlier.

Card status is a category tag ("Rentals"), not an availability state;
the site's own status filter options (surfaced in a dropdown) do
include "Rented"/"Sold"/etc, so those are still mapped in case a
future listing actually carries one, even though none currently do.

One listing ("Wayaca 365") carries a price of Afl.1,150,000 -- two
orders of magnitude above every other LTR listing -- and its own
description literally reads "FOR RENT = OR FOR SALE", confirming Bon
Choice dual-listed it and the site is showing the sale price under
the rentals category. Rather than display a $642K/month figure,
LTR_PRICE_CEILING_USD rejects any price implausible for a monthly
rental (set well above every real listing seen: the highest genuine
LTR price found was ~$6,700/mo) and nulls it instead -- the listing
itself (beds/baths/area/size/status) is kept.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_bca_rentals.py

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

AGENCY    = "Bon Choice Aruba Realty"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://bcarubarealty.com"
LTR_URL   = f"{BASE_URL}/action/rentals/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Well above the highest genuine LTR price seen (~$6,700/mo) -- exists only
# to catch a sale price leaking into the rentals category (see "Wayaca 365"
# in the module docstring), not to second-guess ordinary high-end rentals.
LTR_PRICE_CEILING_USD = 50000

# Anything not listed here (the generic "Rentals" category tag, or no tag
# at all) means the unit is still on the market -> "active".
STATUS_MAP = {
    "rented":         "rented",
    "sold":           "sold",
    "sold out":       "sold",
    "under offer":    "under offer",
    "under contract": "under offer",
    "price reduced":  "price reduced",
    "on hold":        "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(card):
    link_el = card.find("a", href=lambda h: h and "/properties/" in h)
    href    = link_el["href"] if link_el else ""
    if href and not href.startswith("http"):
        href = BASE_URL + href

    img_el = card.find("img")
    image  = (img_el.get("data-original") or img_el.get("src") or "") if img_el else ""
    if image and not image.startswith("http"):
        image = BASE_URL + "/" + image.lstrip("/")

    h4        = card.find("h4") or card.find("h3")
    name_link = h4.find("a") if h4 else None
    name      = clean(name_link.get_text() if name_link else (h4.get_text() if h4 else "Unknown"))

    loc_link = card.find("a", href=lambda h: h and "/area/" in h if h else False)
    location = clean(loc_link.get_text()) if loc_link else ""

    price_el = card.find(class_=lambda c: c and "listing_unit_price" in c if c else False)
    price    = parse_price_robust(price_el.get_text(" ") if price_el else "")

    beds_el  = card.find(class_="inforoom")
    baths_el = card.find(class_="infobath")
    beds     = parse_int(beds_el.get_text()  if beds_el  else "")
    baths    = parse_int(baths_el.get_text() if baths_el else "")

    status = "active"
    status_el = card.find(class_=lambda c: c and "action_tag" in c if c else False)
    if status_el:
        status = STATUS_MAP.get(clean(status_el.get_text()).lower(), "active")

    return {
        "href":      href,
        "name":      name,
        "image":     image,
        "location":  location,
        "askPrice":  price,
        "bedrooms":  beds,
        "bathrooms": baths,
        "status":    status,
    }


def scrape_detail(page, url):
    """Return (building_size, lot_size, description) from a listing detail page."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1)
        soup = BeautifulSoup(page.content(), "html.parser")

        # No separator: this site renders "m²" as "m" + a separate <sup>2</sup>
        # element, so a space-joined get_text() would insert a fake gap
        # ("462 m 2") that breaks parse_two_sizes' "m²"-adjacency regex.
        building_size, lot_size = parse_two_sizes(soup.get_text(strip=True))

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc  = max(paras, key=len, default="")

        return building_size, lot_size, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return "", "", ""


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

        page_num = 1
        while True:
            url = LTR_URL if page_num == 1 else f"{LTR_URL}page/{page_num}/"
            print(f"\n▶  {url}")
            resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            print(f"   status: {resp.status if resp else None}")
            time.sleep(4)

            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all(class_="property_card_default")
            print(f"   {len(cards)} cards")

            new_on_page = 0
            for card in cards:
                data = parse_card(card)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)
                new_on_page += 1

                price = data["askPrice"]
                if price is not None and price > LTR_PRICE_CEILING_USD:
                    print(f"     ⚠  ${price:,} exceeds the LTR sanity ceiling — likely a sale price "
                          f"leaking into the rentals category; storing as null, not a fabricated rent")
                    price = None

                price_str = f"${price:,}/mo" if price else "price on request"
                print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

                building_size, lot_size, desc = scrape_detail(page, href)
                time.sleep(1)

                slug = href.rstrip("/").split("/")[-1]
                listings.append({
                    "id":           f"bca-ltr-{slug}",
                    "name":         data["name"],
                    "type":         "ltr",
                    "image":        data["image"],
                    "area":         data["location"],
                    "location":     data["location"],
                    "askPrice":     price,
                    "pricePeriod":  "monthly",
                    "size":         building_size or lot_size,
                    "buildingSize": building_size,
                    "lotSize":      lot_size,
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": price}],
                    "notes":        desc,
                })

            if new_on_page == 0:
                break
            page_num += 1
            time.sleep(2)

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
    print(f"\n✓  Saved {len(new_rentals)} Bon Choice Aruba Realty LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
