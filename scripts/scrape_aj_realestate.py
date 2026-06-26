#!/usr/bin/env python3
"""
AJ Real Estate Aruba property listing scraper.
Source: https://ajrealestatearuba.com

Uses the MH Estate WordPress plugin. Cards are <article> elements.
Detail page provides price, beds, baths, size, and description.

Usage:
    python3 scrape_aj_realestate.py

Requirements:
    pip3 install playwright beautifulsoup4
    python3 -m playwright install chromium
"""

import sys, json, re, time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from deduplicate import dedup_within_site, parse_price_robust, parse_two_sizes, restore_user_fields

BASE_URL   = "https://ajrealestatearuba.com"
AGENCY     = "AJ Real Estate Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/property-type/house-for-sale/",        "house"),
    ("/property-type/condominium/",           "condo"),
    ("/property-type/land/",                  "land"),
    ("/property-type/commercial-properties/", "commercial"),
]

# "Sold!" has a trailing "!" on the MH Estate plugin — strip punctuation before lookup.
AJ_STATUS_MAP = {
    "sold":           "sold",
    "for sale":       "active",
    "under offer":    "under offer",
    "under contract": "under offer",
    "price reduced":  "price reduced",
    "on hold":        "on hold",
}

# Labels in the mh-estate__list__element that indicate building/interior area
_BUILDING_SIZE_LABELS = re.compile(
    r"^(?:property|building|floor|interior|living|house)\s*size\s*:", re.I
)
_LOT_SIZE_LABELS = re.compile(
    r"^(?:lot|land|parcel|plot)\s*size\s*:", re.I
)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def _alpha(text):
    """Lowercase + strip all non-alpha/space characters (handles 'Sold!', etc.)."""
    return re.sub(r"[^a-z\s]", "", (text or "").lower()).strip()


def parse_card(article):
    link_el = article.find("a")
    href    = link_el["href"] if link_el else ""
    if href and not href.startswith("http"):
        href = BASE_URL + href

    img_el = article.find("img")
    image  = img_el.get("src") or img_el.get("data-src") or "" if img_el else ""

    h = article.find(["h2", "h3"])
    name = clean(h.get_text()) if h else clean(link_el.get_text()) if link_el else "Unknown"

    price_el = article.find(class_=re.compile(r"price", re.I))
    price = parse_price(price_el.get_text() if price_el else "")
    if not price:
        price = parse_price(article.get_text())

    text = article.get_text(" ")
    beds  = parse_int(re.search(r"(\d+)\s*[Bb]edroom", text).group(1) if re.search(r"(\d+)\s*[Bb]edroom", text) else "")
    baths = parse_int(re.search(r"(\d+)\s*[Bb]athroom", text).group(1) if re.search(r"(\d+)\s*[Bb]athroom", text) else "")

    location = ""
    for cls in article.get("class", []):
        m = re.match(r"mh-attribute-city__(.+)", cls)
        if m:
            location = m.group(1).replace("-", " ").title()
            break

    size_el = article.find(class_=re.compile(r"size|area|sqft|sqm", re.I))
    size    = clean(size_el.get_text()) if size_el else ""

    # Status from card badge (MH Estate uses mh-label__sold, mh-label__under-contract, etc.)
    # Strip non-alpha characters before lookup — "Sold!" → "sold"
    status = "active"
    status_el = article.find(class_=re.compile(r"label|badge|tag|status", re.I))
    if status_el:
        st = _alpha(status_el.get_text())
        status = AJ_STATUS_MAP.get(st, "active")

    return {
        "name":     name,
        "href":     href,
        "image":    image,
        "location": location,
        "area":     location,
        "askPrice": price,
        "size":     size,
        "bedrooms": beds,
        "bathrooms": baths,
        "status":   status,
    }


