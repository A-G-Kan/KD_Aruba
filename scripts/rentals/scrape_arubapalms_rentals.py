#!/usr/bin/env python3
"""
Aruba Palms Realtors — LTR + STR rental scraper.
Source: https://arubapalmsrealtors.com (Houzez WordPress theme)

Three explicit nav categories map onto our two rental types:
  property-type/long-term-rentals/  -> LTR, monthly
  property-type/commercial-rentals/ -> LTR, monthly (a commercial lease is
                                       still "long term" in duration, same
                                       treatment as every other agency's
                                       commercial rentals this session)
  property-type/vacation-rental/    -> STR

STR pricing note: vacation-rental cards publish a per-WEEK rate ("$595
/week", confirmed on the large majority of cards), not nightly -- no
nightly figure exists anywhere on the site, including detail pages. The
task asked for STR listings tagged nightly, but computing nightly by
dividing the weekly rate by 7 would mean displaying a number the source
never actually states. Per explicit direction, these are stored as-is
with pricePeriod="weekly" rather than a derived/fabricated nightly figure.

Card data (name, href, image, price, beds, baths) comes from the shared
parse_houzez_card() already used by the for-sale scraper. Area and size
are NOT reliable from the card (both blank on most cards) and are read
from the detail page instead -- but scoped to specific labelled blocks
(#area-label's sibling span, the ".h-area-sizes" overview item, and
#property-description-wrap for notes), not the whole page: detail pages
also render a "Similar Listings" section whose unrelated numbers would
otherwise contaminate a plain full-page-text scan (confirmed directly --
an unrelated "$3,323 /week" from a sidebar card showed up in an early,
unscoped test).

No rented/sold status signal exists anywhere on the site (checked ~98
cards across all three categories: every status label is just "For
Rent" or "Vacation Rentals" -- a category tag, not an availability
state), so every listing is written as "active"; that's an honest
reflection of what the source shows; ROG and RE/MAX's STR listings hit
this same situation earlier and were handled the same way.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_arubapalms_rentals.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   # find deduplicate.py / scrape_houzez.py in scripts/
sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from scrape_houzez import parse_houzez_card

AGENCY    = "Aruba Palms Realtors"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://arubapalmsrealtors.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SECTIONS = [
    ("property-type/long-term-rentals/",  "ltr", "monthly"),
    ("property-type/commercial-rentals/", "ltr", "monthly"),
    ("property-type/vacation-rental/",    "str", "weekly"),
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def convert_size(raw):
    """'645.83 Sq Ft' -> '60 m²'; '120 m²'/'120m2' -> '120 m²'; '' if unparseable."""
    if not raw:
        return ""
    m = re.search(r"([\d,.]+)", raw)
    if not m:
        return ""
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return ""
    if v <= 0:
        return ""
    if re.search(r"sq\.?\s*ft|sqft", raw, re.I):
        v *= 0.0929
    return f"{round(v)} m²"


def collect_cards(page, section_path, seen_urls):
    all_cards = []
    page_num  = 1
    while True:
        url = f"{BASE_URL}/{section_path}" if page_num == 1 else f"{BASE_URL}/{section_path}page/{page_num}/"
        print(f"\n▶  {url}")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(4)   # AJAX-loaded listings need a beat to render

        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all(class_="item-listing-wrap")
        print(f"   {len(cards)} cards")

        new_on_page = 0
        for card in cards:
            data = parse_houzez_card(card)
            href = data["href"]
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)
            all_cards.append(data)
            new_on_page += 1

        if new_on_page == 0:
            break
        page_num += 1
        time.sleep(2)

    return all_cards


def scrape_detail(page, url):
    """Return (area, size, description), each scoped to its own labelled
    block rather than the whole page (which also renders unrelated
    "Similar Listings" cards)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1.5)
        soup = BeautifulSoup(page.content(), "html.parser")

        area = ""
        area_label = soup.find(id="area-label")
        if area_label:
            value_el = soup.find(attrs={"aria-labelledby": "area-label"})
            if value_el:
                area = clean(value_el.get_text())

        # Scoped to #property-overview-wrap specifically, not the whole
        # page: a "Similar Listings" section renders further down and a
        # bare class_="h-area-sizes" search isn't otherwise guaranteed to
        # skip it.
        size = ""
        overview = soup.find(id="property-overview-wrap")
        size_label = overview.find(class_="h-area-sizes") if overview else None
        if size_label:
            item = size_label.find_previous_sibling("li", class_="property-overview-item")
            if item:
                strong = item.find("strong")
                if strong:
                    size = convert_size(clean(strong.get_text()))

        desc = ""
        desc_wrap = soup.find(id="property-description-wrap")
        if desc_wrap:
            desc = clean(desc_wrap.get_text(" "))
            desc = re.sub(r"^Description\s*", "", desc)

        return area, size, desc
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

        for section_path, listing_type, price_period in SECTIONS:
            cards = collect_cards(page, section_path, seen_urls)
            print(f"   {len(cards)} unique cards in this section")

            for data in cards:
                price_str = f"${data['askPrice']:,}" if data["askPrice"] else "price on request"
                print(f"     → {data['name'][:50]}  |  {price_str}/{price_period}")

                area, size, desc = scrape_detail(page, data["href"])
                time.sleep(0.8)

                slug = data["href"].rstrip("/").split("/")[-1]
                listings.append({
                    "id":           f"arubapalms-{listing_type}-{slug}",
                    "name":         data["name"],
                    "type":         listing_type,
                    "image":        data["image"],
                    "area":         area,
                    "location":     area,
                    "askPrice":     data["askPrice"],
                    "pricePeriod":  price_period,
                    "size":         size,
                    "buildingSize": size,
                    "lotSize":      "",
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    data["href"],
                    "status":       "active",
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        desc,
                })

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

    ltr_count = sum(1 for r in new_rentals if r["type"] == "ltr")
    str_count = sum(1 for r in new_rentals if r["type"] == "str")
    total = len(existing.get("rentals", []))
    print(f"\n✓  Saved {ltr_count} LTR + {str_count} STR = {len(new_rentals)} Aruba Palms rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
