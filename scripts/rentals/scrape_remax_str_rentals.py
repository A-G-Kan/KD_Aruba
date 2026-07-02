#!/usr/bin/env python3
"""
RE/MAX Aruba — short-term / vacation rental scraper (arubaivr.com).
Source: https://www.arubaivr.com/our-rentals ("Aruba Island Vacation Rentals",
RE/MAX's sister brand for vacation rentals)

This is a Wix site whose actual listing grid isn't native Wix content at
all: it's a third-party OwnerRez booking widget loaded in a nested iframe
(Wix page -> a filesusr.com custom-HTML embed -> an app.ownerrez.com/widgets
iframe), and that iframe is lazy-loaded -- it doesn't attach until the page
is scrolled, which is why a plain goto()+wait finds zero listings. Every
step here (scroll to trigger the widget, locate the OwnerRez frame among
several on the page, click its in-frame pagination) exists because of that.

No status/rented signal exists anywhere on the site -- vacation rentals
don't have an LTR-style binary rented/available state, just a day-by-day
booking calendar -- so every listing is written as "active"; that's an
honest reflection of what the source shows, not a fabricated default.

"Area" has no structured field on the detail pages either. The description
text sometimes names a neighbourhood ("the vibrant heart of Oranjestad") and
sometimes doesn't mention one at all, or names a resort/community instead
("exclusive Tierra del Sol Resort") -- inconsistent enough that a generic
"located in X" regex would either miss real matches or grab the wrong noun.
Area is only set when the description text contains one of Aruba's known
neighbourhood names verbatim; otherwise it's left blank rather than guessed.

Writes to data.json["rentals"] — NOT data.json["listings"].

Usage:
    python3 scrape_remax_str_rentals.py

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
from deduplicate import parse_price_robust

AGENCY    = "RE/MAX Aruba"
DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")
TODAY     = date.today().isoformat()
GRID_URL  = "https://www.arubaivr.com/our-rentals"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Known Aruba neighbourhoods/areas -- used only to recognise an unambiguous
# mention in free-text descriptions, never to guess.
KNOWN_AREAS = [
    "Palm Beach", "Eagle Beach", "Malmok", "Noord", "Oranjestad",
    "Savaneta", "San Nicolas", "Santa Cruz", "Paradera", "Tanki Leendert",
    "Pos Chiquito", "Bubali", "Alto Vista", "Seroe Colorado",
    "Tierra del Sol", "Sombre", "Sabana Basora", "Ponton",
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def find_grid_frame(page):
    """The listing grid lives in an OwnerRez widget iframe that's lazy-loaded
    on scroll; there are several OwnerRez iframes on the page (grid, reviews,
    booking form), so this picks out the one that actually has cards."""
    for _ in range(10):
        page.mouse.wheel(0, 800)
        time.sleep(1)
    time.sleep(2)

    for f in page.frames:
        if "ownerrez.com/widgets" not in f.url:
            continue
        try:
            if "Sleeps" in f.content():
                return f
        except Exception:
            continue
    return None


def parse_card(card):
    href = card.get("href", "")

    img_el = card.find("img")
    image  = img_el.get("src", "") if img_el else ""

    name_el = card.find(class_="h3")
    name    = clean(name_el.get_text()) if name_el else "Unknown"

    price_el = card.find(class_="media-heading")   # first match is the price span
    price    = parse_price_robust(price_el.get_text() if price_el else "")

    caption = card.find(class_="caption")
    beds = baths = None
    if caption:
        cap_text = clean(caption.get_text())
        m = re.search(r"(\d+)\s*bedrooms?", cap_text, re.I)
        if m:
            beds = int(m.group(1))
        m = re.search(r"(\d+)\s*baths?", cap_text, re.I)
        if m:
            baths = int(m.group(1))

    return {
        "href":      href,
        "name":      name,
        "image":     image,
        "askPrice":  price,
        "bedrooms":  beds,
        "bathrooms": baths,
    }


def scrape_cards(grid_frame):
    cards = []
    seen_urls = set()

    for page_num in (1, 2, 3):   # 19 listings at 12/page = 2 pages; 3 is a safety margin
        soup = BeautifulSoup(grid_frame.content(), "html.parser")
        tiles = soup.find_all("a", class_="property-result-tile")
        new_count = 0
        for tile in tiles:
            data = parse_card(tile)
            if not data["href"] or data["href"] in seen_urls:
                continue
            seen_urls.add(data["href"])
            cards.append(data)
            new_count += 1

        print(f"   page {page_num}: {new_count} new cards ({len(cards)} total)")

        next_link = grid_frame.locator(f'a.result-page:has-text("{page_num + 1}")')
        if next_link.count() == 0:
            break
        next_link.first.click()
        time.sleep(3)

    return cards


def scrape_detail(page, url):
    """Return (area, description) from a listing detail page."""
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        time.sleep(4)
        soup = BeautifulSoup(page.content(), "html.parser")
        text = soup.get_text(" ", strip=True)

        idx = text.find("Bathrooms")
        desc_body = ""
        if idx >= 0:
            # description runs from just after the specs line to the footer contact block
            after = text[idx:]
            stop = re.search(r"CHECK RATES & BOOK ONLINE|Caya Dr\. J\.E\.M|TERMS & COND", after)
            snippet = after[:stop.start()] if stop else after[:2500]
            desc_body = snippet   # kept unmodified for the area search below

        # Every page on the site -- including this one -- has the agency's
        # own office address ("...Unit 3 Oranjestad, Aruba") in the footer,
        # so searching the whole page for a known area name would just find
        # that on every listing; the area search is scoped to desc_body to
        # avoid that. But a plain "does this known area name appear anywhere
        # in the description" scan is its own trap: descriptions often name
        # a nearby landmark alongside the real location (Island Haven is
        # "located in the heart of Noord, just minutes from ... Palm
        # Beach") and a generic scan can match the landmark instead of the
        # actual location depending on which name happens to appear first.
        # Only the "located in X" / "heart of X" opener -- the phrasing this
        # site consistently uses to actually state the location, not just
        # mention a nearby place -- is trusted; if a description doesn't use
        # it, area is left blank rather than guessed from any area name that
        # happens to appear.
        area = ""
        m = re.search(
            r"(?:located in|nestled in|situated in|in the (?:vibrant |beautiful |exclusive )?heart of)\s+"
            r"(?:the\s+)?([A-Z][A-Za-z\s]+?)(?=[,.]|\s+(?:just|near|within|minutes|Aruba\b))",
            desc_body,
        )
        if m:
            candidate_text = m.group(1).strip()
            for known in KNOWN_AREAS:
                if known.lower() in candidate_text.lower():
                    area = known
                    break

        # drop the leading "Bathrooms N <Name>" specs echo
        desc = clean(re.sub(r"^Bathrooms\s*[\d.]+\s*", "", desc_body))

        return area, desc
    except Exception as e:
        print(f"    ⚠  Detail failed ({url}): {e}")
        return "", ""


def scrape_all():
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1400, "height": 1000})
        page    = ctx.new_page()

        print(f"\n▶  {GRID_URL}")
        page.goto(GRID_URL, timeout=45000, wait_until="domcontentloaded")
        time.sleep(5)

        grid_frame = find_grid_frame(page)
        if not grid_frame:
            print("   ⚠  Could not locate the OwnerRez listing grid frame — aborting.")
            ctx.close()
            browser.close()
            return []

        cards = scrape_cards(grid_frame)
        print(f"   {len(cards)} unique listings found")

        for data in cards:
            price_str = f"${data['askPrice']:,}/night" if data["askPrice"] else "price on request"
            print(f"     → {data['name'][:50]}  |  {price_str}")

            time.sleep(2)
            area, desc = scrape_detail(page, data["href"])

            slug = data["href"].rstrip("/").split("/")[-1]
            listings.append({
                "id":           f"remax-str-{slug}",
                "name":         data["name"],
                "type":         "str",
                "image":        data["image"],
                "area":         area,
                "location":     area,
                "askPrice":     data["askPrice"],
                "pricePeriod":  "nightly",
                "size":         "",
                "buildingSize": "",
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

        ctx.close()
        browser.close()

    return listings


def save(new_rentals):
    existing = {}
    if DATA_JSON.exists():
        with open(DATA_JSON) as f:
            existing = json.load(f)

    current_rentals = existing.get("rentals", [])
    old_agency       = [r for r in current_rentals if r.get("agency") == AGENCY and r.get("id", "").startswith("remax-str-")]
    kept             = [r for r in current_rentals if not (r.get("agency") == AGENCY and r.get("id", "").startswith("remax-str-"))]

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
    print(f"\n✓  Saved {len(new_rentals)} RE/MAX Aruba STR rentals → data.json[\"rentals\"]  (total rentals: {total})")


if __name__ == "__main__":
    print(f"{AGENCY} STR rental scraper (arubaivr.com) …")
    listings = scrape_all()
    if listings:
        print(f"\nScraped {len(listings)} listings. Saving …")
        save(listings)
    else:
        print("\nNo listings scraped — nothing saved.")