def _parse_m2_from_attr(raw):
    """Parse 'NNN m2' or 'N,NNN m2' from an attribute list item value."""
    m = re.search(r"([0-9,. ]+)\s*m[²2]?", raw, re.I)
    if not m:
        return ""
    try:
        v = float(m.group(1).replace(",", "").replace(" ", ""))
        return f"{int(v)} m²" if v >= 10 else ""
    except ValueError:
        return ""


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")

        # First photo — three structures observed across listing types:
        # 1. Houses/condos: swiper gallery div (mh-popup-group) with img tags inside
        # 2. Houses/condos fallback: individual mh-popup-group__element anchor hrefs
        # 3. Land/commercial: single plain <a class="mh-popup"> whose href IS the image
        image = ""
        gallery = soup.find(class_="mh-popup-group")
        if gallery:
            img = gallery.find("img")
            if img:
                image = img.get("src") or img.get("data-src") or ""
        if not image:
            link = soup.find(class_="mh-popup-group__element")
            if link:
                image = link.get("href", "")
        if not image:
            # Land/commercial: no gallery wrapper, just a bare mh-popup anchor
            popup = soup.find("a", class_="mh-popup")
            if popup:
                image = popup.get("href", "")

        text  = soup.get_text(" ", strip=True)

        # Price: targeted element lookup only — intentionally no full-page-text fallback.
        # Full page text can contain stray dollar amounts (parking fees, deposits, etc.)
        # that get mistaken for the listing price when the real price field is absent.
        price = None
        price_el = (
            soup.select_one(".mh-estate__listing-price, .listing-price, .property-price")
            or soup.find(class_=re.compile(r"^price$", re.I))
        )
        if price_el:
            price = parse_price(price_el.get_text())

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc  = max(paras, key=len, default="")

        # Parse ALL property data from the MH Estate structured attribute list.
        # This avoids false positives from sidebar filters, related listings, etc.
        beds = baths = None
        building_size = lot_size = ""
        detail_status = None

        for li in soup.find_all(class_="mh-estate__list__element"):
            raw   = li.get_text(" ", strip=True)
            lower = raw.lower()

            if lower.startswith("offer type:"):
                offer_val = _alpha(raw.replace("Offer type:", "").replace("offer type:", ""))
                detail_status = AJ_STATUS_MAP.get(offer_val)

            elif re.match(r"(?:asking\s*)?price\s*:", lower) and price is None:
                # Attribute list fallback for price (only used when no dedicated price element)
                price = parse_price(raw)

            elif re.match(r"bedrooms?\s*:", lower):
                m = re.search(r"(\d+)", raw)
                if m and beds is None:
                    beds = int(m.group(1))

            elif re.match(r"bathrooms?\s*:", lower):
                m = re.search(r"(\d+)", raw)
                if m and baths is None:
                    baths = int(m.group(1))

            elif _BUILDING_SIZE_LABELS.match(raw):
                if not building_size:
                    building_size = _parse_m2_from_attr(raw)

            elif _LOT_SIZE_LABELS.match(raw):
                if not lot_size:
                    lot_size = _parse_m2_from_attr(raw)

        # Fallback for size only: if the attribute list had nothing, try full text.
        if not building_size and not lot_size:
            building_size, lot_size = parse_two_sizes(text)

        size = building_size or lot_size

        return price, beds, baths, size, building_size, lot_size, desc, image, detail_status

    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, None, "", "", "", "", "", None


def scrape_section(browser, section_path, listing_type, seen_urls):
    results = []
    page_num = 1

    while True:
        ctx  = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()
        try:
            url = BASE_URL + section_path
            if page_num > 1:
                url = BASE_URL + section_path.rstrip("/") + f"/page/{page_num}/"
            print(f"\n▶  {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            soup     = BeautifulSoup(page.content(), "html.parser")
            articles = soup.find_all("article", class_="mh-estate-vertical")
            print(f"   {len(articles)} cards")
            if not articles:
                break

            for article in articles:
                data = parse_card(article)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                print(f"     → {data['name'][:50]}")
                price, beds, baths, size, building_size, lot_size, desc, detail_image, detail_status = scrape_detail(page, href)
                time.sleep(0.4)

                # For land listings, "Property size" on AJ's site means the parcel area.
                # If we parsed it as building_size but there's no explicit lot_size, swap.
                if listing_type == "land" and building_size and not lot_size:
                    lot_size = building_size
                    building_size = ""
                    size = lot_size

                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":           slug,
                    "name":         data["name"],
                    "type":         listing_type,
                    "image":        detail_image or data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     price or data["askPrice"],
                    "size":         size or data["size"],
                    "buildingSize": building_size or "",
                    "lotSize":      lot_size or "",
                    "bedrooms":     beds if beds is not None else data["bedrooms"],
                    "bathrooms":    baths if baths is not None else data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       detail_status or data["status"],
                    "priceHistory": [{"date": TODAY, "price": price or data["askPrice"]}],
                    "notes":        desc,
                })

            next_el = soup.find("a", class_=re.compile(r"next|»", re.I))
            if not next_el:
                break
            page_num += 1

        finally:
            ctx.close()
        time.sleep(1)

    return results


def scrape_all():
    listings = []
    seen_urls = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for section_path, listing_type in SEARCH_SECTIONS:
            listings.extend(scrape_section(browser, section_path, listing_type, seen_urls))
            time.sleep(2)
        browser.close()
    return listings


def save(new_listings):
    new_listings, _ = dedup_within_site(new_listings, AGENCY)
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    old_agency   = [l for l in current if l.get("agency") == AGENCY]
    kept    = [l for l in current if l.get("agency") != AGENCY]
    new_listings = restore_user_fields(old_agency, new_listings)
    merged       = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} {AGENCY} listings → {DATA_JSON} ({len(merged)} total)")


if __name__ == "__main__":
    print(f"{AGENCY} scraper …")
    listings = scrape_all()
    print(f"\nScraped {len(listings)} listings. Saving …")
    save(listings)
