#!/usr/bin/env python3
"""
lc_market.py — shared helpers for talking to markets.lostcity.rs.

Used by scrape_prices.py (regular price refresh) and backfill_catalog.py
(one-time full item catalog build).

The Markets site is an Inertia app: every server-rendered page embeds its
props as JSON in a `data-page` attribute. That's the same mechanism the
site's own front end consumes, and it's how we read paginated feeds that
the documented /api/* routes don't expose (completed sales, and active
listings beyond the API's 100-item cap).
"""

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://markets.lostcity.rs"
USER_AGENT = "LC-bankvalue/0.1 (Lost City bank value calculator; contact via GitHub issues)"
RATE = 0.8       # seconds between requests — be polite to a community server
TIMEOUT = 20
RETRIES = 3

COINS_GAME_ID = 995


def _request(url, accept_json=False):
    headers = {"User-Agent": USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/json"
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except Exception as e:
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {RETRIES} attempts: {last_err}")


def fetch_props(url):
    """Fetch an Inertia page and return its props dict (or None)."""
    body = _request(url)
    if body is None:
        return None
    m = re.search(r'data-page="([^"]*)"', body)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1))).get("props", {})
    except Exception:
        return None


def fetch_json(url):
    body = _request(url, accept_json=True)
    if body is None:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def unit_price(listing):
    """Coin-per-unit price for a listing, or None if it isn't a clean coin trade.

    A listing's single offer holds the payment: offers[0].items[0].quantity is
    the coin amount paid *per unit* of the listed item. Barter trades (non-coin
    payment, or multi-item payment) are rejected — they can't be valued without
    circular pricing.
    """
    offers = listing.get("offers") or []
    if len(offers) != 1:
        return None
    items = offers[0].get("items") or []
    if len(items) != 1:
        return None
    pay = items[0].get("item") or {}
    if pay.get("game_id") != COINS_GAME_ID and pay.get("slug") != "coins":
        return None
    qty = items[0].get("quantity")
    if not isinstance(qty, (int, float)) or qty <= 0:
        return None
    return float(qty)


def walk_feed(path, max_pages=40, label=""):
    """Yield every listing from a paginated Inertia feed.

    path examples: "/sales", "/?tab=buy", "/?tab=sell"
    """
    page = 1
    last_page = None
    while page <= max_pages:
        sep = "&" if "?" in path else "?"
        url = f"{BASE}{path}" if page == 1 else f"{BASE}{path}{sep}page={page}"
        props = fetch_props(url)
        if props is None:
            print(f"    {label} page {page}: no data, stopping", flush=True)
            return
        listings = props.get("listings", {})
        data = listings.get("data", [])
        for listing in data:
            yield listing

        meta = listings.get("meta", {})
        if last_page is None:
            last_page = meta.get("last_page", 1)
            print(f"    {label}: {meta.get('total', '?')} entries over {last_page} pages", flush=True)
        if page >= (last_page or 1):
            return
        page += 1
        time.sleep(RATE)


def fetch_item_history(slug):
    """Per-item page -> (item_dict, [ {price, qty, soldAt} ]).

    The global /sales feed only covers a rolling ~24h. An item page carries its
    own sold-listing history going back months, which is the only way to price
    anything that trades slowly (body runes sell at 14gp consistently, but a
    couple of times a month — invisible to the daily feed, so they were falling
    back to a 2gp alch value).
    """
    props = fetch_props(f"{BASE}/items/{urllib.parse.quote(slug)}")
    if props is None:
        return None, []
    item = props.get("item") or {}
    sold = (props.get("soldListings") or {}).get("data", []) or []

    sales = []
    for listing in sold:
        price = unit_price(listing)
        if price is None:
            continue
        sales.append({
            "price": price,
            "qty": listing.get("quantity") or 1,
            "soldAt": listing.get("soldAt") or listing.get("updatedAt"),
        })
    return item, sales


def lookup_item(slug):
    """Exact-slug catalog lookup via the documented search API.

    /api/items?q=<term> is a search capped at 5 results, so it can't enumerate
    the catalog — but for a known slug it returns the item's game_id, name and
    cost in a very small JSON response, which is what the backfill needs.
    """
    url = f"{BASE}/api/items?q={urllib.parse.quote(slug)}&include_unlisted=1"
    results = fetch_json(url)
    if not results:
        return None
    for item in results:
        if item.get("slug") == slug:
            return item
    return None
