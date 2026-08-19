#!/usr/bin/env python3
"""
build_catalog.py — build data/items.json from Lost City's own Content repo.

This is the authoritative item catalog: the game's published content for build
274, not something inferred from market activity. It gives us, for every item
in the game:

  pack/obj.pack     numeric game_id  <->  slug   (the same ids .sav files use)
  scripts/**/*.obj  name, cost (alch base), tradeable flag, dose/note variants

Why this matters:
  * Market feeds only ever show items that are actively trading (~300 of 3,900),
    so most of a real bank was previously "unknown". Now every item resolves.
  * `tradeable=no` is explicit here, so an item with no market price can be
    correctly reported as untradeable/valueless rather than "no data".
  * Noted items (cert_x) map back to their base item for pricing.

Run this when the game content updates (rarely). The regular price refresh
(scrape_prices.py) does not need it and will not overwrite it.

Usage:
    python scripts/build_catalog.py
"""

import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lc_items import base_variant, categorize, disambiguate_name  # noqa: E402

CONTENT_TARBALL = "https://github.com/LostCityRS/Content/archive/refs/heads/274.tar.gz"
USER_AGENT = "LC-bankvalue/0.1 catalog-builder"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ITEMS_PATH = DATA_DIR / "items.json"

# Tradeable "rare" holiday items. Their prices are driven by collector demand
# rather than utility, swing wildly, and can dwarf an entire normal bank — so
# the report totals them separately. Curated deliberately: this is the set
# players actually mean by "rares", which is not the same as the engine's
# holiday.obj (that includes untradeable event junk and omits several rares).
RARE_SLUGS = {
    "red_partyhat", "yellow_partyhat", "blue_partyhat", "green_partyhat",
    "purple_partyhat", "white_partyhat",
    "santa_hat",
    "halloweenmask_green", "halloweenmask_blue", "halloweenmask_red",
    "christmas_cracker", "easter_egg", "pumpkin",
    "half_full_wine_jug", "discofreturning",
}

WEIGHT_RE = re.compile(r"^weight=", re.M)


def fetch_content_tree():
    """Download the Content tarball and return {path: text} for what we need."""
    print(f"downloading {CONTENT_TARBALL} ...", flush=True)
    req = urllib.request.Request(CONTENT_TARBALL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        blob = resp.read()
    print(f"  {len(blob):,} bytes", flush=True)

    obj_pack = None
    obj_configs = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name
            if name.endswith("/pack/obj.pack"):
                obj_pack = tar.extractfile(member).read().decode("utf-8", "replace")
            elif name.endswith(".obj"):
                obj_configs.append(tar.extractfile(member).read().decode("utf-8", "replace"))
    if obj_pack is None:
        raise RuntimeError("pack/obj.pack not found in Content tarball")
    print(f"  found obj.pack + {len(obj_configs)} .obj config files", flush=True)
    return obj_pack, obj_configs


def parse_obj_pack(text):
    """'995=coins' lines -> {slug: game_id}."""
    mapping = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        gid, slug = line.split("=", 1)
        try:
            mapping[slug.strip()] = int(gid)
        except ValueError:
            continue
    return mapping


def parse_obj_configs(configs):
    """Parse [slug] blocks -> {slug: {name, cost, tradeable}}."""
    defs = {}
    for text in configs:
        current = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1].strip()
                defs.setdefault(current, {"name": None, "cost": None, "tradeable": True})
            elif current and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key == "name":
                    defs[current]["name"] = value
                elif key == "cost":
                    try:
                        defs[current]["cost"] = int(value)
                    except ValueError:
                        pass
                elif key == "tradeable":
                    defs[current]["tradeable"] = value.lower() not in ("no", "false", "0")
    return defs


def prettify(slug):
    """Fallback display name for items with no name= line."""
    return slug.replace("_", " ").strip().capitalize()


def main():
    DATA_DIR.mkdir(exist_ok=True)
    obj_pack_text, obj_configs = fetch_content_tree()

    slug_to_id = parse_obj_pack(obj_pack_text)
    defs = parse_obj_configs(obj_configs)
    print(f"  {len(slug_to_id)} ids in obj.pack, {len(defs)} defined in configs", flush=True)

    items = {}
    for slug, gid in slug_to_id.items():
        d = defs.get(slug, {})

        # Noted items (cert_x) are priced off their base item.
        noted_of = None
        base_slug = slug
        if slug.startswith("cert_"):
            candidate = slug[len("cert_"):]
            if candidate in slug_to_id:
                noted_of = slug_to_id[candidate]
                base_slug = candidate

        base_def = defs.get(base_slug, d)
        name = d.get("name") or base_def.get("name") or prettify(base_slug)
        if noted_of is not None:
            name = f"{name} (noted)"

        name = disambiguate_name(base_slug, name if noted_of is None else name)
        if noted_of is not None and not name.endswith("(noted)"):
            name = f"{name} (noted)"

        entry = {
            "slug": slug,
            "name": name,
            "cost": d.get("cost") if d.get("cost") is not None else (base_def.get("cost") or 0),
            "category": categorize(base_slug, name, False),
            "tradeable": bool(base_def.get("tradeable", True)),
        }
        if noted_of is not None:
            entry["notedOf"] = str(noted_of)
        if base_slug in RARE_SLUGS:
            entry["rare"] = True

        # Poisoned weapons and dragon leather are priced and displayed as their
        # base item; the report folds them into that row with a "+N poisoned"
        # style note rather than listing them separately at a bad price.
        var_base, var_label = base_variant(base_slug)
        if var_base and var_base in slug_to_id:
            entry["pricedAs"] = str(slug_to_id[var_base])
            entry["variant"] = var_label
        items[str(gid)] = entry

    # Preserve any market-derived fields from a previous items.json that the
    # catalog itself doesn't know about.
    if ITEMS_PATH.exists():
        try:
            prev = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
            for gid, old in prev.items():
                if gid in items:
                    for key in ("marketName",):
                        if key in old:
                            items[gid][key] = old[key]
        except Exception:
            pass

    tradeable = sum(1 for i in items.values() if i["tradeable"])
    noted = sum(1 for i in items.values() if "notedOf" in i)
    rares = sum(1 for i in items.values() if i.get("rare"))
    print(f"\nDone: {len(items)} items", flush=True)
    print(f"    tradeable   {tradeable}", flush=True)
    print(f"    untradeable {len(items) - tradeable}", flush=True)
    print(f"    noted       {noted}", flush=True)
    print(f"    rares       {rares}", flush=True)

    ITEMS_PATH.write_text(json.dumps(items, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {ITEMS_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\nFATAL ERROR: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
