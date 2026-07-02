#!/usr/bin/env python3
"""
MPG Aruba — long-term rental scraper.
Source: https://www.mpgaruba.com/{houses,condos,commercial-property}-for-rent-aruba

Mirrors the for-sale scraper's card/pagination handling (same theme, same
changePage(n) JS pagination), with two differences specific to rentals:

  - Status is read from each card's first `prt-tags` span ("New Listing" /
    "Rented") -- the for-sale scraper hardcodes "active" and never reads
    this, but rentals need real status detection.
  - The card's only size figure is explicitly labelled "Lot size" in the
    DOM (true for houses, condos, and commercial alike). The for-sale
    scraper runs the shared building/lot text-parser on it, which never
    matches here (the site renders the unit as text + <sup>, so plain-text
    scanning finds nothing) and falls back to stuffing the raw value into
    buildingSize regardless of what the card itself calls it. Since the
    card unambiguously labels it "Lot size" and no detail page offers a
    separate building figure, this scraper takes the label at face value
    and reports it as lotSize, leaving buildingSize genuinely blank rather
    than mislabeling it.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_mpg_rentals.py

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

AGENCY    = "MPG Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
BASE_URL  = "https://www.mpgaruba.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_SECTIONS = [
    "houses-for-rent-aruba",
    "condos-for-rent-aruba",
    "commercial-property-for-rent-aruba",
]

# Anything not listed here (New Listing, or no tag at all) means the unit
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


def parse_count(text):
    """Like parse_int, but a decimal count (e.g. '2.5' baths) rounds UP
    rather than truncating -- truncating would silently drop a real half
    bath instead of reporting it."""
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return math.ceil(float(m.group())) if m else None


def get_page_count(soup):
    pager = soup.find("ul", class_="pagination")
    if not pager:
        return 1
    page_items = [li for li in pager.find_all("li") if li.find("a") and re.match(r"^\d+$", li.find("a").get_text().strip())]
    return len(page_items) if page_items else 1


def parse_card(card):
    link_el = card.find("a", class_="properties-link")
    href    = link_el["href"] if link_el else ""

    img_el = card.find("img", class_="core-image")
    image  = img_el["src"] if img_el else ""

    tags_el = card.find(class_="prt-tags")
    spans   = tags_el.find_all("span") if tags_el else []
    status  = STATUS_MAP.get(spans[0].get_text(strip=True).lower(), "active") if spans else "active"

    text_el = card.find(class_="properties-text")
    if not text_el:
        return None

    name_el  = text_el.find("h3")
    loc_el   = text_el.find(class_="prt-location")
    price_el = text_el.find(class_="prt-price")

    name     = clean(name_el.get_text()) if name_el else "Unknown"
    location = clean(loc_el.get_text()) if loc_el else ""
    price    = parse_price_robust(price_el.get_text() if price_el else "")

    beds = baths = None
    lot_size = ""
    for attr in text_el.find_all(class_="attr-item"):
        label = clean(attr.get_text())
        b_val = attr.find("b")
        val   = clean(b_val.get_text()) if b_val else ""   # no separator: keeps "869m2" adjacency intact
        if "Beds" in label:
            beds = parse_int(val)
        elif "Bath" in label:
            baths = parse_count(val)
        elif "size" in label.lower():
            m2 = re.search(r"([\d,]+)\s*m[²2]", val)
            if m2:
                lot_size = f"{m2.group(1)} m²"

    return {
        "href":     href,
        "name":     name,
        "image":    image,
        "location": location,
        "area":     location.split(",")[0].strip() if location else "",
        "askPrice": price,
        "lotSize":  lot_size,
        "bedrooms": beds,
        "bathrooms": baths,
        "status":   status,
    }


def scrape_detail(page, url):
    """Return a description from an MPG listing detail page (best-effort).

    The per-listing text lives inside <div id="overview"> as several short
    <p> tags. Every MPG page also carries a generic "MPG is the top-producing
    real estate company..." company-boilerplate paragraph elsewhere on the
    page that happens to be the single longest <p> on the page -- picking
    the "longest paragraph" (as the for-sale scraper's description fallback
    does) grabs that boilerplate instead of the real listing text, so this
    scopes to #overview specifically rather than reusing that fallback.
    """
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        overview = soup.find(id="overview")
        if overview:
            paras = [p.get_text(strip=True) for p in overview.find_all("p") if p.get_text(strip=True)]
            if paras:
                return clean(" ".join(paras))

        return ""
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return ""


def get_all_cards_for_section(page, url):
    page.goto(url, timeout=30000, wait_until="networkidle")
    time.sleep(2)

    soup      = BeautifulSoup(page.content(), "html.parser")
    num_pages = get_page_count(soup)
    print(f"   Pages: {num_pages}")

    all_cards = soup.find_all(class_="properties-items")

    for pg in range(2, num_pages + 1):
        print(f"   Loading page {pg} …", end=" ", flush=True)
        try:
            page.evaluate(f"changePage({pg})")
            time.sleep(2)
            soup_n  = BeautifulSoup(page.content(), "html.parser")
            cards_n = soup_n.find_all(class_="properties-items")
            print(f"{len(cards_n)} cards")
            all_cards.extend(cards_n)
        except Exception as e:
            print(f"⚠  {e}")

    return all_cards


def scrape_section(browser, section_path, seen_urls):
    results = []
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        url = f"{BASE_URL}/{section_path}"
        print(f"\n▶  {section_path}")

        raw_cards = get_all_cards_for_section(page, url)
        print(f"   Total cards on page: {len(raw_cards)}")

        for card in raw_cards:
            data = parse_card(card)
            if not data or not data["href"] or data["href"] in seen_urls:
                continue
            seen_urls.add(data["href"])

            price_str = f"${data['askPrice']:,}/mo" if data["askPrice"] else "price on request"
            print(f"     → {data['name'][:50]}  |  {price_str}  |  {data['status']}")

            desc = scrape_detail(page, data["href"])
            time.sleep(0.5)

            slug = data["href"].rstrip("/").split("/")[-1]
            results.append({
                "id":           f"mpg-ltr-{slug}",
                "name":         data["name"],
                "type":         "ltr",
                "image":        data["image"],
                "area":         data["area"],
                "location":     data["location"],
                "askPrice":     data["askPrice"],
                "pricePeriod":  "monthly",
                "size":         data["lotSize"],
                "buildingSize": "",
                "lotSize":      data["lotSize"],
                "bedrooms":     data["bedrooms"],
                "bathrooms":    data["bathrooms"],
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    data["href"],
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
        for section_path in SEARCH_SECTIONS:
            listings.extend(scrape_section(browser, section_path, seen_urls))
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
    print(f"\n✓  Saved {len(new_rentals)} MPG Aruba LTR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
