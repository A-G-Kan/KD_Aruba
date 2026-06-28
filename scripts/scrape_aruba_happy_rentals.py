#!/usr/bin/env python3
"""
Aruba Happy Homes rental scraper.
Covers two sources:
  LTR  — arubahappyrentals.com/listings   (long-term, monthly rent, custom Laravel/Guesty)
  STR  — casagoaruba.com/vacation-rentals  (vacation rentals, nightly, Streamline VRS/AngularJS)

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_aruba_happy_rentals.py

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
from deduplicate import parse_price_robust

AGENCY    = "Aruba Happy Homes"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

LTR_BASE = "https://arubahappyrentals.com"
STR_BASE = "https://casagoaruba.com"

LTR_STATUS_MAP = {
    "rented":         "rented",
    "under contract": "under offer",
    "new listing":    "active",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    return parse_price_robust(text)


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


# ─────────────────────────────────────────────
#  LTR scraper  (arubahappyrentals.com)
# ─────────────────────────────────────────────

def scrape_ltr_detail(page, url):
    """Visit a detail page and return (area, bedrooms, bathrooms, description)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1)
        soup = BeautifulSoup(page.content(), "html.parser")

        # Spec table: rows are (Label, Value)
        specs = {}
        for row in soup.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) == 2:
                specs[clean(cells[0].get_text()).lower()] = clean(cells[1].get_text())

        area      = specs.get("location", "")
        bedrooms  = parse_int(specs.get("bedrooms", ""))
        bathrooms = parse_int(specs.get("bathrooms", ""))

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        description = max(paras, key=len, default="")

        return area, bedrooms, bathrooms, description
    except Exception as e:
        print(f"    ⚠  LTR detail failed ({url}): {e}")
        return "", None, None, ""


def scrape_ltr(browser):
    results = []
    seen = set()
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  LTR: {LTR_BASE}/listings")
        page.goto(f"{LTR_BASE}/listings", timeout=30000, wait_until="networkidle")
        time.sleep(3)
        soup = BeautifulSoup(page.content(), "html.parser")

        cards = soup.find_all(attrs={"data-block": "card-listing"})
        print(f"   {len(cards)} LTR cards found")

        for card in cards:
            # Link
            name_link = card.find("a", class_=re.compile(r"font-secondary"))
            if not name_link:
                name_link = card.find("a", href=lambda h: h and "/listing/" in h)
            if not name_link:
                continue
            href = name_link["href"]
            if href in seen:
                continue
            seen.add(href)

            name = clean(name_link.get_text()) or href.rstrip("/").split("/")[-1]

            # Image: prefer webp source, fall back to img src
            source_el = card.find("source", attrs={"srcset": True})
            img_el    = card.find("img", src=True)
            image = ""
            if source_el:
                image = source_el["srcset"].split()[0]  # first URL in srcset
            elif img_el:
                image = img_el.get("src", "")

            # Price: div with "italic" class containing "per month"
            price_el = card.find("div", class_=re.compile(r"\bitalic\b"))
            price = parse_price(price_el.get_text() if price_el else "")

            # Status badge
            badge = card.find("div", class_=re.compile(r"bg-tertiary"))
            badge_text = clean(badge.get_text()).lower() if badge else ""
            status = LTR_STATUS_MAP.get(badge_text, "active")

            # Beds/baths from card (fallback if detail fails)
            card_text = card.get_text(" ")
            card_beds  = parse_int(re.search(r"(\d+)\s*bed", card_text, re.I).group(1)
                                   if re.search(r"(\d+)\s*bed", card_text, re.I) else "")
            card_baths = parse_int(re.search(r"(\d+)\s*bath", card_text, re.I).group(1)
                                   if re.search(r"(\d+)\s*bath", card_text, re.I) else "")

            print(f"     → {name[:55]}")
            area, bedrooms, bathrooms, description = scrape_ltr_detail(page, href)
            bedrooms  = bedrooms  if bedrooms  is not None else card_beds
            bathrooms = bathrooms if bathrooms is not None else card_baths
            time.sleep(0.5)

            slug = href.rstrip("/").split("/")[-1]
            results.append({
                "id":           f"ahr-ltr-{slug}",
                "name":         name,
                "type":         "ltr",
                "image":        image,
                "area":         area,
                "location":     area,
                "askPrice":     price,
                "pricePeriod":  "monthly",
                "size":         "",
                "buildingSize": "",
                "lotSize":      "",
                "bedrooms":     bedrooms,
                "bathrooms":    bathrooms,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    href,
                "status":       status,
                "priceHistory": [{"date": TODAY, "price": price}],
                "notes":        description,
            })
    finally:
        ctx.close()

    return results


# ─────────────────────────────────────────────
#  STR scraper  (casagoaruba.com)
# ─────────────────────────────────────────────

