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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Library/Python/3.9/lib/python/site-packages"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BASE_URL   = "https://ajrealestatearuba.com"
AGENCY     = "AJ Real Estate Aruba"
DATA_JSON  = Path("/Users/alan/Desktop/KD/Website/data.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TODAY = date.today().isoformat()

SEARCH_SECTIONS = [
    ("/property-type/house-for-sale/",       "house"),
    ("/property-type/condominium-for-sale/", "condo"),
    ("/property-type/land-for-sale/",        "land"),
    ("/property-type/commercial-for-sale/",  "commercial"),
]

AJ_STATUS_MAP = {
    "sold":          "sold",
    "under offer":   "under offer",
    "under contract":"under offer",
    "price reduced": "price reduced",
    "on hold":       "on hold",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_price(text):
    text = text or ""
    # AWG format: AWG1,700,000.00 or $944.000,00
    m = re.search(r"AWG\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"\$\s*([\d.,]+)", text)
    if m:
        raw = m.group(1).replace(",", "").replace(".", "")
        return int(raw) if raw.isdigit() else None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits and len(digits) > 3 else None


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_card(article):
    link_el = article.find("a")
    href    = link_el["href"] if link_el else ""
    if href and not href.startswith("http"):
        href = BASE_URL + href

    img_el = article.find("img")
    image  = img_el.get("src") or img_el.get("data-src") or "" if img_el else ""

    # Title: h2 or h3 inside article
    h = article.find(["h2", "h3"])
    name = clean(h.get_text()) if h else clean(link_el.get_text()) if link_el else "Unknown"

    # Price: look for AWG or $ amounts
    price_el = article.find(class_=re.compile(r"price", re.I))
    price = parse_price(price_el.get_text() if price_el else "")
    if not price:
        price = parse_price(article.get_text())

    # Beds / baths
    text = article.get_text(" ")
    beds = parse_int(re.search(r"(\d+)\s*[Bb]edroom", text).group(1) if re.search(r"(\d+)\s*[Bb]edroom", text) else "")
    baths = parse_int(re.search(r"(\d+)\s*[Bb]athroom", text).group(1) if re.search(r"(\d+)\s*[Bb]athroom", text) else "")

    # Location from class names: mh-attribute-city__noord → Noord
    location = ""
    for cls in article.get("class", []):
        m = re.match(r"mh-attribute-city__(.+)", cls)
        if m:
            location = m.group(1).replace("-", " ").title()
            break

    # Size
    size_el = article.find(class_=re.compile(r"size|area|sqft|sqm", re.I))
    size    = clean(size_el.get_text()) if size_el else ""

    # Status
    status = "active"
    status_el = article.find(class_=re.compile(r"label|badge|tag|status", re.I))
    if status_el:
        st = clean(status_el.get_text()).lower()
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


def scrape_detail(page, url):
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(0.8)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        price = parse_price(re.search(r"(AWG\s*[\d,]+|\$\s*[\d,.]+)", text).group(0) if re.search(r"(AWG\s*[\d,]+|\$\s*[\d,.]+)", text) else "")

        beds = baths = None
        m = re.search(r"(\d+)\s*[Bb]edroom", text)
        if m: beds = int(m.group(1))
        m = re.search(r"(\d+)\s*[Bb]athroom", text)
        if m: baths = int(m.group(1))

        size = ""
        m = re.search(r"([\d,.]+)\s*(m²|m2|sqm|sq\.?\s*ft)", text, re.I)
        if m: size = m.group(0).strip()

        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
        desc = max(paras, key=len, default="")

        return price, beds, baths, size, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return None, None, None, "", ""


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

            soup = BeautifulSoup(page.content(), "html.parser")
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
                price, beds, baths, size, desc = scrape_detail(page, href)
                time.sleep(0.4)

                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":           slug,
                    "name":         data["name"],
                    "type":         listing_type,
                    "image":        data["image"],
                    "area":         data["area"],
                    "location":     data["location"],
                    "askPrice":     price or data["askPrice"],
                    "size":         size or data["size"],
                    "bedrooms":     beds or data["bedrooms"],
                    "bathrooms":    baths or data["bathrooms"],
                    "agency":       AGENCY,
                    "listedDate":   TODAY,
                    "sourceUrl":    href,
                    "status":       data["status"],
                    "priceHistory": [{"date": TODAY, "price": price or data["askPrice"]}],
                    "notes":        desc,
                })

            # Check for next page
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
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current = existing.get("listings", [])
    kept    = [l for l in current if l.get("agency") != AGENCY]
    merged  = kept + new_listings

    existing["listings"] = merged
    existing["agentMeta"] = {
        "lastSync":       TODAY,
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
