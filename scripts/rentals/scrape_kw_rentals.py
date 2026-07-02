#!/usr/bin/env python3
"""
Keller Williams Aruba — long-term rental scraper.
Source: https://kw-aruba.com/listings/for-rent/{residential,condominium-townhouse,commercial,apartment}

LTR only. KW's short-term/vacation rentals live on a separate, date-gated
booking flow (bestrentalsaruba.com) and are explicitly out of scope here.

Card gives price/location/bedrooms/status directly; a raw "size" option on
the card doesn't say whether it's building or lot area, so it's used only
as a last-resort fallback. Each detail page carries clean, separately
labelled "Land size N m²" / "Build up size N m²" text (same site, same
layout as the for-sale pages) and a "N bathroom(s)" figure, so those are
parsed from there instead of guessing from the ambiguous card value.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_kw_rentals.py

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

AGENCY    = "Keller Williams Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://kw-aruba.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# land-for-rent exists as a category but is empty at the time of writing;
# left out rather than hardcoding a listing_type for zero results.
SEARCH_SECTIONS = [
    ("/listings/for-rent/residential",            "house"),
    ("/listings/for-rent/condominium-townhouse",  "condo"),
    ("/listings/for-rent/apartment",              "condo"),
    ("/listings/for-rent/commercial",              "commercial"),
]

# Anything not listed here (New Listing, Price upon Request, or no label at
# all) means the unit is still on the market -> "active".
STATUS_MAP = {
    "rented":            "rented",
    "reduced in price":  "price reduced",
    "under offer":       "under offer",
    "under contract":    "under offer",
    "on hold":           "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_area(location_text):
    """'Palm Beach, Noord' -> 'Palm Beach'  |  'Savaneta' -> 'Savaneta'"""
    return clean(location_text.split(",")[0]) if location_text else ""


def parse_card(card):
    url_el   = card.find("a", class_="card__overlay")
    href     = url_el["href"] if url_el else ""
    if href.startswith("/"):
        href = BASE_URL + href

    name_el  = card.find(class_="card__heading")
    loc_el   = card.find(class_="card__location")
    price_el = card.find(class_="card__price")
    img_el   = card.find("img", class_="card__image-img")

    # Options: first = size (ruler icon, unit unclear -- building or lot),
    # second = bedrooms (door icon).
    opts       = card.find_all(class_="option")
    size_text  = clean(opts[0].find(class_="option__value").get_text()) if len(opts) > 0 else ""
    beds_text  = clean(opts[1].find(class_="option__value").get_text()) if len(opts) > 1 else ""
    beds       = parse_int(beds_text)

    location = clean(loc_el.get_text()) if loc_el else ""

    status = "active"
    label_el = card.find(class_="card__label")
    if label_el:
        status = STATUS_MAP.get(clean(label_el.get_text()).lower(), "active")

    return {
        "href":       href,
        "name":       clean(name_el.get_text()) if name_el else "Unknown",
        "image":      img_el["src"] if img_el else "",
        "location":   location,
        "area":       parse_area(location),
        "askPrice":   parse_price_robust(price_el.get_text() if price_el else ""),
        "card_size":  size_text,
        "bedrooms":   beds,
        "status":     status,
    }


def scrape_detail(page, url):
    """Return (bathrooms, description, building_size, lot_size)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        baths = None
        m = re.search(r"(\d+)\s*bathroom\(s\)", text, re.I)
        if m:
            baths = int(m.group(1))

        description = ""
        idx = text.find("Description")
        if idx >= 0:
            after = text[idx + len("Description"):]
            stop = re.search(r"\b(Features|Map|Contact|Agent)\b", after)
            snippet = after[:stop.start()].strip() if stop else after[:2000].strip()
            description = clean(snippet)
        if not description:
            paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 80]
            description = max(paras, key=len, default="")

        building_size, lot_size = parse_two_sizes(text)

        return baths, description, building_size, lot_size
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, "", "", ""


def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  {section_path}")
        page.goto(BASE_URL + section_path, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("div.card", timeout=10000)
        except Exception:
            pass
        time.sleep(2)

        soup  = BeautifulSoup(page.content(), "html.parser")
        cards = soup.find_all(class_="card")
        print(f"   {len(cards)} cards")

        for card in cards:
            data = parse_card(card)
            href = data["href"]
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            price_str = f"${data['askPrice']:,}/mo" if data["askPrice"] else "price on request"
            print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

            baths, desc, building_size, lot_size = scrape_detail(page, href)
            time.sleep(1.5)

            slug = href.rstrip("/").split("/")[-1]
            results.append({
                "id":           f"kw-ltr-{slug}",
                "name":         data["name"],
                "type":         "ltr",
                "image":        data["image"],
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "pricePeriod":  "monthly",
                "size":         building_size or lot_size,
                "buildingSize": building_size,
                "lotSize":      lot_size,
                "bedrooms":     data["bedrooms"],
                "bathrooms":    baths,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    href,
                "status":       data["status"],
                "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                "notes":        desc,
            })
    finally:
        ctx.close()

    return results


def scrape_all():
    listings  = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for section_path, listing_type in SEARCH_SECTIONS:
            listings.extend(scrape_section(browser, section_path, listing_type, seen_urls))
            time.sleep(2)
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
    print(f"\n✓  Saved {len(new_rentals)} Keller Williams Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
