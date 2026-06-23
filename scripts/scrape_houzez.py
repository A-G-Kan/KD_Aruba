#!/usr/bin/env python3
"""
Shared Houzez-theme scraper helper.
Imported by scrape_hkg_realestate.py, scrape_jz_realty.py,
scrape_arubapalms.py, scrape_res_aruba.py.

DO NOT run this file directly.
"""

import json, re, time, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deduplicate import dedup_within_site

DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()

HOUZEZ_STATUS_MAP = {
    "for sale":      "active",
    "sold":          "sold",
    "under offer":   "under offer",
    "under contract":"under offer",
    "price reduced": "price reduced",
    "on hold":       "on hold",
    "rented":        "sold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    text = text or ""
    m = re.search(r"\$\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"([\d.]+)\s*(?:AWG|Afl)", text)
    if m:
        return int(float(m.group(1).replace(".", "").replace(",", ""))) if m else None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits and len(digits) > 3 else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_houzez_card(card):
    # Image from data-images JSON attribute
    data_images_raw = card.get("data-images", "[]")
    try:
        images = json.loads(data_images_raw)
        image_url = images[0]["image"] if images else ""
    except Exception:
        image_url = ""

    # Fallback image from img tag
    if not image_url:
        img = card.find("img")
        image_url = (img.get("src") or img.get("data-src") or "") if img else ""

    # Title and link
    title_el = card.find(class_="item-title") or card.find("h2") or card.find("h3")
    link_el  = title_el.find("a") if title_el else card.find("a", href=True)
    name = clean(link_el.get_text()) if link_el else "Unknown"
    href = link_el["href"] if link_el else ""

    # Price
    price_el  = card.find(class_="item-price")
    price_span = price_el.find(class_="price") if price_el else None
    price = parse_price((price_span or price_el).get_text() if (price_span or price_el) else "")

    # Beds / baths
    beds_el  = card.find(class_="h-beds")
    baths_el = card.find(class_="h-baths")
    beds  = parse_int(beds_el.get_text()  if beds_el  else "")
    baths = parse_int(baths_el.get_text() if baths_el else "")

    # Size
    size_el = card.find(class_=re.compile(r"h-area|item-area|h-size", re.I))
    size    = clean(size_el.get_text()) if size_el else ""

    # Location
    addr_el  = card.find(class_="item-address")
    location = clean(addr_el.get_text()) if addr_el else ""

    # Status from label (first one that isn't "For Sale" is a modifier)
    status = "active"
    for label in card.find_all(class_="label-status"):
        st = clean(label.get_text()).lower()
        if st and st != "for sale":
            status = HOUZEZ_STATUS_MAP.get(st, "active")
            break
    # If first label says sold/under offer etc. catch that too
    first_label = card.find(class_="label-status")
    if first_label:
        st = clean(first_label.get_text()).lower()
        if st in HOUZEZ_STATUS_MAP:
            status = HOUZEZ_STATUS_MAP[st]

    return {
        "name":      name,
        "href":      href,
        "image":     image_url,
        "location":  location,
        "area":      location.split(",")[0].strip() if "," in location else location,
        "askPrice":  price,
        "size":      size,
        "bedrooms":  beds,
        "bathrooms": baths,
        "status":    status,
    }


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = page.content()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(soup, "html.parser")
        text = soup.get_text(" ", strip=True)

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return ""


def scrape_houzez_site(browser, base_url, agency, listing_pages, user_agent, seen_urls):
    from bs4 import BeautifulSoup

    results = []
    for url, listing_type in listing_pages:
        ctx  = browser.new_context(user_agent=user_agent)
        page = ctx.new_page()
        try:
            print(f"\n▶  {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            soup  = BeautifulSoup(page.content(), "html.parser")
            cards = soup.find_all(class_="item-listing-wrap")
            print(f"   {len(cards)} cards")

            for card in cards:
                data = parse_houzez_card(card)
                href = data["href"]
                if not href or href in seen_urls:
                    continue
                # Skip rental listings
                if "/for-rent/" in href or "/rental/" in href:
                    continue
                seen_urls.add(href)

                print(f"     → {data['name'][:50]}")
                desc = scrape_detail(page, href)
                time.sleep(0.4)

                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":           slug,
                    "name":         data["name"],
                    "type":         listing_type,
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     data["askPrice"],
                    "size":         data["size"],
                    "bedrooms":     data["bedrooms"],
                    "bathrooms":    data["bathrooms"],
                    "agency":       agency,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": data["askPrice"]}],
                    "notes":        desc,
                })
        finally:
            ctx.close()
        time.sleep(2)

    return results


def save_houzez(new_listings, agency):
    new_listings, _ = dedup_within_site(new_listings, agency)
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    kept    = [l for l in current if l.get("agency") != agency]
    merged  = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       TODAY,
        "agentActive":    True,
        "totalSyncCount": existing.get("agentMeta", {}).get("totalSyncCount", 0) + 1,
    }

    with open(DATA_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved {len(new_listings)} {agency} listings → {DATA_JSON} ({len(merged)} total)")
