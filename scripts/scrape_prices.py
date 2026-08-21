#!/usr/bin/env python3
"""
scrape_prices.py — build data/items.json, data/prices.json, data/history.json
from markets.lostcity.rs.

Reads three feeds (~56 requests total for a full market snapshot):
  /sales      completed sales, rolling ~24h   -> real transaction prices
  /?tab=buy   active buy listings             -> best bid (what buyers pay)
  /?tab=sell  active sell listings            -> best ask (what sellers want)

Pricing model (per item, best evidence wins):
  sale  = quantity-weighted median of completed coin sales in a 60-day window
  mid   = (best_bid + best_ask) / 2, from the live order book
  price = 0.75*sale + 0.25*mid when both exist  (sales dominate: they're money
          that changed hands, a listing is only an intention)
        -> a listing >=10x off the sale price is a typo and is dropped outright
        -> else sale, else bid, else ask, else an older "stale" sale,
           else high alch minus a nature rune, else vendor/low-alch (cost * 0.4)

Derived prices fill the long tail: potions per-dose off their family's 3-dose variant,
charged jewellery off its fully-charged variant, splitbark from fine cloth,
noted items from their base item. BUNDLE_CAPS reject set listings posted under
a single item's slug (full rune sets under "rune platebody", etc), and plain
gem jewellery is capped at its enchanted form's price (ENCHANT_PRODUCT).
FIXED_PRICES hand-sets the few items no rule reads correctly (cannon parts,
soul runes) and overrides everything else. MATERIAL_RECIPES prices an item from
what it's made of, and BULK_UNSELLABLE discounts the handful that only ever
trade one at a time.

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
    BULK_DISCOUNT, BULK_UNSELLABLE, BUNDLE_CAPS, ENCHANT_PRODUCT,
    FINE_CLOTH_SLUG, FIXED_PRICES, MATERIAL_RECIPES, SAME_AS_BASE,
    SPLITBARK_CLOTH, UNID_HERB, VIAL_WATER_SLUG, categorize, is_alch_default,
    is_vendor_default, parse_charges, parse_dose, unfinished_potion_herb,
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

HISTORY_DAYS = 60     # rolling window that counts as a current "market" price.
                      # Two months, not one: most of this catalog is thin, and
                      # a 28-day window left slow movers (adamant darts, trimmed
                      # armour) with no sale median at all — which is exactly
                      # when a stray listing gets to set the price unopposed.
HISTORY_KEEP_DAYS = 365   # older sales are kept as a last-resort "stale" price
HISTORY_MAX_PER_ITEM = 24
OUTLIER_LO = 0.2      # drop sales below 0.2x the raw median
OUTLIER_HI = 5.0      # ...and above 5x — kills fat-finger listings without
                      # needing the old scraper's hand-tuned per-item caps
MIN_CORROBORATION = 2 # sales needed before they may overrule the order book
MIN_WEIGHTED_SALES = 3    # below this, weight by quantity stops being an average
                          # and becomes "whichever side moved more units"

SALE_WEIGHT = 0.75    # completed sales vs. order book, when both exist
ERROR_RATIO = 10.0    # a listing >=10x (or <=1/10) the sale price is a typo,
                      # not a signal — drop it rather than averaging it in
ASK_FLOOR_RATIO = 100.0   # how far under the asking price a completed sale may
                          # sit before it stops being believable. Far looser
                          # than ERROR_RATIO: sellers ask over the market all
                          # the time, so only the absurd should be caught here


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


def _weighted_median(sales):
    """Median price weighted by units traded. `sales` is [(price, qty), ...].

    One person buying a single lockpick "for doors" at 10,000 and someone
    else moving 50 at 4,900 are not equal evidence about what a lockpick is
    worth: 50 units of agreement outweigh one. Unweighted, the convenience
    trade wins on count alone, which is how a bank full of bulk goods ends up
    valued at prices nobody could ever liquidate into.
    """
    ordered = sorted(sales)
    total = sum(q for _, q in ordered)
    seen = 0
    for i, (price, qty) in enumerate(ordered):
        seen += qty
        # An exact half-and-half split has no middle value, so take the midpoint
        # of the two it falls between — the same thing a plain median does with
        # an even sample. Without this, two single-unit sales at 10k and 25k
        # would read as 10k purely by tie-break, which is a bias, not evidence.
        if seen * 2 == total and i + 1 < len(ordered):
            return (price + ordered[i + 1][0]) / 2
        if seen * 2 > total:
            return price
    return ordered[-1][0]


def _trimmed_median(sales):
    """(median, surviving sale count, units traded) for [(price, qty)].

    The trim anchor is the plain unweighted median, deliberately: letting
    quantity choose the window would hand a single huge trade the power to
    define what counts as an outlier — and the one 1,000,000,000gp sale in
    this dataset is booked against a quantity of two million.

    Below MIN_WEIGHTED_SALES the weighting is dropped entirely. Weighting needs
    a distribution to weigh; with one or two sales there isn't one, and the
    "weighted median" degenerates into whichever side happened to move more
    units. Super strength(4) was the case that showed it: 59 units at 3,000 and
    30 at 5,500 came out as 3,000 flat, below the 3-dose potion it strictly
    contains. Two sales support a midpoint and nothing finer.
    """
    prices = [p for p, _ in sales]
    raw = statistics.median(prices)
    kept = [(p, q) for p, q in sales
            if raw * OUTLIER_LO <= p <= raw * OUTLIER_HI] or list(sales)
    units = sum(q for _, q in kept)
    if len(kept) < MIN_WEIGHTED_SALES:
        return statistics.median([p for p, _ in kept]), len(kept), units
    return _weighted_median(kept), len(kept), units


def robust_median(sales, floor=None, ceiling=None):
    """Weighted median with a light outlier trim. Returns (value, n, units).

    `floor`/`ceiling` reject values against an independent reference (the order
    book) before the trim. The internal trim only works when the bad values are
    a minority; a reference catches them even when they aren't.

    But the reference can be the broken one, and then the filter is circular:
    a single 1,000,000,000gp ask on an adamant platebody (t) sets a floor of
    100M, throws away all ten genuine 15k-45k sales, and leaves nothing for the
    ask guard downstream to check that ask against — so the typo becomes the
    price. When the reference rejects EVERY sale, fall back to the unfiltered
    ones instead.

    That fallback is deliberately conditional. Sales only get to overrule the
    book when they corroborate each other (MIN_CORROBORATION+ surviving their
    own trim); one lone sale that the entire order book disagrees with really is
    more likely to be the mistake — someone typing the total instead of the
    unit price on 1,000 blood runes.
    """
    vals = [(p, max(1, q)) for p, q in sales if p and p > 0]
    if not vals:
        return None, 0, 0

    bounded = vals
    if floor is not None:
        bounded = [(p, q) for p, q in bounded if p >= floor]
    if ceiling is not None:
        bounded = [(p, q) for p, q in bounded if p <= ceiling]

    if not bounded:
        median, sample, units = _trimmed_median(vals)
        return (median, sample, units) if sample >= MIN_CORROBORATION else (None, 0, 0)
    return _trimmed_median(bounded)


def sale_bounds(bid_list, ask_list):
    """(floor, ceiling) for completed sales, from the standing order book.

    Someone who lists 1,000 blood runes and types the total instead of the
    per-unit price records a real 1gp sale. Nothing in the sale data itself
    marks it as wrong, but four people bidding 800-900 each do.

    Bids and asks don't get equal say here, in either direction:

    *Bids* are real coins on the table, so they bound sales tightly, both ways
    (ERROR_RATIO). If people are bidding 500, neither a 1gp sale nor a 20,000gp
    one is telling the truth about this item.

    *Asks* are one seller's hope, and hope can't prove a completed sale was a
    mistake. Letting an ask set a tight floor read the water talisman at 16,312
    against a real market of 500-1,000: a lone 10,000gp ask lifted the floor
    until all 29 units of genuine 500gp sales were rejected as implausibly
    cheap, leaving two 1-unit sales at 20,000 to set both the price and the
    outlier window it was judged against. So an ask floors sales only at
    ASK_FLOOR_RATIO — loose enough that ordinary ask-over-market optimism
    passes, tight enough to still catch the absurd. That case is real too: with
    no bids at all, a 1gp sale is the only thing standing between a purple
    partyhat and being valued at 1gp.

    Asks set no ceiling. A seller asking high is not evidence that high sales
    are wrong, and an absurd ask has its own guard downstream.
    """
    floors, ceilings = [], []
    if bid_list:
        bid_ref = sum(bid_list) / len(bid_list)
        floors.append(bid_ref / ERROR_RATIO)
        ceilings.append(bid_ref * ERROR_RATIO)
    if ask_list:
        ask_ref = sum(ask_list) / len(ask_list)
        floors.append(ask_ref / ASK_FLOOR_RATIO)
    # The most permissive floor wins: each is a separate argument for throwing
    # a sale out, and a sale only has to survive the weakest of them.
    return (min(floors) if floors else None,
            min(ceilings) if ceilings else None)


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

        # Sanity-check sales against the standing order book before averaging.
        # A mistyped listing produces a genuine sale record ("1,000 blood runes
        # for 1gp" when the seller meant 1gp each of 1,000), and no property of
        # the sale itself flags it — but live bids an order of magnitude higher
        # do. Symmetric with the guard on listings in blend().
        floor, ceiling = sale_bounds(bids.get(gid, []), asks.get(gid, []))

        sale_median, sample, units = robust_median(
            [(e["price"], e.get("qty") or 1) for e in recent],
            floor=floor, ceiling=ceiling)
        stale_median, stale_sample, stale_units = robust_median(
            [(e["price"], e.get("qty") or 1) for e in older],
            floor=floor, ceiling=ceiling)
        best_bid, best_ask, mid = price_from_book(bids.get(gid, []), asks.get(gid, []))

        # A wildly-out-of-line standing offer is usually a typo or a troll. If
        # we have *any* sale on record — even an old one — use it as the
        # reality check, and apply it to both sides of the book.
        #
        # Both sides, because the damage isn't symmetric only in theory: a
        # santa hat sat at 110,000,084 because someone had a 169gp bid standing
        # against a 220,000,000 ask, and the mid of those two is meaningless.
        # Sales at 170-220M were on file the whole time.
        reference = sale_median if sale_median is not None else stale_median
        if reference is not None:
            lo, hi = reference / ERROR_RATIO, reference * ERROR_RATIO
            sane_bids = [b for b in bids.get(gid, []) if lo <= b <= hi]
            sane_asks = [a for a in asks.get(gid, []) if lo <= a <= hi]
            best_bid, best_ask, mid = price_from_book(sane_bids, sane_asks)

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
        # Units behind the price, not just sales. The gap between the two is
        # what separates a real bulk market from a handful of one-off trades.
        traded = units if tier != "stale" else stale_units
        if traded:
            entry["volume"] = traded
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
    holding 104 doses, and every dose of a potion is the same thing. One rate
    prices the whole family.

    That rate comes from the 3-dose variant. Potions are *brewed* as (3)s and
    there's no easy way to decant, so that's where the trading is — 87% of all
    dose-family volume — and the other variants are byproducts whose thin
    markets say more about scarcity than about what a dose is worth. Super
    strength(4) was the proof: two month-old sales, 89 units, priced it at
    3,000 while super strength(3) had a live 3,500 bid and four recent sales.
    A (4) is strictly more potion than a (3); it cannot be worth less.

    Families that never trade as (3)s (agility potion only sells as a (4)) fall
    back to whichever variant has the strongest evidence.
    """
    families = {}
    for gid, item in catalog.items():
        doses, family = parse_dose(item.get("slug"))
        if doses:
            families.setdefault(family, []).append((gid, doses))

    filled = 0
    for family, members in families.items():
        def usable(gid):
            p = prices.get(gid)
            return p if p and p["tier"] in ("market", "bid", "ask") else None

        # The 3-dose variant is the anchor wherever it has a live price at all.
        anchor = next((g for g, d in members if d == 3 and usable(g)), None)
        if anchor is None:
            # No (3) trading: fall back to the best-evidenced variant.
            best = None
            for gid, doses in members:
                p = usable(gid)
                if not p:
                    continue
                score = (p["tier"] == "market", p.get("sampleSize", 0))
                if best is None or score > best[0]:
                    best = (score, gid)
            if best is None:
                continue
            anchor = best[1]

        anchor_doses = next(d for g, d in members if g == anchor)
        per_dose = prices[anchor]["price"] / anchor_doses
        for gid, doses in members:
            if gid == anchor:
                continue
            prices[gid] = {
                "price": max(1, round(per_dose * doses)),
                "tier": "dose",
                "sampleSize": 0,
                "asOf": now_iso,
                "doseAnchor": catalog.get(anchor, {}).get("slug"),
                "perDose": round(per_dose, 2),
            }
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
            # Keep a variant's own price when it has real completed-sale
            # evidence — but only where charges are the product. Under the
            # "full" model every level is the same item, so its own sales are
            # the same market as the anchor's, quoted thinner.
            if (spec["model"] == "proportional" and existing
                    and existing["tier"] == "market"
                    and existing.get("sampleSize", 0) >= 3):
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


