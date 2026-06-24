#!/usr/bin/env python3
"""
Property listing deduplication — two-layer system.

Layer 1 — within-site:
    Call dedup_within_site(listings, agency) before saving any scraper's results.
    Removes listings that share the same URL or the same (location, price, size) fingerprint.

Layer 2 — cross-site:
    Run this file directly, or call run_cross_site_dedup(), after all scrapers have run.
    Merges listings from DIFFERENT agencies that match on location + price (±5%) + size (±10%).
    Merged listings keep a `realtors` list recording every agency co-listing the property.

Usage (cross-site pass):
    cd Website/scripts && python3 deduplicate.py
"""

import re
import json
import sys
from pathlib import Path
from collections import Counter

DATA_JSON = Path("/Users/alan/Desktop/KD/Website/data.json")


# ── shared price parsing ────────────────────────────────────────────────────

AWG_TO_USD = 1.79  # fixed peg: 1 USD = 1.79 AWG


def _parse_numeric(raw: str):
    """Detect US ($1,234,567) vs Dutch ($1.234.567,00) number format → int."""
    raw = (raw or "").strip().rstrip(".,")
    if not raw:
        return None
    # Dutch decimal: comma + 1-2 digits at end, with dot thousands
    if re.search(r",\d{1,2}$", raw) and "." in raw:
        integer_part = raw.rsplit(",", 1)[0].replace(".", "")
        return int(integer_part) if integer_part.isdigit() else None
    # US decimal: dot + 2 digits at end, with comma thousands
    if re.search(r"\.\d{2}$", raw) and "," in raw:
        integer_part = raw.rsplit(".", 1)[0].replace(",", "")
        return int(integer_part) if integer_part.isdigit() else None
    # Dutch thousands: multiple dots, no comma (1.234.567)
    if raw.count(".") >= 2:
        clean = raw.replace(".", "")
        return int(clean) if clean.isdigit() else None
    # Dutch thousands: single dot + exactly 3 trailing digits (944.000)
    if re.search(r"\.\d{3}$", raw) and "," not in raw:
        clean = raw.replace(".", "")
        return int(clean) if clean.isdigit() else None
    # US thousands: commas only (1,234,567)
    if "," in raw:
        clean = raw.replace(",", "")
        return int(clean) if clean.isdigit() else None
    # Plain digits or single-dot decimal
    try:
        return int(float(raw)) if raw else None
    except ValueError:
        return None


def parse_price_robust(text: str, prefer_usd: bool = True):
    """
    Extract a price from text and return an integer USD value.

    Handles both US ($1,234,567) and Dutch/European ($1.234.567,00) number
    formats. When prefer_usd=True (default), tries $ / USD / US$ first, then
    AWG / Afl as a fallback (converting to USD at the fixed 1 USD = 1.79 AWG
    rate). When prefer_usd=False, tries AWG/Afl first and returns the raw AWG
    integer without conversion, falling back to USD.
    """
    text = (text or "").strip()
    if re.search(r"price\s*(upon|on)\s*request|upon\s*request|on\s*request",
                 text, re.I):
        return None

    if prefer_usd:
        m = re.search(r"(?:US\$|USD|\$)\s*([\d.,]+)", text)
        if m:
            return _parse_numeric(m.group(1))
        m = re.search(r"(?:AWG|Afl\.?)\s*([\d.,]+)", text)
        if m:
            awg = _parse_numeric(m.group(1))
            return round(awg / AWG_TO_USD) if awg else None
    else:
        m = re.search(r"(?:AWG|Afl\.?)\s*([\d.,]+)", text)
        if m:
            return _parse_numeric(m.group(1))
        m = re.search(r"(?:US\$|USD|\$)\s*([\d.,]+)", text)
        if m:
            return _parse_numeric(m.group(1))
    return None


# ── normalisation helpers ────────────────────────────────────────────────────