def scrape_str_detail(page, url):
    """Visit detail page, return (bedrooms, bathrooms, description)."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(1.5)
        soup = BeautifulSoup(page.content(), "html.parser")

        # .unit_inf spans: "N Guests", "N Bedrooms", "N Baths"
        unit_inf = soup.find(class_="unit_inf")
        bedrooms  = None
        bathrooms = None
        if unit_inf:
            for span in unit_inf.find_all("span"):
                t = clean(span.get_text()).lower()
                m = re.match(r"(\d+)\s*bedroom", t)
                if m:
                    bedrooms = int(m.group(1))
                m = re.match(r"(\d+)\s*bath", t)
                if m:
                    bathrooms = int(m.group(1))

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        description = max(paras, key=len, default="")

        return bedrooms, bathrooms, description
    except Exception as e:
        print(f"    ⚠  STR detail failed ({url}): {e}")
        return None, None, ""


def extract_bg_image(style_attr):
    """Pull URL from a background-image: url(...) style string."""
    m = re.search(r'background-image:\s*url\(["\']?(https?://[^"\')\s]+)["\']?\)', style_attr or "")
    return m.group(1) if m else ""


def scrape_str(browser):
    results = []
    seen = set()
    ctx  = browser.new_context(user_agent=USER_AGENT)
    page = ctx.new_page()

    try:
        print(f"\n▶  STR: {STR_BASE}/vacation-rentals")
        page.goto(f"{STR_BASE}/vacation-rentals", timeout=30000, wait_until="networkidle")
        time.sleep(8)  # AngularJS needs extra time
        soup = BeautifulSoup(page.content(), "html.parser")

        # Each card's image link has ng-href and ng-alt (property name)
        img_links = soup.find_all("a", class_="c-property__img-link")
        print(f"   {len(img_links)} STR cards found")

        for img_link in img_links:
            href = img_link.get("ng-href") or img_link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            name  = clean(img_link.get("ng-alt", "") or href.rstrip("/").split("/")[-1])
            image = extract_bg_image(img_link.get("style", ""))

            # Area: .unit_location sibling (within same parent card)
            parent = img_link.parent
            while parent and "panel-image" not in " ".join(parent.get("class", [])):
                parent = parent.parent
            area_el = parent.find(class_="unit_location") if parent else None
            area = clean(area_el.get_text()) if area_el else ""

            # Price: .price-amount.ng-binding + period text
            price_el  = parent.find(class_="price-amount") if parent else None
            period_el = parent.find("span", class_="h6") if parent else None
            price_text  = clean(price_el.get_text())  if price_el  else ""
            period_text = clean(period_el.get_text()) if period_el else "daily"
            price = parse_price(price_text)

            print(f"     → {name[:55]}  ({area}, {price_text} {period_text})")
            bedrooms, bathrooms, description = scrape_str_detail(page, href)
            time.sleep(0.5)

            slug = href.rstrip("/").split("/")[-1] or re.sub(r"[^a-z0-9]+", "-", name.lower())
            results.append({
                "id":           f"ahr-str-{slug}",
                "name":         name,
                "type":         "str",
                "image":        image,
                "area":         area,
                "location":     area,
                "askPrice":     price,
                "pricePeriod":  "nightly",
                "size":         "",
                "buildingSize": "",
                "lotSize":      "",
                "bedrooms":     bedrooms,
                "bathrooms":    bathrooms,
                "agency":       AGENCY,
                "listedDate":   TODAY,
                "sourceUrl":    href,
                "status":       "active",
                "priceHistory": [{"date": TODAY, "price": price}],
                "notes":        description,
            })
    finally:
        ctx.close()

    return results


# ─────────────────────────────────────────────
#  Save to data.rentals
# ─────────────────────────────────────────────

def save(new_rentals):
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current_rentals = existing.get("rentals", [])
    # Keep rentals from other agencies, replace this agency's
    kept    = [r for r in current_rentals if r.get("agency") != AGENCY]
    merged  = kept + new_rentals

    # Preserve user fields (archived, notes overrides) from previous run
    old_by_id = {r["id"]: r for r in current_rentals if r.get("agency") == AGENCY}
    for r in new_rentals:
        old = old_by_id.get(r["id"])
        if old:
            if old.get("archived"):
                r["archived"] = True
            # Preserve user-written notes override if different from scraped
            if old.get("userNotes"):
                r["userNotes"] = old["userNotes"]

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
    print(f"\n✓  Saved {ltr_count} LTR + {str_count} STR rentals ({len(new_rentals)} total) → data.json[\"rentals\"]")
    print(f"   Total rentals in data.json: {len(merged)}")


if __name__ == "__main__":
    print(f"{AGENCY} rental scraper …")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ltr_listings = scrape_ltr(browser)
            str_listings = scrape_str(browser)
        finally:
            browser.close()

    all_rentals = ltr_listings + str_listings
    print(f"\nScraped {len(ltr_listings)} LTR + {len(str_listings)} STR = {len(all_rentals)} total. Saving …")
    save(all_rentals)