def apply_junk_vendor_pricing(catalog, prices, now_iso):
    """Junk is worth its vendor price — what a general store pays, and no more.

    These used to be zeroed. A shop counter is a real (if small) exit, though,
    and a player who banked 500 buckets would rather see them counted at 1gp
    each than written off entirely. It stays a rounding error on any bank —
    one of every junk item in the game comes to about 12k — so this buys the
    honesty without letting untraded clutter move the number.
    """
    priced = 0
    for gid, item in catalog.items():
        # A rare is never junk, whatever a keyword rule concluded — writing a
        # partyhat down to shop value is far worse than leaving one oddity in
        # place.
        if item.get("category") != "junk" or item.get("rare"):
            continue
        cost = item.get("cost") or 0
        prices[gid] = {"price": max(1, round(cost * 0.4)) if cost > 0 else 0,
                       "tier": "junk", "sampleSize": 0, "asOf": now_iso}
        priced += 1
    return priced


def apply_recipe_pricing(catalog, prices, now_iso):
    """Price an item from the materials it's made of. See MATERIAL_RECIPES.

    Runs after same-as-base so a component that borrows another item's price
    (soda ash reads as seaweed) is already resolved. A solidly-sampled market
    price wins over the recipe — if the item starts trading properly, the
    market is the better answer and this steps aside.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    filled = 0
    for slug, recipe in MATERIAL_RECIPES.items():
        gid = by_slug.get(slug)
        if not gid:
            continue
        existing = prices.get(gid)
        if existing and existing["tier"] == "market" and existing.get("sampleSize", 0) >= 2:
            continue
        total = 0
        for part_slug, count in recipe.items():
            part_gid = by_slug.get(part_slug)
            part_price = (prices.get(part_gid) or {}).get("price") if part_gid else None
            if not part_price:
                total = None
                break
            total += part_price * count
        if not total:
            continue
        prices[gid] = {
            "price": max(1, round(total)),
            "tier": "recipe",
            "sampleSize": 0,
            "asOf": now_iso,
            "madeOf": sorted(recipe),
        }
        filled += 1
    return filled


def apply_bulk_discount(catalog, prices, now_iso):
    """Discount items with no bulk market. See BULK_UNSELLABLE in lc_items.py.

    The per-unit price is real — someone genuinely pays 5-7k for a lockpick.
    There is just no depth behind it: about 85 units traded in two months, one
    or two at a time. Holding three hundred does not mean holding three hundred
    times that price, so the whole stack is marked down.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    discounted = 0
    for slug in BULK_UNSELLABLE:
        gid = by_slug.get(slug)
        entry = prices.get(gid) if gid else None
        if not entry or not entry.get("price"):
            continue
        prices[gid] = {
            **entry,
            "price": max(1, round(entry["price"] * BULK_DISCOUNT)),
            "tier": "bulk",
            "asOf": now_iso,
            "undiscountedPrice": entry["price"],
            "undiscountedTier": entry["tier"],
        }
        discounted += 1
    return discounted


