#!/usr/bin/env python3
"""
backfill_history.py — deepen data/history.json from per-item sale pages.

Why this exists
---------------
The global /sales feed only covers a rolling ~24 hours. That's fine for liquid
items, but a bank is mostly things that trade slowly. Body runes sell at a
consistent 14gp — a few times a month. They never appear in a daily snapshot, so
they were falling through to an alch value of 2gp: seven times too low.

Each item's own page carries its last ~10 coin sales, going back months. Walking
those once gives real prices for the long tail, and the daily scrape then keeps
them current.

Which items get deepened is decided by the *evidence behind their price*, never
by which tier it landed in. That distinction is the whole point: this used to
skip anything already reading "market", so an item with one bad sale was
protected from the very data that would have corrected it. Molten glass caught
a single 50,000gp novelty sale, tier "market", and stayed ineligible while its
real market — 3,600 units at 1,900-2,000 — sat unread on its item page.

It's a rolling refresh, not a one-shot migration. State records when each item
was last looked at, so a `--limit`ed run picks up the least recently checked and
the whole catalog cycles. The daily workflow spends a small budget every run,
which drains the backlog and stops it re-forming.

Usage:
    python scripts/backfill_history.py             # everything resting on thin evidence
    python scripts/backfill_history.py --all       # every tradeable item, regardless
    python scripts/backfill_history.py --limit 40  # spend a budget of N lookups
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lc_market as mkt   # noqa: E402
from lc_items import BUNDLE_CAPS   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ITEMS_PATH = DATA_DIR / "items.json"
PRICES_PATH = DATA_DIR / "prices.json"
HISTORY_PATH = DATA_DIR / "history.json"
BOOK_PATH = DATA_DIR / "book.json"
STATE_PATH = DATA_DIR / ".backfill-state.json"

# A price carrying any of these keys was copied from another item — the dose
# anchor, the base of a variant, the item a filled bucket was filled from. The
# evidence lives on that other item, so a request spent here buys nothing.
DERIVED_MARKERS = ("doseAnchor", "chargeAnchor", "variantOf", "sameAs",
                   "notedFrom", "identifiedAs")
# Priced by fiat: a hand-set number, or zeroed vendor clutter. Nothing the
# market says would change either, so never spend a request on them.
#
# Note which fallbacks are NOT here. A `recipe`, `unfinished` or `cloth` price
# is a stand-in the item is allowed to grow out of — each of those rules steps
# aside for a properly sampled market price — and molten glass is the reason
# that matters: it reads 1,612 from sand plus soda ash while its own page
# carries 3,600 units of real sales at 1,900-2,000.
DERIVED_TIERS = {"junk", "fixed"}

# Coins are 1gp by definition; the price file lists them for convenience.
COINS_GID = "995"

# What counts as evidence solid enough to leave alone: a real market price, off
# more than a couple of sales, at least one of them recent.
MARKET_MIN_SALES = 3
MARKET_FRESH_DAYS = 30

# Don't re-examine the same item every day, however thin it looks.
RECHECK_MIN_DAYS = 7

SAVE_EVERY = 25


def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def load_state(path):
    """gid -> when it was last looked at. Reads the old flat "done" list too.

    Entries migrated from that list inherit the file's own timestamp: they were
    checked at some point, we just don't know exactly when, and dating them to
    the last run puts them at the back of the queue rather than the front.
    """
    raw = load_json(path, {})
    checked = {}
    for gid, when in (raw.get("checked") or {}).items():
        ts = parse_ts(when)
        if ts:
            checked[gid] = ts
    migrated = parse_ts(raw.get("updated")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    for gid in raw.get("done") or []:
        checked.setdefault(str(gid), migrated)
    return checked


def last_sale(history, gid):
    stamps = [parse_ts(e.get("soldAt")) for e in history.get(gid, [])]
    stamps = [t for t in stamps if t]
    return max(stamps) if stamps else None


def needs_deepening(gid, prices, history, now):
    """Is this item's price resting on evidence too thin to trust?

    Note what this does NOT ask: which tier the price landed in. A `vendor` or
    `stale` price is a confession that we found nothing, and those are exactly
    the items whose own page tends to hold a live offer the paginated feeds
    never reached — adamantite ore had a standing 1,000gp bid and a 1,000gp
    sale while we priced it at its 160gp vendor value.
    """
    if gid == COINS_GID:
        return False
    entry = prices.get(gid)
    if not entry:
        return True
    if entry.get("tier") in DERIVED_TIERS:
        return False
    if any(k in entry for k in DERIVED_MARKERS):
        return False
    if entry.get("tier") != "market":
        return True
    if entry.get("sampleSize", 0) < MARKET_MIN_SALES:
        return True
    latest = last_sale(history, gid)
    return latest is None or (now - latest).days > MARKET_FRESH_DAYS


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: could not read {path}: {e}", flush=True)
    return {} if default is None else default


def main():
    args = sys.argv[1:]
    do_all = "--all" in args
    limit = None
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit needs a number")
            return

    items = load_json(ITEMS_PATH)
    if not items:
        print("data/items.json is empty — run scripts/build_catalog.py first.")
        sys.exit(1)
    prices = load_json(PRICES_PATH)
    history = load_json(HISTORY_PATH)
    book = load_json(BOOK_PATH)
    checked = load_state(STATE_PATH)
    now = datetime.now(timezone.utc)
    never = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Untradeable items can never have a market price — never spend a request.
    targets = []
    for gid, item in items.items():
        if not item.get("tradeable", True) or item.get("notedOf"):
            continue
        if not do_all and not needs_deepening(gid, prices, history, now):
            continue
        seen = checked.get(gid)
        if seen and not do_all and (now - seen).days < RECHECK_MIN_DAYS:
            continue
        targets.append((seen or never, gid, item["slug"]))

    # Least recently checked first, so a budgeted run rotates through the
    # catalog instead of gnawing at the same low game ids every time. Items
    # never looked at sort to the very front.
    targets.sort(key=lambda t: (t[0], int(t[1])))
    total_eligible = len(targets)
    if limit:
        targets = targets[:limit]
    targets = [(gid, slug) for _, gid, slug in targets]

    if not targets:
        print("Nothing to backfill — every tradeable item's price rests on real evidence.")
        return

    est = len(targets) * mkt.RATE / 60
    print(f"backfilling {len(targets)} of {total_eligible} eligible items "
          f"from {mkt.BASE}/items/<slug>", flush=True)
    if len(targets) < total_eligible:
        print("  (least recently checked first; the rest follow on later runs)", flush=True)
    print(f"~{est:.0f} min at {mkt.RATE}s/request. Ctrl-C is safe — progress is saved.\n", flush=True)

    added = found = 0
    try:
        for n, (gid, slug) in enumerate(targets, 1):
            try:
                item, sales, bids, asks = mkt.fetch_item_history(slug)
            except Exception as e:
                print(f"  [{n}/{len(targets)}] {slug:<30} error: {e}", flush=True)
                continue

            cap = BUNDLE_CAPS.get(slug)
            if cap:
                sales = [s for s in sales if s["price"] <= cap]
                bids = [b for b in bids if b <= cap]
                asks = [a for a in asks if a <= cap]

            # Standing offers found here feed the same bid/ask logic the main
            # scraper uses, so a quiet item still gets a real price.
            if bids or asks:
                book[gid] = {"bids": bids, "asks": asks}

            if sales:
                bucket = history.setdefault(gid, [])
                seen = {(e.get("soldAt"), e.get("price"), e.get("qty")) for e in bucket}
                fresh = [s for s in sales
                         if (s.get("soldAt"), s.get("price"), s.get("qty")) not in seen]
                bucket.extend(fresh)
                added += len(fresh)
                found += 1
                newest = max((s.get("soldAt") or "")[:10] for s in sales)
                print(f"  [{n}/{len(targets)}] {slug:<30} {len(sales)} sales, "
                      f"latest {newest}, +{len(fresh)} new", flush=True)
            else:
                print(f"  [{n}/{len(targets)}] {slug:<30} no coin sales", flush=True)

            checked[gid] = datetime.now(timezone.utc)
            if n % SAVE_EVERY == 0:
                flush(history, checked, book)
            if n < len(targets):
                time.sleep(mkt.RATE)
    except KeyboardInterrupt:
        print("\ninterrupted — saving progress", flush=True)

    flush(history, checked, book)
    print(f"\nDone: {found} items with sale history, {added} new sales recorded.", flush=True)
    remaining = max(0, total_eligible - len(targets))
    if remaining:
        print(f"{remaining} eligible items still queued for a later run.", flush=True)
    print("Now re-run scripts/scrape_prices.py to fold these into prices.json.", flush=True)


def flush(history, checked, book):
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")
    BOOK_PATH.write_text(json.dumps(book, indent=2, sort_keys=True), encoding="utf-8")
    STATE_PATH.write_text(
        json.dumps({
            "checked": {gid: ts.strftime("%Y-%m-%dT%H:%M:%SZ")
                        for gid, ts in sorted(checked.items(), key=lambda kv: int(kv[0]))},
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, indent=1),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\nFATAL ERROR: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
