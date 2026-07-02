#!/usr/bin/env python3
"""
Prima Casa Real Estate — LTR + STR rental scraper.
Source: https://aruba-realty.com/listings/{active-rentals,vacation-rentals}

Two cleanly separated sections: active-rentals (long-term, monthly) and
vacation-rentals (short-term, nightly -- each detail page confirms
"*Price per night" and the card price is explicitly labelled "Starting
From", since vacation rates vary by season). Pagination is AJAX-driven
(October CMS "Listings::onFilter" request), not a URL query param, so
page links are clicked rather than navigated to directly.

Most residential detail pages carry no size (m²/sq ft) figure at all --
confirmed genuinely absent there, not a scraping gap -- but some
commercial/industrial listings do publish a "Build Up Size: N m2" label,
so size is still extracted per listing rather than assumed blank
site-wide; no "similar listings" widget was found on any detail page
tried, so reading the whole page's text for it is safe here.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_primacasa_rentals.py

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
from deduplicate import parse_price_robust, parse_two_sizes

AGENCY    = "Prima Casa Real Estate"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://aruba-realty.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SECTIONS = [
    ("listings/active-rentals",   "ltr", "monthly"),
    ("listings/vacation-rentals", "str", "nightly"),
]

# Anything not listed here (New Listing, or no status at all) means the
# unit is still on the market -> "active".
STATUS_MAP = {
    "rented":            "rented",
    "under offer":       "under offer",
    "price reduced":     "price reduced",
    "sold":              "sold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_card(card):
    href = card.get("href", "")

    img_el = card.find("img")
    image  = img_el.get("src", "") if img_el else ""

    status_el = card.find(class_="status")
    status_raw = clean(status_el.get_text()) if status_el else ""
    status     = STATUS_MAP.get(status_raw.lower(), "active")

    price_el = card.find(class_="price")
    price_text = clean(price_el.get_text()) if price_el else ""
    # "Starting From $475.00 ƒ845.50 Noord" / "Rented Noord" / "$5,350.00 ƒ9,523.00 Oranjestad"
    # -- strip the leading label and trailing location so parse_price_robust
    # sees only the USD figure, and so the AFL amount never gets picked up
    # as if it were a second, different price.
    price_text = re.sub(r"^Starting From\s*", "", price_text, flags=re.I)
    price = parse_price_robust(price_text)

    title_el = card.find(class_="title")
    name     = clean(title_el.get_text()) if title_el else "Unknown"

    loc_el   = card.find(class_="location")
    location = clean(loc_el.get_text()) if loc_el else ""

    return {
        "href":     href,
        "name":     name,
        "image":    image,
        "location": location,
        "askPrice": price,
        "status":   status,
    }


def scrape_detail(page, url):
    """Return (bedrooms, bathrooms, building_size, lot_size, description)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        beds = baths = None
        m = re.search(r"Bedrooms:\s*(\d+)", text, re.I)
        if m:
            beds = int(m.group(1))
        m = re.search(r"Bathrooms:\s*(\d+(?:\.\d+)?)", text, re.I)
        if m:
            baths = math.ceil(float(m.group(1)))   # a half-bath is real; round up, don't truncate

        building_size, lot_size = parse_two_sizes(text)

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc  = max(paras, key=len, default="")

        return beds, baths, building_size, lot_size, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, "", "", ""


def collect_cards(page, section_path, seen_urls):
    """Walk every page of a section's AJAX pagination and return the raw
    cards, all in one pass. Detail pages are visited separately afterward
    (see scrape_section) -- doing it interleaved with pagination breaks the
    next-page click, since page.goto() to a detail page navigates the same
    Playwright page away from the listings grid, so the "next page" link
    Playwright looks for afterward is gone."""
    url = f"{BASE_URL}/{section_path}"
    print(f"\n▶  {url}")
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)

    all_cards = []
    page_num  = 1
    while True:
        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all("a", class_="property")
        print(f"   page {page_num}: {len(cards)} cards")

        new_on_page = 0
        for card in cards:
            data = parse_card(card)
            if not data["href"] or data["href"] in seen_urls:
                continue
            seen_urls.add(data["href"])
            all_cards.append(data)
            new_on_page += 1

        if new_on_page == 0:
            break

        next_link = page.locator(f'a.page-link:has-text("{page_num + 1}")')
        if next_link.count() == 0:
            break
        next_link.first.click()
        time.sleep(2)
        page_num += 1

    return all_cards


def scrape_section(page, section_path, listing_type, price_period, seen_urls):
    results = []
    cards = collect_cards(page, section_path, seen_urls)

    for data in cards:
        price_str = f"${data['askPrice']:,}" if data["askPrice"] else "price on request"
        print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

        beds, baths, building_size, lot_size, desc = scrape_detail(page, data["href"])
        time.sleep(0.6)

        slug = data["href"].rstrip("/").split("/")[-1]
        results.append({
            "id":           f"primacasa-{listing_type}-{slug}",
            "name":         data["name"],
            "type":         listing_type,
            "image":        data["image"],
            "area":         data["location"],
            "location":     data["location"],
            "askPrice":     data["askPrice"],
            "pricePeriod":  price_period,
            "size":         building_size or lot_size,
            "buildingSize": building_size,
            "lotSize":      lot_size,
            "bedrooms":     beds,
            "bathrooms":    baths,
            "agency":       AGENCY,
            "listedDate":   TODAY,
            "sourceUrl":    data["href"],
            "status":       data["status"],
            "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
            "notes":        desc,
        })

    return results


def scrape_all():
    listings  = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=USER_AGENT)
        page    = ctx.new_page()

        for section_path, listing_type, price_period in SECTIONS:
            listings.extend(scrape_section(page, section_path, listing_type, price_period, seen_urls))
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
    print(f"\n✓  Saved {ltr_count} LTR + {str_count} STR = {len(new_rentals)} Prima Casa rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
