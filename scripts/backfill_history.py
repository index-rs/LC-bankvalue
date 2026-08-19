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

This is slow and only worth running occasionally (the deep history barely moves).
It's resumable — rerun it and it picks up where it left off.

Usage:
    python scripts/backfill_history.py             # tradeable items missing good prices
    python scripts/backfill_history.py --all       # every tradeable item
    python scripts/backfill_history.py --limit 200 # stop after N lookups
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lc_market as mkt   # noqa: E402
from lc_items import BUNDLE_CAPS   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ITEMS_PATH = DATA_DIR / "items.json"
PRICES_PATH = DATA_DIR / "prices.json"
HISTORY_PATH = DATA_DIR / "history.json"
STATE_PATH = DATA_DIR / ".backfill-state.json"

# Tiers that mean "we already have a decent price, don't spend a request here".
GOOD_TIERS = {"market", "bid", "dose", "charge", "noted", "cloth"}

SAVE_EVERY = 25


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
    state = load_json(STATE_PATH, {"done": []})
    done = set(state.get("done", []))

    # Untradeable items can never have a market price — never spend a request.
    targets = []
    for gid, item in items.items():
        if not item.get("tradeable", True) or item.get("notedOf"):
            continue
        if gid in done:
            continue
        if not do_all:
            tier = (prices.get(gid) or {}).get("tier")
            if tier in GOOD_TIERS:
                continue
        targets.append((gid, item["slug"]))

    targets.sort(key=lambda t: int(t[0]))
    if limit:
        targets = targets[:limit]

    if not targets:
        print("Nothing to backfill — every tradeable item already has a good price.")
        print(f"(delete {STATE_PATH.name} to start over)")
        return

    est = len(targets) * mkt.RATE / 60
    print(f"backfilling {len(targets)} items from {mkt.BASE}/items/<slug>", flush=True)
    print(f"~{est:.0f} min at {mkt.RATE}s/request. Ctrl-C is safe — progress is saved.\n", flush=True)

    added = found = 0
    try:
        for n, (gid, slug) in enumerate(targets, 1):
            try:
                item, sales = mkt.fetch_item_history(slug)
            except Exception as e:
                print(f"  [{n}/{len(targets)}] {slug:<30} error: {e}", flush=True)
                continue

            cap = BUNDLE_CAPS.get(slug)
            if cap:
                sales = [s for s in sales if s["price"] <= cap]

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

            done.add(gid)
            if n % SAVE_EVERY == 0:
                flush(history, done)
            if n < len(targets):
                time.sleep(mkt.RATE)
    except KeyboardInterrupt:
        print("\ninterrupted — saving progress", flush=True)

    flush(history, done)
    print(f"\nDone: {found} items with sale history, {added} new sales recorded.", flush=True)
    print("Now re-run scripts/scrape_prices.py to fold these into prices.json.", flush=True)


def flush(history, done):
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")
    STATE_PATH.write_text(
        json.dumps({"done": sorted(done), "updated": datetime.now(timezone.utc).isoformat()}),
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