def apply_same_as_base(catalog, prices, now_iso):
    """Items worth exactly what another item is worth. See SAME_AS_BASE.

    A bucket of water is a bucket someone filled; a broken rune pickaxe is a
    rune pickaxe someone has to fix; tanned leather is the hide it came from.
    Only one side of each pair trades, so the other would otherwise land on an
    alch guess.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    filled = 0
    for slug, base_slug in SAME_AS_BASE.items():
        gid, base_gid = by_slug.get(slug), by_slug.get(base_slug)
        if not gid or not base_gid or base_gid not in prices:
            continue
        base = prices[base_gid]
        prices[gid] = {
            "price": base["price"], "tier": base["tier"],
            "sampleSize": base.get("sampleSize", 0), "asOf": now_iso,
            "sameAs": base_slug,
        }
        filled += 1
    return filled


def apply_unidentified_herb_pricing(catalog, prices, now_iso):
    """An unidentified herb is that herb before you looked at it.

    They barely trade on their own and are all named just "Herb", so whatever
    stray quote exists is noise next to the identified herb's real price.
    Always overrides, for the same reason poison variants do.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    filled = 0
    for slug, herb_slug in UNID_HERB.items():
        gid, herb_gid = by_slug.get(slug), by_slug.get(herb_slug)
        if not gid or not herb_gid or herb_gid not in prices:
            continue
        herb = prices[herb_gid]
        prices[gid] = {
            "price": herb["price"], "tier": herb["tier"],
            "sampleSize": herb.get("sampleSize", 0), "asOf": now_iso,
            "identifiedAs": herb_slug,
        }
        filled += 1
    return filled


