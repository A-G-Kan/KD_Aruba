#!/usr/bin/env python3
"""
Century 21 Aruba — long-term rental scraper.
Source: https://century21aruba.com/en/s/for-rent/{single-family-homes,condos-apartments}

C21 sits behind a CloudFront WAF that 403s any request that isn't part of an
established browser session: hitting a /en/s/... search URL as the very
first request of a fresh session gets blocked, even from headless Chromium
with a normal user agent. Visiting the homepage first (in the same browser
context, so its cookies carry over) and only then navigating to the search
pages reliably gets through. The WAF is also rate-limit sensitive, so this
scraper deliberately reuses ONE browser context/page for the entire run
(homepage warm-up + both category pages + every detail page) and paces
requests generously rather than opening fresh contexts per section the way
the for-sale scraper does.

Card beds/baths use an ambiguous "N · M · view · size" shorthand that
collapses for studios (e.g. "1 · Inland View" -- is "1" a bed or a bath?),
so beds/baths are read from each detail page's unambiguous "Beds N Baths M"
text instead of guessed from card position.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_century21_rentals.py

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

AGENCY    = "Century 21 Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://century21aruba.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_SECTIONS = [
    "en/s/for-rent/single-family-homes",
    "en/s/for-rent/condos-apartments",
]

# Anything not listed here (New Listing, or no ribbon at all) means the unit
# is still on the market -> "active".
STATUS_MAP = {
    "rented":          "rented",
    "under contract":  "under offer",
    "sold":            "sold",
    "price reduced":   "price reduced",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_area(location_text):
    """'Pos Chiquito (Savaneta)' -> 'Savaneta'"""
    m = re.search(r"\(([^)]+)\)", location_text or "")
    return m.group(1).strip() if m else clean(location_text)


def best_image_url(img_tag):
    if not img_tag:
        return ""
    src = img_tag.get("src", "")
    src_780 = re.sub(r"/w\d+/", "/w780/", src)
    src_jpg = re.sub(r"\.avif|\.webp", ".jpg", src_780)
    src_jpg = src_jpg or src
    return BASE_URL + src_jpg if src_jpg.startswith("/") else src_jpg


def parse_card(card):
    mls = card.get("data-ad-id", "")

    price_el = card.find(class_=lambda c: c and "card-header" in c)
    price    = parse_price_robust(price_el.get_text() if price_el else "")

    h2    = card.find("h2")
    spans = h2.find_all("span", recursive=False) if h2 else []
    name     = clean(spans[0].get_text()) if len(spans) > 0 else clean(card.get("data-ad-title", ""))
    location = clean(spans[1].get_text()) if len(spans) > 1 else ""

    img = card.find("img", class_=lambda c: c and "thumb" in c.split() if c else False)
    image = best_image_url(img)

    link_el = card.find("a", class_=lambda c: c and "card-body" in c.split() if c else False)
    href = link_el["href"] if link_el and link_el.get("href") else ""
    source_url = BASE_URL + href if href.startswith("/") else href

    ribbon = card.find(class_=lambda c: c and "ribbon" in c if c else False)
    status = STATUS_MAP.get(ribbon.get_text(strip=True).lower(), "active") if ribbon else "active"

    return {
        "mls":       mls,
        "name":      name or "Unknown",
        "image":     image,
        "location":  location,
        "area":      parse_area(location),
        "askPrice":  price,
        "status":    status,
        "sourceUrl": source_url,
    }


def scrape_detail(page, url):
    """Return (bedrooms, bathrooms, description, building_size, lot_size)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1.5)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        beds = baths = None
        m = re.search(r"\bBeds\s+(\d+)", text)
        if m:
            beds = int(m.group(1))
        m = re.search(r"\bBaths\s+(\d+)", text)
        if m:
            baths = int(m.group(1))

        remarks = soup.find(class_=lambda c: c and "remarks" in c.lower() if c else False)
        description = clean(remarks.get_text()) if remarks else ""

        building_size, lot_size = parse_two_sizes(text)

        return beds, baths, description, building_size, lot_size
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, "", "", ""


def scrape_all():
    listings  = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # One context/session for the entire run -- the WAF requires a
        # homepage-established cookie before it'll serve search pages, and
        # a fresh context per section would lose that cookie.
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()

        print(f"\n▶  {BASE_URL}/  (session warm-up)")
        page.goto(BASE_URL + "/", timeout=30000, wait_until="domcontentloaded")
        time.sleep(8)

        for section_path in SEARCH_SECTIONS:
            url = f"{BASE_URL}/{section_path}"
            print(f"\n▶  {url}")
            resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            print(f"   status: {resp.status if resp else None}")
            try:
                page.wait_for_selector("article.card-listing", timeout=15000)
            except Exception as e:
                print(f"   (selector wait: {e})")
            time.sleep(3)

            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all("article", class_="card-listing")
            print(f"   {len(cards)} cards")

            for card in cards:
                data = parse_card(card)
                mls  = data["mls"]
                if not mls or mls in seen_urls:
                    continue
                seen_urls.add(mls)

                price_str = f"${data['askPrice']:,}/mo" if data["askPrice"] else "price on request"
                print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

                time.sleep(4)
                beds, baths, desc, building_size, lot_size = scrape_detail(page, data["sourceUrl"])

                listings.append({
                    "id":           f"c21-ltr-{mls}",
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
                    "bedrooms":     beds,
                    "bathrooms":    baths,
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    data["sourceUrl"],
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        desc,
                })

            time.sleep(15)

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
    print(f"\n✓  Saved {len(new_rentals)} Century 21 Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