def _norm_loc(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = (text or "").lower()
    text = re.sub(r"[,./\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _size_m2(size_text: str):
    """
    Extract a numeric size value. Converts sq ft → m² so both units compare
    on the same scale. Returns None when the string carries no numeric value.
    """
    if not size_text:
        return None
    text = (size_text or "").lower()
    m = re.search(r"([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    if re.search(r"sq\.?\s*ft|sqft", text):
        val *= 0.0929          # sq ft → m²
    return val


def _loc_match(a: str, b: str) -> bool:
    """
    True when two normalised location strings plausibly refer to the same
    physical place.  Checks exact match, substring containment, and a
    Jaccard word-overlap threshold of 50%.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    wa = {w for w in a.split() if len(w) > 2}
    wb = {w for w in b.split() if len(w) > 2}
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.5


# ── Layer 1: within-site deduplication ──────────────────────────────────────

def dedup_within_site(listings: list, agency_name: str = "") -> tuple:
    """
    Remove duplicate entries from a single scraper's result list.

    Pass 1 — URL dedup:
        Exact URL match (trailing slash stripped, lowercased).

    Pass 2 — fingerprint dedup (catches same property listed twice under
    different URLs, e.g. 'featured' + 'for-sale' category overlap):
        Key = (normalised_location, askPrice, size_bucket_10m²).
        Only applied when both location and price are present.

    Logs removed count with site label.
    Returns (deduped_list, removed_count).
    """
    seen_urls = set()
    seen_fps  = set()
    deduped   = []
    removed   = 0

    for listing in listings:
        url = (listing.get("sourceUrl") or "").rstrip("/").lower()

        # Pass 1: URL
        if url:
            if url in seen_urls:
                removed += 1
                continue
            seen_urls.add(url)

        # Pass 2: fingerprint
        loc   = _norm_loc(listing.get("location") or listing.get("area") or "")
        price = listing.get("askPrice") or 0
        size  = _size_m2(listing.get("size") or "")

        if loc and price:
            bucket = round(size / 10) * 10 if size else None   # 10 m² bucket
            fp = (loc, price, bucket)
            if fp in seen_fps:
                removed += 1
                continue
            seen_fps.add(fp)

        deduped.append(listing)

    if removed > 0:
        tag = f"[{agency_name}] " if agency_name else ""
        print(f"  ↳ {tag}within-site dedup: removed {removed} duplicate(s) "
              f"({len(listings)} → {len(deduped)})")

    return deduped, removed


# ── Layer 2: cross-site deduplication ───────────────────────────────────────

def dedup_cross_site(listings: list) -> tuple:
    """
    Merge listings from DIFFERENT agencies that represent the same physical
    property.

    Match criteria (ALL must hold):
      • Location strings are similar (≥50% Jaccard word overlap or substring)
      • askPrice within ±5%
      • Size within ±10%  (only checked when BOTH listings carry size data)

    Same-agency listings are never merged (a site occasionally lists the same
    property in multiple categories — that's the within-site layer's job).

    Merge behaviour:
      • The listing with more populated fields is kept as the primary record.
      • A `realtors` list is written on the primary: one entry per agency
        with {agency, sourceUrl}.
      • Missing fields (image, notes, bedrooms, bathrooms, size) are filled
        from the secondary when the primary lacks them.

    Resets any `realtors` fields left over from a previous run before starting,
    so results are always fresh.

    Returns (merged_list, merge_count).
    """
    n = len(listings)

    # Reset stale realtors from any prior run
    for l in listings:
        l.pop("realtors", None)

    keep   = [True] * n
    merges = 0

    for i in range(n):
        if not keep[i]:
            continue
        a       = listings[i]
        a_price = a.get("askPrice")
        a_loc   = _norm_loc(a.get("location") or a.get("area") or "")
        a_size  = _size_m2(a.get("size") or "")

        if not a_price or not a_loc:
            continue

        for j in range(i + 1, n):
            if not keep[j]:
                continue
            b = listings[j]

            # Never merge within same agency
            if a.get("agency") == b.get("agency"):
                continue

            b_price = b.get("askPrice")
            b_loc   = _norm_loc(b.get("location") or b.get("area") or "")

            if not b_price or not b_loc:
                continue

            # Price within 5%
            if abs(a_price - b_price) / max(a_price, b_price) > 0.05:
                continue

            # Location similarity
            if not _loc_match(a_loc, b_loc):
                continue

            # Size within 10% (when both available)
            b_size = _size_m2(b.get("size") or "")
            if a_size and b_size:
                if abs(a_size - b_size) / max(a_size, b_size) > 0.10:
                    continue

            # ── Match found ──────────────────────────────────────
            # Always keep listing[i] as primary. Fill any fields it is
            # missing from the secondary (b) so we keep the richer data.
            if "realtors" not in a:
                a["realtors"] = [
                    {"agency": a.get("agency", ""), "sourceUrl": a.get("sourceUrl", "")}
                ]

            b_agency = b.get("agency", "")
            # Only add each agency once even if it has multiple duplicate listings
            if not any(r["agency"] == b_agency for r in a["realtors"]):
                a["realtors"].append(
                    {"agency": b_agency, "sourceUrl": b.get("sourceUrl", "")}
                )

            for field in ("image", "notes", "bedrooms", "bathrooms", "size"):
                if not a.get(field) and b.get(field):
                    a[field] = b[field]

            keep[j] = False
            merges += 1

    return [l for idx, l in enumerate(listings) if keep[idx]], merges


# ── Standalone runner ────────────────────────────────────────────────────────

def run_cross_site_dedup(data_json: Path = DATA_JSON) -> int:
    """
    Load data.json, run a full two-pass dedup across ALL listings, save back.

    Pass 1 — within-site pre-clean:
        Groups existing listings by agency and runs dedup_within_site on each
        group.  This catches any leftover duplicates in data.json from previous
        scraper runs that predated this dedup system.

    Pass 2 — cross-site:
        Merges listings from different agencies that represent the same property.

    Prints per-agency counts before and after, total merges for both passes,
    and a list of every co-listed property with its agencies.

    Returns total cross-site merges performed.
    """
    if not data_json.exists():
        print(f"[dedup] data.json not found at {data_json}")
        return 0

    with open(data_json) as f:
        data = json.load(f)

    listings = data.get("listings", [])
    before   = len(listings)

    counts_before = Counter(l.get("agency", "?") for l in listings)
    print(f"\n{'─'*54}")
    print(f"  Cross-site dedup — {before} listings across "
          f"{len(counts_before)} agencies")
    print(f"{'─'*54}")
    for agency in sorted(counts_before):
        print(f"  {'before':6}  {counts_before[agency]:>4}  {agency}")

    # ── Pass 1: within-site pre-clean ─────────────────────────────────────
    from collections import defaultdict
    by_agency: dict = defaultdict(list)
    for l in listings:
        by_agency[l.get("agency", "?")].append(l)

    cleaned: list = []
    total_within_removed = 0
    for agency in sorted(by_agency):
        deduped, removed = dedup_within_site(by_agency[agency], agency)
        cleaned.extend(deduped)
        total_within_removed += removed

    if total_within_removed:
        print(f"\n  Pass 1 (within-site): removed {total_within_removed} "
              f"duplicate(s) from existing data ({before} → {len(cleaned)})")
    else:
        print(f"\n  Pass 1 (within-site): no duplicates found in existing data")

    listings = cleaned

    # ── Pass 2: cross-site ────────────────────────────────────────────────
    merged_list, merges = dedup_cross_site(listings)
    after = len(merged_list)

    counts_after = Counter(l.get("agency", "?") for l in merged_list)

    print(f"\n  Pass 2 (cross-site): {merges} duplicate(s) merged across agencies")
    print(f"  Total: {before} → {after} listings  "
          f"(−{total_within_removed} within-site, −{merges} cross-site)")
    print()
    for agency in sorted(counts_after):
        delta = counts_before[agency] - counts_after[agency]
        tag   = f"  (−{delta} merged away)" if delta else ""
        print(f"  {'after':6}  {counts_after[agency]:>4}  {agency}{tag}")

    co_listed = [l for l in merged_list if len(l.get("realtors", [])) > 1]
    if co_listed:
        print(f"\n  {len(co_listed)} co-listed propert{'ies' if len(co_listed) != 1 else 'y'}:")
        for l in co_listed:
            agencies = "  +  ".join(r["agency"] for r in l["realtors"])
            name = (l.get("name") or "?")[:45]
            price = f"${l['askPrice']:,}" if l.get("askPrice") else "n/a"
            print(f"    • {name:<45}  {price}  [{agencies}]")
    else:
        print("\n  No co-listed properties found.")

    data["listings"] = merged_list
    with open(data_json, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✓  Saved to {data_json}")
    return merges


if __name__ == "__main__":
    run_cross_site_dedup()