def apply_alch_defaults(catalog, prices, now_iso):
    """Force alch pricing on the melee families nobody actually trades.

    A steel mace or a mithril halberd has no market — the odd listing that
    exists says more about the lister than the item, and alch value is the real
    floor. Dragon weapons are excluded; those genuinely trade. See
    ALCH_FAMILY_RE in lc_items.py.
    """
    nature = (prices.get(NATURE_RUNE_GID) or {}).get("price", NATURE_RUNE_FALLBACK)
    forced = 0
    for gid, item in catalog.items():
        if not is_alch_default(item.get("slug")) or not item.get("tradeable", True):
            continue
        cost = item.get("cost") or 0
        if cost <= 0:
            continue
        net_alch = max(1, round(cost * 0.6)) - nature
        if net_alch > 0:
            prices[gid] = {"price": net_alch, "tier": "alch",
                           "sampleSize": 0, "asOf": now_iso}
        else:
            prices[gid] = {"price": max(1, round(cost * 0.4)), "tier": "vendor",
                           "sampleSize": 0, "asOf": now_iso}
        forced += 1
    return forced


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


def apply_enchant_caps(catalog, prices, now_iso):
    """Cap plain gem jewellery at what its enchanted form sells for.

    Enchanting is tedious — runes, magic level, a lot of clicking — so nobody
    pays a premium for the unenchanted piece. When a thin market quotes one
    above its enchanted counterpart (a sapphire necklace at 1,000gp beside a
    games necklace(8) at 975) that's noise, and the enchanted item's price is
    the better answer for both. See ENCHANT_PRODUCT in lc_items.py.

    One-directional: an unenchanted piece trading below its enchanted form is
    normal and left alone.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    capped = 0
    for slug, product_slug in ENCHANT_PRODUCT.items():
        gid, product_gid = by_slug.get(slug), by_slug.get(product_slug)
        if not gid or not product_gid:
            continue
        entry, product = prices.get(gid), prices.get(product_gid)
        if not entry or not product or entry["price"] <= product["price"]:
            continue
        prices[gid] = {
            "price": product["price"],
            "tier": "enchant",
            "sampleSize": 0,
            "asOf": now_iso,
            "enchantCap": product_slug,
            "uncappedPrice": entry["price"],
            "uncappedTier": entry["tier"],
        }
        capped += 1
    return capped


def apply_fixed_prices(catalog, prices, now_iso):
    """Hand-set prices that override every other tier.

    A handful of items the market reads wrong no matter which fallback catches
    them — cannon parts priced as a whole cannon, soul runes off a single
    outlier bid. See FIXED_PRICES in lc_items.py.
    """
    by_slug = {i.get("slug"): g for g, i in catalog.items()}
    forced = 0
    for slug, price in FIXED_PRICES.items():
        gid = by_slug.get(slug)
        if not gid:
            continue
        previous = prices.get(gid)
        prices[gid] = {
            "price": price,
            "tier": "fixed",
            "sampleSize": 0,
            "asOf": now_iso,
            "replacedPrice": previous["price"] if previous else None,
            "replacedTier": previous["tier"] if previous else None,
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
    # Dose membership rides along for the same reason: the report reads it to
    # pour a potion family into one row, and it must not go stale.
    for item in items_db.values():
        slug = item.get("slug", "")
        item["category"] = categorize(slug, item.get("name", ""), False)
        base = slug[len("cert_"):] if slug.startswith("cert_") else slug
        doses, dose_family = parse_dose(base)
        if doses:
            item["doses"] = doses
            item["doseFamily"] = dose_family
        else:
            item.pop("doses", None)
            item.pop("doseFamily", None)

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
    junk_priced = apply_junk_vendor_pricing(items_db, prices, now_iso)
    vendor_forced = apply_vendor_defaults(items_db, prices, now_iso)
    container_filled = apply_same_as_base(items_db, prices, now_iso)
    # After same-as-base: a recipe's components may borrow another item's price.
    recipe_filled = apply_recipe_pricing(items_db, prices, now_iso)
    alch_forced = apply_alch_defaults(items_db, prices, now_iso)
    unid_filled = apply_unidentified_herb_pricing(items_db, prices, now_iso)
    enchant_capped = apply_enchant_caps(items_db, prices, now_iso)
    bulk_discounted = apply_bulk_discount(items_db, prices, now_iso)
    # Hand-set prices beat every tier above, including live market data.
    fixed_forced = apply_fixed_prices(items_db, prices, now_iso)
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
          f"{container_filled} same-as-base, {junk_priced} junk, "
          f"{recipe_filled} from materials, {bulk_discounted} bulk-discounted, "
          f"{alch_forced} forced alch, {unid_filled} unidentified herbs, "
          f"{enchant_capped} enchant-capped, {fixed_forced} fixed)", flush=True)

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
