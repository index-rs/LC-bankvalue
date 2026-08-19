#!/usr/bin/env python3
"""
scrape_prices.py — build data/items.json, data/prices.json, data/history.json
from markets.lostcity.rs.

Reads three feeds (~56 requests total for a full market snapshot):
  /sales      completed sales, rolling ~24h   -> real transaction prices
  /?tab=buy   active buy listings             -> best bid (what buyers pay)
  /?tab=sell  active sell listings            -> best ask (what sellers want)

Pricing model (per item, best evidence wins):
  sale  = median of completed coin sales inside a 28-day window
  mid   = (best_bid + best_ask) / 2, from the live order book
  price = 0.75*sale + 0.25*mid when both exist  (sales dominate: they're money
          that changed hands, a listing is only an intention)
        -> a listing >=10x off the sale price is a typo and is dropped outright
        -> else sale, else bid, else ask, else an older "stale" sale,
           else high alch minus a nature rune, else vendor/low-alch (cost * 0.4)

Derived prices fill the long tail: potions per-dose across their dose family,
charged jewellery off its fully-charged variant, splitbark from fine cloth,
noted items from their base item. BUNDLE_CAPS reject set listings posted under
a single item's slug (full rune sets under "rune platebody", etc).

Deep sale history for slow-moving items comes from backfill_history.py.

Usage:
    python scripts/scrape_prices.py
"""

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lc_market as mkt          # noqa: E402
from lc_items import (   # noqa: E402
    BUNDLE_CAPS, CONTAINER_BASE, FINE_CLOTH_SLUG, SPLITBARK_CLOTH,
    VIAL_WATER_SLUG, categorize, is_vendor_default, parse_charges, parse_dose,
    unfinished_potion_herb,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ITEMS_PATH = DATA_DIR / "items.json"
PRICES_PATH = DATA_DIR / "prices.json"
HISTORY_PATH = DATA_DIR / "history.json"
BOOK_PATH = DATA_DIR / "book.json"

COINS_GID = "995"
NATURE_RUNE_GID = "561"
NATURE_RUNE_FALLBACK = 342

HISTORY_DAYS = 28     # rolling window that counts as a current "market" price
HISTORY_KEEP_DAYS = 365   # older sales are kept as a last-resort "stale" price
HISTORY_MAX_PER_ITEM = 24
OUTLIER_LO = 0.2      # drop sales below 0.2x the raw median
OUTLIER_HI = 5.0      # ...and above 5x — kills fat-finger listings without
                      # needing the old scraper's hand-tuned per-item caps

SALE_WEIGHT = 0.75    # completed sales vs. order book, when both exist
ERROR_RATIO = 10.0    # a listing >=10x (or <=1/10) the sale price is a typo,
                      # not a signal — drop it rather than averaging it in


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: could not read {path}: {e}", flush=True)
    return {} if default is None else default


def within_cap(slug, price):
    """Reject a per-unit price that's really a bundle/set sale. See BUNDLE_CAPS."""
    cap = BUNDLE_CAPS.get(slug or "")
    return cap is None or price <= cap


def harvest():
    """Collect the three feeds. Returns (catalog, sales, bids, asks)."""
    catalog, sales, bids, asks = {}, [], {}, {}

    def note_item(item):
        gid = item.get("game_id")
        if gid is None:
            return None
        gid = str(gid)
        catalog[gid] = {
            "slug": item.get("slug"),
            "name": item.get("name"),
            "cost": item.get("cost") or 0,
            "isSet": bool(item.get("isSet")),
        }
        return gid

    print("  fetching completed sales...", flush=True)
    for listing in mkt.walk_feed("/sales", label="sales"):
        item = listing.get("item") or {}
        gid = note_item(item)
        price = mkt.unit_price(listing)
        if gid and price and within_cap(item.get("slug"), price):
            sales.append({
                "gid": gid,
                "price": price,
                "qty": listing.get("quantity") or 1,
                "soldAt": listing.get("soldAt") or listing.get("updatedAt"),
            })

    for tab, bucket, label in (("buy", bids, "buy listings"), ("sell", asks, "sell listings")):
        print(f"  fetching active {label}...", flush=True)
        for listing in mkt.walk_feed(f"/?tab={tab}", label=label):
            item = listing.get("item") or {}
            gid = note_item(item)
            price = mkt.unit_price(listing)
            if gid and price and within_cap(item.get("slug"), price):
                bucket.setdefault(gid, []).append(price)

    return catalog, sales, bids, asks


def merge_history(history, sales):
    """Append new sales, dedupe, prune to the rolling window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_KEEP_DAYS)
    for s in sales:
        history.setdefault(s["gid"], []).append(
            {"price": s["price"], "qty": s["qty"], "soldAt": s["soldAt"]}
        )

    pruned = {}
    for gid, events in history.items():
        seen, keep = set(), []
        for e in events:
            key = (e.get("soldAt"), e.get("price"), e.get("qty"))
            if key in seen:
                continue
            seen.add(key)
            if e.get("soldAt") and parse_ts(e["soldAt"]) and parse_ts(e["soldAt"]) < cutoff:
                continue
            keep.append(e)
        keep.sort(key=lambda e: e.get("soldAt") or "", reverse=True)
        if keep:
            pruned[gid] = keep[:HISTORY_MAX_PER_ITEM]
    return pruned


def parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def split_by_window(events, now):
    """Split an item's sales into (within HISTORY_DAYS, older)."""
    edge = now - timedelta(days=HISTORY_DAYS)
    recent, older = [], []
    for e in events:
        when = parse_ts(e.get("soldAt"))
        (recent if (when is None or when >= edge) else older).append(e)
    return recent, older


def robust_median(values):
    """Median with a light outlier trim. Returns (value, sample_size)."""
    vals = [v for v in values if v and v > 0]
    if not vals:
        return None, 0
    raw = statistics.median(vals)
    trimmed = [v for v in vals if raw * OUTLIER_LO <= v <= raw * OUTLIER_HI] or vals
    return statistics.median(trimmed), len(trimmed)


def price_from_book(bid_list, ask_list):
    """best_bid / best_ask / mid from the active order book."""
    best_bid = max(bid_list) if bid_list else None
    best_ask = min(ask_list) if ask_list else None
    mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else None
    return best_bid, best_ask, mid


def blend(mid, sale_median):
    """Combine order-book mid with completed-sale median.

    Completed sales dominate: they're money that actually changed hands, while a
    listing is only an intention. The book still contributes — it's fresher and
    reflects where the market is heading — but at a quarter of the weight.

    A listing more than ERROR_RATIO away from the sale price is treated as a
    mistake and dropped, not averaged in. These are common and very damaging:
    a seller listing 100 chaos talismans "at 350k" who meant 3.5k each will
    otherwise drag an item to 100x its real value.
    """
    if mid is not None and sale_median is not None:
        if mid > sale_median * ERROR_RATIO or mid < sale_median / ERROR_RATIO:
            return sale_median, "market"
        return sale_median * SALE_WEIGHT + mid * (1 - SALE_WEIGHT), "market"
    if sale_median is not None:
        return sale_median, "market"
    if mid is not None:
        return mid, "market"
    return None, None


def compute_prices(catalog, history, bids, asks, now_iso):
    now = datetime.now(timezone.utc)
    prices = {}
    for gid in set(catalog) | set(history) | set(bids) | set(asks):
        recent, older = split_by_window(history.get(gid, []), now)
        sale_median, sample = robust_median([e["price"] for e in recent])
        stale_median, stale_sample = robust_median([e["price"] for e in older])
        best_bid, best_ask, mid = price_from_book(bids.get(gid, []), asks.get(gid, []))

        # A wildly-out-of-line ask with nothing to check it against is usually a
        # listing typo. If we have *any* sale on record — even an old one — use
        # it as the reality check the recent window couldn't provide.
        reference = sale_median if sale_median is not None else stale_median
        if reference is not None and best_ask and best_ask > reference * ERROR_RATIO:
            best_ask = None
            _, _, mid = price_from_book(bids.get(gid, []), [])

        value, tier = blend(mid, sale_median)

        if value is None and stale_median is not None and not (best_bid or best_ask):
            # Nothing current, but this item has traded before. A real (if old)
            # price beats an alch guess by a mile: body runes sell at 14gp every
            # few weeks, and alch would call them 2gp.
            value, tier = stale_median, "stale"

        if value is None and (best_bid or best_ask):
            # Only one side of the book is quoted. These are NOT equal evidence:
            #   a standing bid is someone offering real coins — a genuine floor.
            #   a standing ask is only what a seller hopes to get, and nothing
            #   stops it being absurd (a chaos talisman listed at 350k when every
            #   other talisman trades under 10k and alch value is 2gp).
            # Keep both, since some items have no better signal, but tier them
            # separately so an asking price is never shown as a market price.
            if best_bid:
                value, tier = best_bid, "bid"
            else:
                value, tier = best_ask, "ask"

        if value is None:
            continue

        entry = {
            "price": max(1, round(value)),
            "tier": tier,
            "sampleSize": sample if tier != "stale" else stale_sample,
            "asOf": now_iso,
        }
        if best_bid:
            entry["bestBid"] = round(best_bid)
        if best_ask:
            entry["bestAsk"] = round(best_ask)
        if sale_median:
            entry["saleMedian"] = round(sale_median)
        if tier == "stale" and older:
            entry["lastSold"] = (older[0].get("soldAt") or "")[:10]
        prices[gid] = entry
    return prices


def apply_splitbark_pricing(catalog, prices, now_iso):
    """Price splitbark from fine cloth (see SPLITBARK_CLOTH in lc_items.py).

    Kept as a fallback rather than an override: where a piece has real repeat
    sales the market wins, but where it barely trades (the helm has no coin
    sales at all) the cloth cost is far closer than an alch value.
    """
    cloth_gid = next((g for g, i in catalog.items() if i.get("slug") == FINE_CLOTH_SLUG), None)
    cloth = prices.get(cloth_gid) if cloth_gid else None
    if not cloth:
        return 0

    filled = 0
    for gid, item in catalog.items():
        pieces = SPLITBARK_CLOTH.get(item.get("slug"))
        if not pieces:
            continue
        existing = prices.get(gid)
        if existing and existing["tier"] == "market" and existing.get("sampleSize", 0) >= 2:
            continue
        prices[gid] = {
            "price": max(1, round(cloth["price"] * pieces)),
            "tier": "cloth",
            "sampleSize": 0,
            "asOf": now_iso,
            "clothPieces": pieces,
            "clothPrice": cloth["price"],
        }
        filled += 1
    return filled


def apply_dose_normalization(catalog, prices, now_iso):
    """Price potions per-dose across their whole dose family.

    A bank holding 1x(4), 100x(3) and 1x(1) of the same potion is really
    holding 104 doses; pricing every variant off a shared per-dose rate is
    both more accurate and fills in variants that never trade on their own.
    The per-dose rate comes from the best-sampled priced variant in the family.
    """
    families = {}
    for gid, item in catalog.items():
        doses, family = parse_dose(item.get("slug"))
        if doses:
            families.setdefault(family, []).append((gid, doses))

    filled = 0
    for family, members in families.items():
        # Pick the variant with the strongest evidence as the per-dose anchor.
        best = None
        for gid, doses in members:
            p = prices.get(gid)
            if not p or p["tier"] not in ("market", "bid", "ask"):
                continue
            score = (p["tier"] == "market", p.get("sampleSize", 0))
            if best is None or score > best[0]:
                best = (score, p["price"] / doses, gid)
        if best is None:
            continue

        per_dose, anchor_gid = best[1], best[2]
        for gid, doses in members:
            existing = prices.get(gid)
            # Don't override a variant that has solid market evidence of its own.
            if existing and existing["tier"] == "market" and existing.get("sampleSize", 0) >= 2:
                continue
            prices[gid] = {
                "price": max(1, round(per_dose * doses)),
                "tier": "dose",
                "sampleSize": 0,
                "asOf": now_iso,
                "doseAnchor": catalog.get(anchor_gid, {}).get("slug"),
                "perDose": round(per_dose, 2),
            }
            if gid != anchor_gid:
                filled += 1
    return filled


def apply_charge_normalization(catalog, prices, now_iso):
    """Price charged jewellery off its family's max-charge variant.

    Only the fully-charged variant trades in volume, so partial ones otherwise
    fall through to alch value and are badly wrong. See CHARGE_FAMILIES in
    lc_items.py for the per-family model ("full" vs "proportional").
    """
    families = {}
    for gid, item in catalog.items():
        charges, family, spec = parse_charges(item.get("slug"))
        if family:
            families.setdefault(family, {"spec": spec, "members": []})
            families[family]["members"].append((gid, charges))

    filled = 0
    for family, info in families.items():
        spec, members = info["spec"], info["members"]
        max_charges = spec["max"]

        # Anchor on the fully-charged variant; if it has no price, scale up from
        # the best-priced partial we do have.
        anchor, anchor_gid = None, None
        for gid, charges in members:
            p = prices.get(gid)
            if not p or p["tier"] not in ("market", "bid", "ask"):
                continue
            if charges == max_charges:
                anchor, anchor_gid = p["price"], gid
                break
            if charges and spec["model"] == "proportional":
                scaled = p["price"] * max_charges / charges
                if anchor is None or scaled > anchor:
                    anchor = scaled
            elif spec["model"] == "full" and (anchor is None or p["price"] > anchor):
                anchor = p["price"]
        if anchor is None:
            continue

        for gid, charges in members:
            # The anchor is the market source — don't relabel it as derived.
            if gid == anchor_gid:
                continue
            existing = prices.get(gid)
            # Keep a variant's own price when it has real completed-sale evidence.
            if existing and existing["tier"] == "market" and existing.get("sampleSize", 0) >= 3:
                continue
            if spec["model"] == "full":
                value = anchor
            else:
                if not charges:
                    continue
                value = anchor * charges / max_charges
            prices[gid] = {
                "price": max(1, round(value)),
                "tier": "charge",
                "sampleSize": 0,
                "asOf": now_iso,
                "chargeModel": spec["model"],
                "chargeAnchor": f"{family}_{max_charges}",
            }
            filled += 1
    return filled


def apply_variant_pricing(catalog, prices, now_iso):
    """Poisoned weapons and dragon leather take their base item's price.

    They barely trade on their own — a rune arrow(p) is worth a rune arrow, and
    dragon leather is tanned hide of the same colour. The report also folds
    them into the base row, so this keeps price and display consistent.
    """
    filled = 0
    for gid, item in catalog.items():
        base = item.get("pricedAs")
        if not base:
            continue
        base_price = prices.get(base)
        if not base_price:
            continue
        # Always override. A poisoned dart's own listing is noise — they aren't
        # actively sold, so whatever quote exists is worse than the base price.
        prices[gid] = {
            "price": base_price["price"],
            "tier": base_price["tier"],
            "sampleSize": base_price.get("sampleSize", 0),
            "asOf": now_iso,
            "variantOf": base,
        }
        filled += 1
    return filled


def apply_unfinished_potion_pricing(catalog, prices, now_iso):
    """An unfinished potion is its herb plus a vial of water.

    Both components trade actively, so this is a real derived price rather than
    a guess — and unfinished potions themselves almost never sell.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    vial_gid = by_slug.get(VIAL_WATER_SLUG)
    vial_price = (prices.get(vial_gid) or {}).get("price", 0) if vial_gid else 0

    filled = 0
    for gid, item in catalog.items():
        herb_slug = unfinished_potion_herb(item.get("slug"))
        if not herb_slug:
            continue
        existing = prices.get(gid)
        if existing and existing["tier"] == "market" and existing.get("sampleSize", 0) >= 2:
            continue
        herb_gid = by_slug.get(herb_slug)
        herb_price = (prices.get(herb_gid) or {}).get("price") if herb_gid else None
        if not herb_price:
            continue
        prices[gid] = {
            "price": max(1, round(herb_price + vial_price)),
            "tier": "unfinished",
            "sampleSize": 0,
            "asOf": now_iso,
            "fromHerb": herb_slug,
        }
        filled += 1
    return filled


def apply_junk_zeroing(catalog, prices, now_iso):
    """Junk is worth 0 by fiat — vendor tools and clothing nobody trades."""
    zeroed = 0
    for gid, item in catalog.items():
        if item.get("category") != "junk":
            continue
        prices[gid] = {"price": 0, "tier": "junk", "sampleSize": 0, "asOf": now_iso}
        zeroed += 1
    return zeroed


def apply_container_pricing(catalog, prices, now_iso):
    """A bucket of water is a bucket someone filled; price it as the empty one."""
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    filled = 0
    for slug, base_slug in CONTAINER_BASE.items():
        gid, base_gid = by_slug.get(slug), by_slug.get(base_slug)
        if not gid or not base_gid or base_gid not in prices:
            continue
        base = prices[base_gid]
        prices[gid] = {
            "price": base["price"], "tier": base["tier"],
            "sampleSize": base.get("sampleSize", 0), "asOf": now_iso,
            "containerOf": base_gid,
        }
        filled += 1
    return filled


def apply_vendor_defaults(catalog, prices, now_iso):
    """Force low-alch pricing on items nobody trades in bulk.

    A stray ask on a silver sickle or a javelin says nothing about what it's
    worth; the shop price does. See VENDOR_DEFAULT_SLUGS in lc_items.py.
    """
    forced = 0
    for gid, item in catalog.items():
        if not is_vendor_default(item.get("slug")) or not item.get("tradeable", True):
            continue
        cost = item.get("cost") or 0
        prices[gid] = {
            "price": max(1, round(cost * 0.4)), "tier": "vendor",
            "sampleSize": 0, "asOf": now_iso,
        }
        forced += 1
    return forced


def apply_noted_pricing(catalog, prices, now_iso):
    """Noted (cert_x) items are worth exactly what their base item is worth."""
    filled = 0
    for gid, item in catalog.items():
        base = item.get("notedOf")
        if not base:
            continue
        base_price = prices.get(base)
        if not base_price:
            continue
        # Always override: a noted item IS its base item, so any fallback that
        # landed on it earlier is strictly worse than the base's final price.
        prices[gid] = {
            "price": base_price["price"],
            "tier": base_price["tier"],
            "sampleSize": base_price.get("sampleSize", 0),
            "asOf": now_iso,
            "notedFrom": base,
        }
        filled += 1
    return filled


def apply_alch_fallback(catalog, prices, now_iso):
    """Last-resort pricing for tradeable non-rare items with no market data.

    Multipliers are taken from the game's own spell scripts (Content 274,
    scripts/skill_magic): high alchemy pays `scale(6, 10, oc_cost)` and low
    alchemy `scale(4, 10, oc_cost)` — 60% and 40% of cost, each with a floor
    of 1gp.

    Two rungs:
      "alch"   high alch minus the nature rune it costs to cast. This is what
               you'd actually net turning the item into coins.
      "vendor" when that nets zero or less, the item is worth less than the
               rune needed to alch it, so nobody alchs it. What it's really
               worth is what a shop pays: low alch value, 40% of cost.

    Two deliberate exclusions:
      * Untradeable items get no price entry at all — the report shows them as
        untradeable rather than "no data", which is a real answer, not a gap.
      * Rares are never estimated this way. Their value is collector-driven and
        completely decoupled from `cost` (a half full wine jug has cost=1 but
        trades for millions), so a guess would be off by orders of magnitude.
    """
    nature = (prices.get(NATURE_RUNE_GID) or {}).get("price", NATURE_RUNE_FALLBACK)
    alch_filled = vendor_filled = 0

    for gid, item in catalog.items():
        if gid in prices or not item.get("tradeable", True) or item.get("rare"):
            continue
        # Noted items and poison/leather variants mirror a base item's price,
        # which is resolved after this pass — don't let a guess claim them first.
        if item.get("notedOf") or item.get("pricedAs"):
            continue
        cost = item.get("cost") or 0
        if cost <= 0:
            continue

        net_alch = max(1, round(cost * 0.6)) - nature
        if net_alch > 0:
            prices[gid] = {"price": net_alch, "tier": "alch",
                           "sampleSize": 0, "asOf": now_iso}
            alch_filled += 1
        else:
            prices[gid] = {"price": max(1, round(cost * 0.4)), "tier": "vendor",
                           "sampleSize": 0, "asOf": now_iso}
            vendor_filled += 1

    return alch_filled, vendor_filled


def main():
    DATA_DIR.mkdir(exist_ok=True)
    items_db = load_json(ITEMS_PATH)
    history = load_json(HISTORY_PATH)

    print(f"scraping {mkt.BASE} ...", flush=True)
    catalog, sales, bids, asks = harvest()
    print(f"\n  {len(catalog)} distinct items seen, {len(sales)} coin sales, "
          f"{len(bids)} items bid, {len(asks)} items asked", flush=True)

    if not items_db:
        print("\nERROR: data/items.json is missing or empty.", flush=True)
        print("Run  python scripts/build_catalog.py  first — it builds the", flush=True)
        print("authoritative item catalog from Lost City's Content repo.", flush=True)
        sys.exit(1)

    # The catalog (build_catalog.py) owns slug/name/cost/tradeable/rare/notedOf.
    # Only fill gaps here — never clobber it with market-feed guesses.
    added, synthetic = 0, 0
    for gid, item in catalog.items():
        if gid in items_db:
            continue
        # The Markets site mints synthetic "set" items (armour bundles) with
        # game_id >= 1_000_000. They don't exist in the game, so they can never
        # appear in a .sav bank — keep them out of the catalog entirely.
        if int(gid) >= 1_000_000:
            synthetic += 1
            continue
        items_db[gid] = {
            "slug": item["slug"],
            "name": item["name"],
            "cost": item["cost"],
            "category": categorize(item["slug"], item["name"], item["isSet"]),
            "tradeable": True,
        }
        added += 1
    if added:
        print(f"  note: {added} real item(s) on the market but absent from the "
              f"catalog — content update? re-run build_catalog.py", flush=True)
    if synthetic:
        print(f"  ({synthetic} synthetic market-only set bundles ignored)", flush=True)

    # Re-derive categories — categorize() is a pure function of slug/name, so a
    # rules change must propagate to the whole catalog, not just today's traders.
    for item in items_db.values():
        item["category"] = categorize(item.get("slug", ""), item.get("name", ""), False)

    # Standing offers captured by backfill_history.py, for items the paginated
    # buy/sell feeds don't reach. Live feed data always wins.
    book = load_json(BOOK_PATH)
    for gid, sides in book.items():
        if gid not in bids and sides.get("bids"):
            bids[gid] = sides["bids"]
        if gid not in asks and sides.get("asks"):
            asks[gid] = sides["asks"]

    history = merge_history(history, sales)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    prices = compute_prices(items_db, history, bids, asks, now_iso)
    dose_filled = apply_dose_normalization(items_db, prices, now_iso)
    charge_filled = apply_charge_normalization(items_db, prices, now_iso)
    cloth_filled = apply_splitbark_pricing(items_db, prices, now_iso)
    unf_filled = apply_unfinished_potion_pricing(items_db, prices, now_iso)
    alch_filled, vendor_filled = apply_alch_fallback(items_db, prices, now_iso)
    junk_zeroed = apply_junk_zeroing(items_db, prices, now_iso)
    vendor_forced = apply_vendor_defaults(items_db, prices, now_iso)
    container_filled = apply_container_pricing(items_db, prices, now_iso)
    # Variants and notes resolve LAST: they mirror a base item's final price,
    # so every fallback must already have been applied to that base.
    variant_filled = apply_variant_pricing(items_db, prices, now_iso)
    noted_filled = apply_noted_pricing(items_db, prices, now_iso)

    # Coins are exactly 1gp — never rely on seeing a coins-for-coins listing.
    items_db[COINS_GID] = {"slug": "coins", "name": "Coins", "cost": 1,
                           "category": "coins", "tradeable": True}
    prices[COINS_GID] = {"price": 1, "tier": "market", "sampleSize": 0, "asOf": now_iso}

    by_tier = {}
    for p in prices.values():
        by_tier[p["tier"]] = by_tier.get(p["tier"], 0) + 1

    untradeable = sum(1 for i in items_db.values() if not i.get("tradeable", True))
    print(f"\nDone: {len(items_db)} known items, {len(prices)} priced "
          f"({untradeable} untradeable, deliberately unpriced)", flush=True)
    for tier in sorted(by_tier):
        print(f"    {tier:<10} {by_tier[tier]}", flush=True)
    print(f"  ({dose_filled} by dose, {charge_filled} by charges, {cloth_filled} by cloth, "
          f"{unf_filled} unfinished, {variant_filled} variants, {noted_filled} noted, "
          f"{alch_filled} alch, {vendor_filled}+{vendor_forced} vendor, "
          f"{container_filled} containers, {junk_zeroed} junk)", flush=True)

    ITEMS_PATH.write_text(json.dumps(items_db, indent=2, sort_keys=True), encoding="utf-8")
    PRICES_PATH.write_text(json.dumps(prices, indent=2, sort_keys=True), encoding="utf-8")
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")
    for p in (ITEMS_PATH, PRICES_PATH, HISTORY_PATH):
        print(f"wrote {p}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\nFATAL ERROR: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
