#!/usr/bin/env python3
"""
build_recipes.py — build data/recipes.json from Lost City's own Content repo.

Sibling of build_catalog.py: that one answers "what is this item", this one
answers "what can you turn it into, and what does the skill pay you for it".

Same discipline, same source of truth: every recipe here is read out of
LostCityRS/Content build 274, and every recipe carries a `src` naming the file
and block it came from. Nothing is typed off a wiki.

XP lives in Content in four shapes, and this script reads three of them
mechanically:

  * `.dbrow` rows against a `.dbtable`   fletching, gem cutting, leather,
                                         smithing, runecraft, magic
  * `param=` on the item itself          firemaking (productexp), prayer
                                         (bone_exp), herblore identify
  * `.struct` named param bags           smelting, jewellery, spinning,
                                         pottery, glass, studded, battlestaves,
                                         herblore brewing

The fourth shape — a literal buried in a `.rs2` script body — cannot be
extracted, so it is hand-written in LITERALS below with a file:line citation
per entry, in the same spirit as FIXED_PRICES in lc_items.py. Keep that table
short and make every line say where it came from.

Two traps worth knowing about, both of which will silently produce a wrong
answer rather than an error:

  1. **Everything is in tenths.** `stat_advance` takes tenths of an xp point,
     so `experience=750` is 75.0 xp. Divided out on extraction; recipes.json
     stores real xp and nothing downstream has to think about it.

  2. **`product,<obj>,<n>` means two different things** depending on which
     script reads the row. `make_bolts` treats the n in
     `product,opal_bolt,10` as a batch cap (10 per click, 1 tip -> 1 bolt),
     while `make_bolt_tips` treats the n in `product,opal_bolttips,12` as a
     real yield (1 opal -> 12 tips). Same table, same column. Which one applies
     is a property of the consuming .rs2, so every handler below states its
     reading explicitly and cites the script it read.

Run this when the game content updates (rarely) — same cadence as
build_catalog.py.

Usage:
    python scripts/build_recipes.py
"""

import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lc_items import disambiguate_name  # noqa: E402

CONTENT_TARBALL = "https://github.com/LostCityRS/Content/archive/refs/heads/274.tar.gz"
CONTENT_BUILD = "274"
USER_AGENT = "LC-bankvalue/0.1 recipe-builder"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RECIPES_PATH = DATA_DIR / "recipes.json"

# Suffixes worth carrying in memory. .rs2 is included only so the herb-identify
# handler can read its opheld1 dispatch table; nothing else parses script text.
WANT = (".obj", ".dbrow", ".dbtable", ".struct", ".param", ".rs2",
        ".loc", ".npc", ".inv")


class BuildError(Exception):
    """Raised for anything that would silently shrink the recipe set."""


# ---------------------------------------------------------------------------
# Content fetch + parsing
# ---------------------------------------------------------------------------

def fetch_content_tree():
    """Download the Content tarball -> (obj.pack text, {relpath: text})."""
    print(f"downloading {CONTENT_TARBALL} ...", flush=True)
    req = urllib.request.Request(CONTENT_TARBALL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        blob = resp.read()
    print(f"  {len(blob):,} bytes", flush=True)

    obj_pack = None
    tree = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            # Strip the "Content-274/" prefix so a `src` citation reads the way
            # you would type it into the GitHub UI.
            rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if rel == "pack/obj.pack":
                obj_pack = tar.extractfile(member).read().decode("utf-8", "replace")
            elif rel.endswith(WANT):
                tree[rel] = tar.extractfile(member).read().decode("utf-8", "replace")
    if obj_pack is None:
        raise BuildError("pack/obj.pack not found in Content tarball")
    print(f"  obj.pack + {len(tree)} config/script files", flush=True)
    return obj_pack, tree


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


BLOCK_RE = re.compile(r"^\[([^\]]+)\]\s*$")


def parse_blocks(text):
    """
    '[name]' + 'key=value' config format -> [(name, [(key, value), ...])].

    Key/value pairs are kept as an ordered list rather than a dict because
    repeats are meaningful: a dbrow can carry several `data=convertobj,...`
    lines and a struct several params of the same shape.
    """
    blocks = []
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        m = BLOCK_RE.match(line)
        if m:
            current = (m.group(1).strip(), [])
            blocks.append(current)
        elif current is not None and "=" in line:
            key, _, value = line.partition("=")
            current[1].append((key.strip(), value.strip()))
    return blocks


class Content:
    """Indexed view of the Content tree, with lookups that fail loudly."""

    def __init__(self, obj_pack_text, tree):
        self.slug_to_id = parse_obj_pack(obj_pack_text)
        self.tree = tree
        self.structs = {}   # name -> (relpath, kv)
        self.objs = {}      # slug -> (relpath, kv)
        self.dbrows = {}    # name -> (relpath, table, kv)

        for rel, text in sorted(tree.items()):
            if rel.endswith(".struct"):
                for name, kv in parse_blocks(text):
                    self._put(self.structs, name, rel, kv)
            elif rel.endswith(".obj"):
                for name, kv in parse_blocks(text):
                    self._put(self.objs, name, rel, kv)
            elif rel.endswith(".dbrow"):
                for name, kv in parse_blocks(text):
                    table = next((v for k, v in kv if k == "table"), None)
                    if table is not None:
                        self.dbrows[name] = (rel, table, kv)

    @staticmethod
    def _put(target, name, rel, kv):
        """
        First real definition wins. Content ships a partial re-dump under
        scripts/_unpack/ that repeats ~137 objs with fewer fields; it must
        never shadow the authoritative config.
        """
        if name not in target:
            target[name] = (rel, kv)
        elif "_unpack/" in target[name][0] and "_unpack/" not in rel:
            target[name] = (rel, kv)

    # -- lookups ------------------------------------------------------------

    def oid(self, slug):
        """Slug -> numeric game id. A missing id is a build failure."""
        if slug not in self.slug_to_id:
            raise BuildError(f"item slug not in obj.pack: {slug!r}")
        return self.slug_to_id[slug]

    def obj_name(self, slug):
        """
        Display name for a recipe label, run through the same disambiguation
        the item catalog uses — otherwise three different recipes all read
        "Craft dragonhide body" and the step list is unreadable.
        """
        found = self.objs.get(slug)
        raw = None
        if found:
            for k, v in found[1]:
                if k == "name":
                    raw = v
                    break
        if raw is None:
            raw = slug.replace("_", " ").capitalize()
        return disambiguate_name(slug, raw) or raw

    def obj_param(self, slug, name):
        """One `param=<name>,<value>` off an item definition, or None."""
        found = self.objs.get(slug)
        return param(found[1], name) if found else None

    def rows(self, table):
        """All dbrows declaring `table=<table>`, as (name, relpath, kv)."""
        out = [(n, rel, kv) for n, (rel, t, kv) in self.dbrows.items() if t == table]
        if not out:
            raise BuildError(f"no dbrows found for table {table!r}")
        return sorted(out)

    def structs_in(self, folder):
        """Structs living under a named config folder, sorted by name."""
        out = [(n, rel, kv) for n, (rel, kv) in self.structs.items()
               if f"/{folder}/" in rel]
        if not out:
            raise BuildError(f"no structs found under configs/{folder}/ — moved?")
        return sorted(out)

    def struct_owners(self, param_name):
        """{struct name: obj slug} for objs carrying `param=<param_name>,<struct>`."""
        owners = {}
        for slug, (_rel, kv) in self.objs.items():
            target = param(kv, param_name)
            if target:
                owners[target] = slug
        if not owners:
            raise BuildError(f"no objs carry param={param_name}")
        return owners


def vals(kv, key, prefix="data"):
    """
    Every `<prefix>=<key>,<rest>` line's remaining fields, one list per line.

    `data=shortbow,unstrung_yew_longbow,70,750`
        -> [['unstrung_yew_longbow', '70', '750']]
    """
    out = []
    for k, v in kv:
        if k != prefix:
            continue
        head, _, rest = v.partition(",")
        if head.strip() == key:
            out.append([p.strip() for p in rest.split(",")] if rest else [])
    return out


def one(kv, key, prefix="data", default=None):
    """First value of a single-valued column/param, or `default`."""
    got = vals(kv, key, prefix)
    if not got or not got[0]:
        return default
    return got[0][0]


def param(kv, key, default=None):
    return one(kv, key, prefix="param", default=default)


def tenths(raw, default=None):
    """Content stores xp as tenths; recipes.json stores real xp."""
    if raw is None:
        return default
    return round(int(raw) / 10, 1)


# ---------------------------------------------------------------------------
# The hand-maintained tables
#
# These are the parts that will rot when Content updates, so they are kept
# small, cited, and checked: the build errors out if a slug or block named
# here stops existing, rather than quietly dropping the recipes.
# ---------------------------------------------------------------------------

# Second ingredients that live in the consuming .rs2 rather than in the table.
# Each entry names the inv_del line it was read from.
CO_INPUT_SRC = {
    "bow_string": "skill_fletching/scripts/bows.rs2:39 inv_del(inv, bow_string, 1)",
    "feather": "skill_fletching/scripts/darts.rs2:53 inv_del(inv, feather, $darts_count)",
    "headless_arrow": "skill_fletching/scripts/arrows.rs2:79 inv_del(inv, headless_arrow, $arrows_count)",
    "bolt": "skill_fletching/scripts/bolts.rs2:82 inv_del(inv, bolt, $bolts_count)",
    "studs": "skill_crafting/scripts/studded/studded.rs2:51 inv_del(inv, studs, 1)",
    "ball_of_wool": "skill_crafting/scripts/jewellery/stringing.rs2:64 inv_del(inv, ball_of_wool, 1)",
    "battlestaff": "skill_crafting/scripts/battlestaves/battlestaves.rs2:34 inv_del(inv, battlestaff, 1)",
}

# Ingredients you are expected to BUY rather than bank.
#
# A battlestaff is not something you find — Zaff in Varrock and the Magic Guild
# stock them, five at a time, and a crafter buying orbs buys staves to go with
# them. battlestaves.struct names only the orb, so without this the recipe read
# as free and a bank of 5,000 orbs reported 687k Crafting xp with no mention of
# the 38M gp of staves it takes to get it.
#
# Marked rather than dropped: the solve still runs the recipe, but counts the
# shortfall as a purchase, prices it, and says so. A missing ingredient you can
# walk into a shop and buy is a shopping note, not a wall — the same call the
# tool already makes for tools you don't hold.
SHOP_BOUGHT = {
    "battlestaff": "areas/area_varrock/configs/varrock.inv:150 stock1=battlestaff,5 "
                   "(Zaff) and areas/area_yanille/configs/magic_guild/magic_guild.inv:22",
}

# Gems that dispatch to @make_bolt_tips instead of @make_bolts. This is the one
# place the same dbrow column changes meaning, and the list is an explicit case
# label in the script, so it is copied verbatim rather than guessed at.
BOLT_TIP_INPUTS = {"opal", "smalloysterpearls", "bigoysterpearls"}
BOLT_TIP_SRC = ("skill_crafting/scripts/gem/uncut_gem.rs2:6 "
                "case opal, smalloysterpearls, bigoysterpearls : @make_bolt_tips")

# jewellery.struct holds gold-bar and silver-bar recipes in one file with no
# field distinguishing them; the split is in which script reads the struct.
# These three are the silver ones, named by the objs that carry
# crafting_jewelry_struct in silver.obj.
SILVER_STRUCTS = {"unstrung_symbol", "unstrung_emblem", "silver_sickle"}
SILVER_SRC = ("skill_crafting/configs/jewellery/silver.obj param=crafting_jewelry_struct "
              "+ scripts/jewellery/jewellery.rs2:326 inv_del(inv, silver_bar, 1)")

# Rows that exist in Content but cannot be reached by a player in this build.
#
# A config row is not a promise the content shipped. Lost City is pinned to a
# 2004 snapshot, and some tables carry rows for things that arrived later; the
# row is there, the way in is not. Extracting one anyway invents a recipe, and
# it is the kind of error that looks completely normal in the output.
#
# The test that caught this: every tool item a recipe requires should appear
# somewhere that could put it in a player's hands — a drop table, a shop, a
# spawn, a quest reward. Grep the whole scripts/ tree for the slug, excluding
# .obj/.param/.dbtable (which say what an item *is*, not where it comes from)
# and /_test/ (cheat commands). Re-run that when Content updates; the build
# prints a warning for any tool that comes back empty.
UNRELEASED = {
    "runecraft_death":
        "death_talisman has no source anywhere in build 274 — it appears only "
        "in pack/obj.pack, its own runecraft.obj definition, and "
        "_test/scripts/cheats/cheat_bank.rs2, while every other talisman has "
        "at least one drop, shop or quest source. The row is also the only one "
        "in runecraft.dbrow whose enter_coord and exit_coord are both just the "
        "altar_coord, where every released altar has distinct ones. Death "
        "runecrafting arrived in 2005.",
}

# Filled in as handlers skip them, so a stale entry cannot go unnoticed.
SKIPPED_UNRELEASED = set()

# Tanning: no xp, but without it a bank of raw hide is inert, because every
# craft_leather_table row wants tanned leather. Costs are the constants in
# area_alkharid/configs/tanner.constant; the werewolf tanner in Canifis
# charges more (2/5/45) and is not modelled, since nobody walks past
# Al Kharid to pay double.
#
#   hide -> leather, gp per hide, source
TANNING = [
    ("cow_hide", "leather", 1),
    ("cow_hide", "hard_leather", 3),
    ("dragonhide_green", "dragon_leather", 20),
    ("dragonhide_blue", "dragon_leather_blue", 20),
    ("dragonhide_red", "dragon_leather_red", 20),
    ("dragonhide_black", "dragon_leather_black", 20),
]
TANNING_SRC = ("scripts/areas/area_alkharid/scripts/tanner.rs2 "
               "@tan_soft_leather / @tan_hard_leather / @tan_dragonhide "
               "+ configs/tanner.constant")

# The other zero-xp prep steps, same shape as tanning and there for the same
# reason: without them a whole skill line reads as worth nothing.
#
#   clay + a container of water -> soft clay, and the empty container back
#   an empty bucket             -> a bucket of sand, from any sand pit
#
# Neither pays xp, and neither is in any config — both are plain script bodies
# — but every pottery recipe wants soft clay and every glass recipe wants sand,
# so a bank of raw clay read as zero Crafting the same way 700 dragonhide once
# did. The sand is free: a sand pit fills a bucket for nothing, so the only
# thing standing between an empty bucket and molten glass is the walk knowing
# the step exists.
SOFT_CLAY_WATER = ["bowl_water", "bucket_water", "jug_water"]
SOFT_CLAY_SRC = ("scripts/skill_crafting/scripts/pottery/pottery.rs2:44 "
                 "@make_softclay, dispatched from pottery.rs2:4 "
                 "case bowl_water, bucket_water, jug_water")
SAND_FILL_SRC = ("scripts/skill_crafting/scripts/glass/glass.rs2:12 @sand_fill "
                 "-- inv_del(inv, bucket_empty, 1); inv_add(inv, bucket_sand, 1)")

# quest.enum:22 — the varp these recipes gate on is %chompybird.
OGRE_QUEST = "Big Chompy Bird Hunting"

# What cancels the iron-smelting roll, and what it costs. Both read out of the
# scripts rather than assumed: smelting.rs2:200 takes the ring branch before it
# ever reaches the roll, and ring_of_forging.rs2:5 melts the ring on the 140th
# charge.
RING_OF_FORGING = "ring_of_forging"
RING_CHARGES = 140

# Shape 4: literals in .rs2 bodies. Every entry cites file:line.
LITERALS = [
    dict(
        key="fletch_headless_arrow", skill="fletching", level=1, xp=1.0,
        label="Attach feathers to arrow shafts",
        inp=[("arrow_shaft", 1), ("feather", 1)], out=[("headless_arrow", 1)],
        src="scripts/skill_fletching/scripts/arrows.rs2:46 "
            "stat_advance(fletching, multiply($arrow_count, 10))",
    ),
    dict(
        key="craft_molten_glass", skill="crafting", level=1, xp=20.0,
        label="Melt sand and soda ash into glass",
        inp=[("bucket_sand", 1), ("soda_ash", 1)],
        out=[("molten_glass", 1), ("bucket_empty", 1)],
        src="scripts/skill_crafting/scripts/glass/glass.rs2:53 "
            "stat_advance(crafting, 200)",
    ),
    # The ogre arrow chain (Big Chompy Bird Hunting). Quest-gated, and shipped
    # anyway: a player knows whether they have done the quest, and leaving it
    # out made a whole fletching line silently missing. The recipes carry the
    # quest name so the report can say which one.
    #
    # Two of the four have a random yield — `~random_range(2, 6)`, uniform, so
    # four on average — and their xp is paid per unit produced, which makes
    # both the yield and the xp expectations rather than counts.
    dict(
        key="fletch_ogre_shafts", skill="fletching", level=5, xp=7.2,
        label="Cut achey tree logs into ogre arrow shafts",
        inp=[("achey_tree_logs", 1)], out=[("ogre_arrow_shaft", 4)],
        tools=["knife"], quest=OGRE_QUEST,
        chance={"kind": "randomYield", "min": 2, "max": 6},
        note="yields 2-6 shafts at 1.8 xp each (~random_range(2, 6)), so both "
             "the 4 shafts and the 7.2 xp are averages",
        src="scripts/skill_fletching/scripts/ogre_arrows.rs2:40 "
            "stat_advance(fletching, multiply($shaft_count, 18))",
    ),
    dict(
        key="fletch_wolfbone_tips", skill="fletching", level=5, xp=10.0,
        label="Chisel wolf bones into arrow tips",
        inp=[("wolf_bones", 1)], out=[("wolfbone_arrowheads", 4)],
        tools=["chisel"], quest=OGRE_QUEST,
        chance={"kind": "randomYield", "min": 2, "max": 6},
        note="yields 2-6 tips at 2.5 xp each, so both numbers are averages. "
             "The same action also pays the same again in Crafting "
             "(ogre_arrows.rs2:67) — counted here under Fletching only",
        src="scripts/skill_fletching/scripts/ogre_arrows.rs2:66 "
            "stat_advance(fletching, multiply($tip_count, 25))",
    ),
    dict(
        key="fletch_ogre_headless_arrow", skill="fletching", level=5, xp=1.5,
        label="Attach feathers to ogre arrow shafts",
        inp=[("ogre_arrow_shaft", 1), ("feather", 4)],
        out=[("ogre_headless_arrow", 1)], quest=OGRE_QUEST,
        note="four feathers per shaft, not one (ogre_arrows.rs2:102)",
        src="scripts/skill_fletching/scripts/ogre_arrows.rs2:107 "
            "stat_advance(fletching, multiply($arrow_count, 15))",
    ),
    dict(
        key="fletch_ogre_arrow", skill="fletching", level=5, xp=1.0,
        label="Make ogre arrows",
        inp=[("ogre_headless_arrow", 1), ("wolfbone_arrowheads", 1)],
        out=[("ogre_arrow", 1)], quest=OGRE_QUEST,
        src="scripts/skill_fletching/scripts/ogre_arrows.rs2:144 "
            "stat_advance(fletching, multiply($arrow_count, 10))",
    ),
    dict(
        key="smith_cannonballs", skill="smithing", level=35, xp=37.5,
        label="Cast steel into cannonballs",
        inp=[("steel_bar", 1)], out=[("mcannonball", 4)], tools=["ammo_mould"],
        src="scripts/skill_smithing/scripts/smelting/cannonballs.rs2:42 "
            "stat_advance(smithing, 375)",
    ),
    # The one smithing action that is not on the anvil table. Both halves plus
    # a hammer, and the script gates on level 60 and nothing else — no quest
    # check in build 274, whatever later versions require.
    dict(
        key="smith_dragon_sq_shield", skill="smithing", level=60, xp=75.0,
        label="Repair the dragon square shield",
        inp=[("dragonshield_a", 1), ("dragonshield_b", 1)],
        out=[("dragon_sq_shield", 1)], tools=["hammer"],
        src="scripts/skill_smithing/scripts/smithing/dragon_sq.rs2:53 "
            "stat_advance(smithing, 750)",
    ),
]

# Amulet stringing is a single hardcoded 4 xp for every amulet
# (stringing.rs2:70), applied to whichever jewellery structs declare a `strung`
# counterpart — so the xp is a literal but the recipe list is still extracted.
STRINGING_XP = 4.0
STRINGING_SRC = ("scripts/skill_crafting/scripts/jewellery/stringing.rs2:70 "
                 "stat_advance(crafting, 40)")


# ---------------------------------------------------------------------------
# Recipe accumulator
# ---------------------------------------------------------------------------

class Recipes:
    def __init__(self, content):
        self.c = content
        self.out = {}
        self.counts = {}

    def add(self, key, *, skill, label, level, xp, inp, out, src,
            tools=(), buy=(), chance=None, note=None, extra=None):
        if key in self.out:
            raise BuildError(f"duplicate recipe key {key!r}")
        if xp is None:
            raise BuildError(f"{key}: no xp found")
        rec = {
            "skill": skill,
            "label": label,
            "level": int(level or 1),
            "xp": xp,
            "in": [{"id": self.c.oid(s), "n": n} for s, n in inp],
            "out": [{"id": self.c.oid(s), "n": n} for s, n in out],
            "src": src,
        }
        if tools:
            rec["tools"] = [self.c.oid(t) for t in tools]
        if buy:
            rec["buy"] = [self.c.oid(b) for b in buy]
        if chance is not None:
            rec["chance"] = chance
        if note:
            rec["note"] = note
        if extra:
            rec.update(extra)
        self.out[key] = rec
        self.counts[skill] = self.counts.get(skill, 0) + 1


# ---------------------------------------------------------------------------
# Handlers — one per consuming script, each citing what it read
# ---------------------------------------------------------------------------

def h_fletching_logs(c, r):
    """
    fletch_bow_table, read by skill_fletching/scripts/cut_logs.rs2.

    One log in (`inv_del(inv, $log, 1)`), one of three products out. The shafts
    branch is the odd one: its xp is computed as `multiply($shaft_count, 5)`
    rather than read from a column, and its product count is a real yield.
    """
    for name, rel, kv in c.rows("fletch_bow_table"):
        log = one(kv, "log")
        shafts = one(kv, "shafts")
        if shafts and int(shafts) > 0:
            n = int(shafts)
            r.add(
                f"fletch_shafts_from_{log}", skill="fletching", level=1,
                xp=round(n * 5 / 10, 1),
                label=f"Cut {c.obj_name(log).lower()} into arrow shafts",
                inp=[(log, 1)], out=[("arrow_shaft", n)], tools=["knife"],
                src=f"{rel}#{name}",
                note="xp is multiply($shaft_count, 5) in cut_logs.rs2:88, "
                     "not a table column",
            )
        for col in ("shortbow", "longbow"):
            got = vals(kv, col)
            if not got:
                continue
            product, level, exp = got[0][0], got[0][1], got[0][2]
            r.add(
                f"fletch_cut_{product}", skill="fletching", level=int(level),
                xp=tenths(exp),
                label=f"Cut {c.obj_name(log).lower()} into {col}s",
                inp=[(log, 1)], out=[(product, 1)], tools=["knife"],
                src=f"{rel}#{name}",
            )


def h_fletching_table(c, r):
    """
    fletching_table is read by four different scripts. Which one a row belongs
    to is decided by the folder it lives in — Content groups them that way —
    except in bolts.dbrow, where the gem rows go to a different handler and
    the product count flips meaning.
    """
    for name, rel, kv in c.rows("fletching_table"):
        item = one(kv, "item")
        product_row = vals(kv, "product")[0]
        product = product_row[0]
        batch = int(product_row[1]) if len(product_row) > 1 else 1
        level = int(one(kv, "level", default=1))
        xp = tenths(one(kv, "experience"))
        cap_note = f"the product column's {batch} is a per-click batch cap, not a yield"

        if "/stringing/" in rel:
            # bows.rs2:38-39 — one unstrung bow and one bow string per action.
            r.add(
                f"fletch_string_{product}", skill="fletching", level=level, xp=xp,
                label=f"String {c.obj_name(product).lower()}",
                inp=[(item, 1), ("bow_string", 1)], out=[(product, 1)],
                src=f"{rel}#{name}", note=CO_INPUT_SRC["bow_string"],
            )
        elif "/arrows/" in rel:
            r.add(
                f"fletch_{product}", skill="fletching", level=level, xp=xp,
                label=f"Attach {c.obj_name(item).lower()} to headless arrows",
                inp=[(item, 1), ("headless_arrow", 1)], out=[(product, 1)],
                src=f"{rel}#{name}",
                note=f"{cap_note}; {CO_INPUT_SRC['headless_arrow']}",
            )
        elif "/darts/" in rel:
            r.add(
                f"fletch_{product}", skill="fletching", level=level, xp=xp,
                label=f"Fletch {c.obj_name(product).lower()}s",
                inp=[(item, 1), ("feather", 1)], out=[(product, 1)],
                src=f"{rel}#{name}",
                note=f"{cap_note}; {CO_INPUT_SRC['feather']}",
            )
        elif "/bolts/" in rel:
            if item in BOLT_TIP_INPUTS:
                # uncut_gem.rs2 -> make_bolt_tips, where "// includes count"
                # (bolts.rs2:34) means the count IS the yield: one gem in,
                # `batch` tips out, flat xp.
                r.add(
                    f"fletch_{product}_from_{item}", skill="fletching",
                    level=level, xp=xp,
                    label=f"Cut {c.obj_name(item).lower()} into bolt tips",
                    inp=[(item, 1)], out=[(product, batch)], tools=["chisel"],
                    src=f"{rel}#{name}", note=BOLT_TIP_SRC,
                )
            else:
                r.add(
                    f"fletch_{product}", skill="fletching", level=level, xp=xp,
                    label=f"Tip bolts with {c.obj_name(item).lower()}",
                    inp=[(item, 1), ("bolt", 1)], out=[(product, 1)],
                    src=f"{rel}#{name}",
                    note=f"{cap_note}; {CO_INPUT_SRC['bolt']}",
                )
        else:
            raise BuildError(f"fletching_table row in an unrecognised folder: {rel}#{name}")


def h_firemaking(c, r):
    """
    Logs carry their own firemaking xp: firemaking.rs2:121 reads
    `oc_param($log, productexp)`, with the level gate from `levelrequire`.
    """
    for slug, (rel, kv) in sorted(c.objs.items()):
        exp = param(kv, "productexp")
        if exp is None:
            continue
        r.add(
            f"burn_{slug}", skill="firemaking",
            level=int(param(kv, "levelrequire", 1)), xp=tenths(exp),
            label=f"Burn {c.obj_name(slug).lower()}",
            inp=[(slug, 1)], out=[("ashes", 1)], tools=["tinderbox"],
            src=f"{rel}#{slug} param=productexp",
        )


def h_prayer(c, r):
    """
    Bones carry `bone_exp`; bury_bone.rs2:15 deletes one and grants it. The
    tutorial's copy of the bones config is skipped — same items, thinner rows.
    """
    for slug, (rel, kv) in sorted(c.objs.items()):
        exp = param(kv, "bone_exp")
        if exp is None or "/tutorial/" in rel:
            continue
        r.add(
            f"bury_{slug}", skill="prayer", level=1, xp=tenths(exp),
            label=f"Bury {c.obj_name(slug).lower()}",
            inp=[(slug, 1)], out=[],
            src=f"{rel}#{slug} param=bone_exp",
        )


def h_smelting(c, r):
    """
    smelting.struct carries a complete recipe — both ingredients with counts,
    the product and the xp — so nothing here is inferred.

    Iron is why the schema needs `chance`: smelting.rs2:200 rolls
    `randominc(1)` and on a miss consumes the ore for no bar and no xp.

    But read the whole branch, not just the roll. The `else` is the second
    half of an `if`, and the first half is a ring of forging:

        if (inv_total(worn, ring_of_forging) > 0 & map_members = ^true) {
            ~lose_charge_ring_of_forging;
        } else if (randominc(1) = 1) { ... fail ... }

    Wearing one removes the roll outright — no reduced chance, no roll at all —
    and nobody smelts iron without one, because the ring is a ruby ring and an
    enchant. So the odds are recorded (they are what Content says) and the
    recipe also carries what cancels them, which is what the solve actually
    models. The ring is not free: ring_of_forging.rs2:5 melts it at 140
    charges, so a plan says how many rings it takes.
    """
    for name, rel, kv in c.structs_in("smelting"):
        product = param(kv, "product")
        exp = param(kv, "productexp")
        if product is None or exp is None:
            continue
        inp = [(param(kv, "ingredient"), int(param(kv, "bar_count", 1)))]
        second = param(kv, "ingredient_secondary")
        if second:
            inp.append((second, int(param(kv, "ingredient_secondary_count", 1))))
        iron = product == "iron_bar"
        r.add(
            f"smelt_{product}", skill="smithing",
            level=int(param(kv, "levelrequired", 1)), xp=tenths(exp),
            label=f"Smelt {c.obj_name(product).lower()}",
            inp=inp, out=[(product, 1)], src=f"{rel}#{name}",
            chance={
                "kind": "flat", "p": 0.5,
                "mitigatedBy": {"item": c.oid(RING_OF_FORGING), "uses": RING_CHARGES},
            } if iron else None,
            note="50% failure bare-handed (smelting.rs2:202 randominc(1)), but "
                 "a ring of forging skips the roll entirely (smelting.rs2:200) "
                 "and melts after 140 smelts (ring_of_forging.rs2:5)"
                 if iron else None,
        )


def h_smithing_anvil(c, r):
    """
    smithing.dbrow says how many bars a product takes; the xp per bar lives on
    the bar's own `smithing_anvil_struct` (smithing.rs2:285). So every product
    made from a given bar pays the same xp per bar — what you choose to hammer
    changes the gp, never the xp.
    """
    bar_struct = c.struct_owners("smithing_anvil_struct")
    bar_struct = {slug: name for name, slug in bar_struct.items()}

    for name, rel, kv in c.rows("smithing"):
        bar = one(kv, "bar")
        bar_amount = int(one(kv, "bar_amount", default=1))
        product = one(kv, "product")
        product_amount = int(one(kv, "product_amount", default=1))
        if bar not in bar_struct:
            raise BuildError(f"{rel}#{name}: bar {bar!r} has no smithing_anvil_struct")
        srel, skv = c.structs[bar_struct[bar]]
        xp_per_bar = tenths(param(skv, "xpperbar"))
        r.add(
            f"smith_{name}", skill="smithing",
            level=int(one(kv, "levelrequired", default=1)),
            xp=round(xp_per_bar * bar_amount, 1),
            label=f"Smith {c.obj_name(product).lower()}",
            inp=[(bar, bar_amount)], out=[(product, product_amount)],
            tools=["hammer"],
            src=f"{rel}#{name} + {srel}#{bar_struct[bar]} param=xpperbar",
        )


def h_gem_cutting(c, r):
    """
    gem_cutting_table. Rows carrying `success_rate` can smash the gem for a
    quarter of the xp (uncut_gem.rs2:54), so the roll is recorded rather than
    the recipe being presented as certain; the four precious gems have no roll.
    """
    for name, rel, kv in c.rows("gem_cutting_table"):
        uncut = one(kv, "uncut_gem")
        cut = one(kv, "cut_gem")
        rate = vals(kv, "success_rate")
        r.add(
            f"craft_cut_{cut}", skill="crafting",
            level=int(one(kv, "level", default=1)),
            xp=tenths(one(kv, "experience")),
            label=f"Cut {c.obj_name(uncut).lower()}",
            inp=[(uncut, 1)], out=[(cut, 1)], tools=["chisel"],
            src=f"{rel}#{name}",
            chance=None if not rate else
                   {"kind": "level", "low": int(rate[0][0]),
                    "high": int(rate[0][1]), "quarterOnMiss": True},
            note=None if not rate else
                 "a miss smashes the gem into crushed gemstone for a quarter "
                 "of the xp (uncut_gem.rs2:54)",
        )


def h_tanning(c, r):
    """
    Raw hide -> tanned leather. Pays nothing and costs coins, so it is not a
    recipe in the xp sense — but it is the only way a bank of dragonhide
    reaches the crafting table, and leaving it out made 700 green dragonhide
    read as worth zero Crafting xp.

    Filed under crafting so the chain walk can use it: the solve is per skill,
    and a conversion step is only reachable by the skill it feeds.
    """
    for hide, leather, fee in TANNING:
        r.add(
            f"tan_{hide}_to_{leather}", skill="crafting", level=1, xp=0.0,
            label=f"Tan {c.obj_name(hide).lower()} into {c.obj_name(leather).lower()}",
            inp=[(hide, 1)], out=[(leather, 1)],
            src=TANNING_SRC, extra={"fee": fee},
            note=f"no xp — the tanner charges {fee} gp a hide, and every "
                 f"leather recipe needs it done first",
        )


def h_prep_steps(c, r):
    """
    The zero-xp conversions pottery and glassblowing are gated behind.

    Sibling of h_tanning, and there for exactly the same reason: these pay
    nothing, so they are not recipes in the xp sense, but every recipe
    downstream needs them done. Leaving them out made 1,000 clay read as worth
    zero Crafting xp when it is 33,000, and 1,000 empty buckets plus soda ash
    read as zero when it is 72,500.

    Filed under crafting so the chain walk can reach them — the solve is per
    skill, and a conversion step is only reachable by the skill it feeds.
    """
    for water in SOFT_CLAY_WATER:
        empty = c.obj_param(water, "next_obj_stage")
        if not empty:
            raise BuildError(f"{water} has no next_obj_stage param — moved?")
        r.add(
            f"craft_soften_clay_{water}", skill="crafting", level=1, xp=0.0,
            label=f"Mix clay with {c.obj_name(water).lower()}",
            inp=[("clay", 1), (water, 1)],
            out=[("softclay", 1), (empty, 1)],
            src=SOFT_CLAY_SRC,
            note="no xp — but every pottery recipe needs soft clay, and the "
                 "container comes back empty",
        )
    r.add(
        "craft_fill_bucket_sand", skill="crafting", level=1, xp=0.0,
        label="Fill a bucket at a sand pit",
        inp=[("bucket_empty", 1)], out=[("bucket_sand", 1)],
        src=SAND_FILL_SRC,
        note="no xp and no cost — the sand is free, but molten glass cannot "
             "be made without it",
    )


def h_leather(c, r):
    """craft_leather_table. The `leather` column carries its own count."""
    for name, rel, kv in c.rows("craft_leather_table"):
        hide_row = vals(kv, "leather")[0]
        hide, count = hide_row[0], int(hide_row[1])
        product = one(kv, "product")
        r.add(
            f"craft_{name}", skill="crafting",
            level=int(one(kv, "levelrequired", default=1)),
            xp=tenths(one(kv, "productexp")),
            label=f"Craft {c.obj_name(product).lower()}",
            inp=[(hide, count)], out=[(product, 1)], tools=["needle", "thread"],
            src=f"{rel}#{name}",
            note="thread is consumed once per 5 items (leather.rs2:126)",
        )


def h_struct_pairs(c, r):
    """
    The plain one-in-one-out struct families: spinning, battlestaves, studded.
    Each names its own `ingredient` and `product`; the only thing the scripts
    add is a co-input (studs, a battlestaff) or nothing at all.

    Battlestaves are the reason to read the script rather than trust the
    struct. `battlestaves.struct` lists the orb as the whole recipe, but
    `craft_staff` deletes a battlestaff alongside it — a 7,000 gp shop item
    that dwarfs everything else in the step. The first build missed it and
    reported the xp as though the staves were free.
    """
    families = [
        ("spinning", "levelrequire", [], "Spin"),
        ("battlestaves", "levelrequire", ["battlestaff"], "Make"),
        ("studded", "levelrequired", ["studs"], "Make"),
    ]
    for folder, level_key, co, verb in families:
        for name, rel, kv in c.structs_in(folder):
            ingredient = param(kv, "ingredient")
            product = param(kv, "product")
            exp = param(kv, "productexp")
            if not (ingredient and product and exp):
                continue
            notes = [CO_INPUT_SRC[x] for x in co]
            notes += [f"{x} is shop stock: {SHOP_BOUGHT[x]}"
                      for x in co if x in SHOP_BOUGHT]
            r.add(
                f"craft_{name}", skill="crafting",
                level=int(param(kv, level_key, 1)), xp=tenths(exp),
                label=f"{verb} {c.obj_name(product).lower()}",
                inp=[(ingredient, 1)] + [(x, 1) for x in co], out=[(product, 1)],
                buy=[x for x in co if x in SHOP_BOUGHT],
                src=f"{rel}#{name}",
                note="; ".join(notes) or None,
            )


def h_glassblowing(c, r):
    """glass.struct — one molten glass each (glass.rs2:99), plus the pipe."""
    for name, rel, kv in c.structs_in("glass"):
        product = param(kv, "product")
        exp = param(kv, "productexp")
        if not (product and exp):
            continue
        r.add(
            f"craft_blow_{product}", skill="crafting",
            level=int(param(kv, "levelrequire", 1)), xp=tenths(exp),
            label=f"Blow {c.obj_name(product).lower()}",
            inp=[("molten_glass", 1)], out=[(product, 1)],
            tools=["glassblowingpipe"], src=f"{rel}#{name}",
        )


def h_pottery(c, r):
    """
    pottery.struct. Two steps: the wheel turns soft clay into an unfired item
    (`processexp`, deterministic), the oven fires it (`productexp`) on a
    `stat_random(crafting, 180, 800)` roll that cracks the item on a miss.

    Which unfired item belongs to which struct is not in the struct — it is on
    the item, as `param=crafting_pottery_struct`. Read it back from there
    rather than pattern-matching the names.
    """
    owners = c.struct_owners("crafting_pottery_struct")
    for name, rel, kv in c.structs_in("pottery"):
        product = param(kv, "product")
        if not product:
            continue  # the soft_clay struct is just a message
        if name not in owners:
            raise BuildError(f"no obj carries crafting_pottery_struct,{name}")
        unfired = owners[name]
        process = param(kv, "processexp")
        plural = param(kv, "pottery_name", "items")
        if process:
            r.add(
                f"craft_shape_{name}", skill="crafting",
                level=int(param(kv, "levelrequire", 1)), xp=tenths(process),
                label=f"Shape soft clay into {plural}",
                inp=[("softclay", 1)], out=[(unfired, 1)],
                src=f"{rel}#{name} param=processexp + "
                    f"{c.objs[unfired][0]}#{unfired} param=crafting_pottery_struct",
            )
        exp = param(kv, "productexp")
        if exp:
            r.add(
                f"craft_fire_{name}", skill="crafting",
                level=int(param(kv, "levelrequire", 1)), xp=tenths(exp),
                label=f"Fire {plural} in an oven",
                inp=[(unfired, 1)], out=[(product, 1)],
                src=f"{rel}#{name} param=productexp",
                chance={"kind": "level", "low": 180, "high": 800},
                note="a miss cracks the item for no xp (pottery.rs2:151)",
            )


def h_jewellery(c, r):
    """
    jewellery.struct. A gold bar plus an optional gem, or a silver bar for the
    three symbols; that split is not in the data, so SILVER_STRUCTS carries it
    with a citation.
    """
    for name, rel, kv in c.structs_in("jewellery"):
        product = param(kv, "product")
        exp = param(kv, "productexp")
        if not (product and exp):
            continue
        silver = name in SILVER_STRUCTS
        inp = [("silver_bar" if silver else "gold_bar", 1)]
        gem = param(kv, "gem")
        if gem:
            inp.append((gem, 1))
        mould = param(kv, "mould")
        r.add(
            f"craft_{name}", skill="crafting",
            level=int(param(kv, "levelrequired", 1)), xp=tenths(exp),
            label=f"Make {c.obj_name(product).lower()}",
            inp=inp, out=[(product, 1)], tools=[mould] if mould else [],
            src=f"{rel}#{name}", note=SILVER_SRC if silver else None,
        )

    # Stringing: one flat 4 xp for every amulet (stringing.rs2:70), applied to
    # whichever structs declare a `strung` counterpart.
    for name, rel, kv in c.structs_in("jewellery"):
        strung = param(kv, "strung")
        unstrung = param(kv, "product")
        if not (strung and unstrung):
            continue
        r.add(
            f"craft_string_{unstrung}", skill="crafting", level=1,
            xp=STRINGING_XP,
            label=f"String {c.obj_name(strung).lower()}",
            inp=[(unstrung, 1), ("ball_of_wool", 1)], out=[(strung, 1)],
            src=f"{STRINGING_SRC} + {rel}#{name}",
            note=CO_INPUT_SRC["ball_of_wool"],
        )


def h_herblore(c, r):
    """
    Identify: identify.rs2 maps each unid to its herb, and the *identified*
    herb carries the xp. Brewing: every brew_potion.struct block is a complete
    recipe (ingredient + solvent -> mixture). Unfinished potions carry no
    `brew_potion_exp` and so pay nothing, which is correct — the xp all lands
    on the second step.
    """
    ident_path = "scripts/skill_herblore/scripts/identifying/identify.rs2"
    ident = c.tree.get(ident_path)
    if ident is None:
        raise BuildError(f"{ident_path} not found")
    pairs = re.findall(
        r"\[opheld1,(\w+)\]\s*\n\s*~attempt_identify_herb\((\w+),", ident)
    if not pairs:
        raise BuildError("identify.rs2 parsed to zero herb pairs")
    for unid, herb in pairs:
        if herb not in c.objs:
            raise BuildError(f"identify.rs2 names an unknown herb: {herb!r}")
        hrel, hkv = c.objs[herb]
        exp = param(hkv, "identified_herb_exp")
        if not exp:
            continue
        r.add(
            f"herb_identify_{herb}", skill="herblore",
            level=int(param(hkv, "identified_herb_level", 3)), xp=tenths(exp),
            label=f"Identify {c.obj_name(herb).lower()}",
            inp=[(unid, 1)], out=[(herb, 1)],
            src=f"{ident_path} + {hrel}#{herb} param=identified_herb_exp",
        )

    for name, rel, kv in c.structs_in("brewing"):
        mixture = param(kv, "brew_potion_mixture")
        ingredient = param(kv, "brew_potion_ingredient")
        solvent = param(kv, "brew_potion_solvent")
        exp = param(kv, "brew_potion_exp")
        if not (mixture and ingredient and solvent):
            continue
        if not exp or int(exp) == 0:
            continue
        r.add(
            f"brew_{name}", skill="herblore",
            level=int(param(kv, "brew_potion_level", 3)), xp=tenths(exp),
            label=f"Brew {c.obj_name(mixture).lower()}",
            inp=[(ingredient, 1), (solvent, 1)], out=[(mixture, 1)],
            src=f"{rel}#{name}",
        )


def h_runecraft(c, r):
    """
    runecraft_table. One essence per cast and the xp is flat per essence — but
    the rune *yield* scales with level as `level / multiplier + 1`
    (runecraft.rs2:83), so the divisor is passed through for the report to
    evaluate against the player's real level rather than baked in at 1.
    """
    for name, rel, kv in c.rows("runecraft_table"):
        if name in UNRELEASED:
            SKIPPED_UNRELEASED.add(name)
            continue
        rune = one(kv, "rune")
        talisman = one(kv, "talisman")
        mult = one(kv, "multiplier")
        r.add(
            f"rc_{rune}", skill="runecraft",
            level=int(one(kv, "level", default=1)),
            xp=tenths(one(kv, "experience")),
            label=f"Bind {c.obj_name(rune).lower()}s",
            inp=[("blankrune", 1)], out=[(rune, 1)],
            tools=[talisman] if talisman else [],
            src=f"{rel}#{name}",
            extra={"yieldPerLevel": int(mult)} if mult else None,
            note=f"runes per essence is level/{mult} + 1 (runecraft.rs2:83); "
                 f"the xp is per essence either way" if mult else None,
        )


def h_magic(c, r):
    """
    magic_spell_table. Enchanting names its exact input and output in
    `convertobj`, so those are ordinary recipes. Alchemy names only its runes —
    the target is any alchable item — so it is flagged `anyItem` and the report
    picks that target out of the bank rather than this file inventing one.
    """
    # alchemy.rs2:25 / :63 — `max(scale(6, 10, oc_cost($item)), 1)` coins for
    # high, four tenths for low. The rate travels with the recipe so the report
    # can say what the casts pay for, rather than hardcoding 0.6 in the browser.
    any_item = {
        "magic_spell_low_alch": ("Low alchemy", 0.4),
        "magic_spell_high_alch": ("High alchemy", 0.6),
    }
    for name, rel, kv in c.rows("magic_spell_table"):
        exp = one(kv, "experience")
        if not exp or int(exp) == 0:
            continue
        rune_in = []
        runes = vals(kv, "runesrequired")
        if runes:
            fields = runes[0]
            for i in range(0, len(fields) - 1, 2):
                slug, n = fields[i], fields[i + 1]
                if slug and slug != "null":
                    rune_in.append((slug, int(n)))
        level = int(one(kv, "levelrequired", default=1))

        if name in any_item:
            label, rate = any_item[name]
            r.add(
                f"magic_{name}", skill="magic", level=level, xp=tenths(exp),
                label=label, inp=rune_in, out=[],
                src=f"{rel}#{name}",
                extra={"anyItem": True, "alchRate": rate},
                note="also consumes one alchable item per cast, paying "
                     f"{rate:g}x its cost in coins (alchemy.rs2:25); the "
                     "report picks that target from the bank",
            )
            continue

        for conv in vals(kv, "convertobj"):
            if len(conv) < 2 or conv[0] == "null":
                continue
            target, product = conv[0], conv[1]
            r.add(
                f"magic_{name}_{target}", skill="magic", level=level,
                xp=tenths(exp),
                label=f"Enchant {c.obj_name(target).lower()}",
                inp=[(target, 1)] + rune_in, out=[(product, 1)],
                src=f"{rel}#{name} data=convertobj",
            )


def h_literals(c, r):
    """Shape 4: xp literals read out of .rs2 bodies, each cited in LITERALS."""
    for lit in LITERALS:
        r.add(
            lit["key"], skill=lit["skill"], level=lit["level"], xp=lit["xp"],
            label=lit["label"], inp=lit["inp"], out=lit["out"],
            tools=lit.get("tools", ()), src=lit["src"],
            chance=lit.get("chance"), note=lit.get("note"),
            extra={"quest": lit["quest"]} if lit.get("quest") else None,
        )


HANDLERS = [
    h_fletching_logs, h_fletching_table, h_firemaking, h_prayer,
    h_smelting, h_smithing_anvil, h_gem_cutting, h_tanning, h_prep_steps,
    h_leather, h_struct_pairs,
    h_glassblowing, h_pottery, h_jewellery, h_herblore, h_runecraft, h_magic,
    h_literals,
]

# Individual recipes deliberately left out of covered skills. These are the
# dangerous omissions: a whole missing skill is obvious, but a missing recipe
# inside a skill that otherwise works just makes a number smaller and nobody
# notices. Listed here, shipped in the data file, and shown in the UI.
KNOWN_GAPS = [
    "Superheat item (magic_spells.dbrow#magic_spell_superheat) smelts an ore "
    "and pays Magic xp *and* Smithing xp off one cast — two skills from one "
    "action, which this schema's one-skill-per-recipe shape cannot express.",

    "Chiselling wolf bones into arrow tips pays Fletching *and* Crafting off "
    "one action (ogre_arrows.rs2:66-67). Only the Fletching half is counted, "
    "for the same reason superheat is missing entirely.",

    "Cooking recipes that are not dbrow-driven — wine, pizza, cakes, gnome "
    "cooking — are out with the rest of cooking, but note they are separate "
    "scripts, so covering cooking later means more than one table.",

    "One-off crafting scripts with a hardcoded xp literal and no config: "
    "cape dyeing (dye_cape.rs2:120, 2.5 xp) and snelm carving "
    "(snelm.rs2:15, 32.5 xp).",

    "Bones to bananas (magic_spells.dbrow#magic_spell_bones_to_bananas) pays "
    "25 xp per cast and converts every bone you are carrying in that one cast "
    "(convert_bones.rs2:30 deletes inv_total(inv, bones)). The xp is per cast "
    "and the bones are not, so there is no honest bones-per-action number to "
    "put in a recipe — modelling it as one bone per cast would report a bank "
    "of bones as roughly 26x the Magic xp it is worth.",
]

# Skills deliberately left out, with the reason. Written into the data file so
# the report can say what it does not cover, instead of quietly reporting a
# smaller number.
NOT_COVERED = {
    "cooking": "every recipe carries a burn roll (successchance in "
               "cooking_generic.dbrow), so a total would be an expectation "
               "dressed up as a count",
    "woodcutting": "gathered from trees, not made from bank stock",
    "mining": "gathered from rocks, not made from bank stock",
    "fishing": "gathered from spots, not made from bank stock",
    "agility": "no item input",
    "thieving": "no item input",
    "combat": "no item input",
}


# Which Content skill folder feeds which extracted skill. Used by
# check_deletions to ask "this script eats an item — does any recipe of its
# skill know about that?"
SKILL_FOLDERS = {
    "skill_fletching": "fletching", "skill_crafting": "crafting",
    "skill_smithing": "smithing", "skill_herblore": "herblore",
    "skill_firemaking": "firemaking", "skill_runecraft": "runecraft",
    "skill_prayer": "prayer", "skill_magic": "magic",
}

# Deletions check_deletions is expected to find, with why they are not recipes.
# Everything NOT on this list that the check reports is a missing ingredient or
# a missing recipe, which is the whole point of the check.
EXPECTED_DELETIONS = {
    ("crafting", "viking_golden_fleece"):
        "The Fremennik Trials — spinning the golden fleece is a quest step, "
        "not a repeatable recipe (spinning.rs2:25).",
    ("herblore", "empty_dye_bottle"):
        "A quest item consumed by the grinder, not an ingredient "
        "(grind_ingredient.rs2:73).",
    ("magic", "bones"):
        "Bones to bananas — see KNOWN_GAPS; the xp is per cast and the bones "
        "are not, so there is no per-action number to record.",
    ("magic", "karamja_rum"): "Teleporting destroys smuggled rum. Not a recipe.",
    ("magic", "plaguesample"): "Teleporting destroys the plague sample.",
    ("magic", "thanainabarrel"): "Teleporting destroys the barrel of thanaina.",
}

INV_DEL_RE = re.compile(r"inv_del\(\s*inv\s*,\s*([a-z0-9_]+)\s*,")


def check_deletions(content, recipes):
    """
    Warn about any item a skill script consumes that no recipe of that skill
    names as an ingredient.

    This is the check that would have caught battlestaves. `battlestaves.struct`
    lists only the orb, so the extracted recipe was free; the 7,000 gp staff was
    deleted three lines into the script and appeared nowhere in the data file.
    A user found it, which is one user too many — the whole failure mode of a
    missing ingredient is that it makes a number *better* and nobody looks
    twice.

    Only literal deletions are checked: `inv_del(inv, battlestaff, 1)` yes,
    `inv_del(inv, struct_param($struct, ingredient), 1)` no, because the latter
    is exactly the config-driven path already being extracted. That keeps the
    signal high — the whole tree yields a handful of hits, and every one of
    them is either a real gap or an entry in EXPECTED_DELETIONS with a reason.

    A warning rather than an error, same as check_tool_sources: quest scripts
    live in these folders too, and a false positive should not block a rebuild.
    """
    by_id = {gid: slug for slug, gid in content.slug_to_id.items()}
    known = {}  # skill -> set of slugs the recipes already account for
    for r in recipes.values():
        seen = known.setdefault(r["skill"], set())
        for slot in r["in"]:
            seen.add(by_id.get(slot["id"]))
        for tool in r.get("tools", ()):
            seen.add(by_id.get(tool))

    found = {}
    for rel, text in content.tree.items():
        if not rel.endswith(".rs2") or "/_test/" in rel:
            continue
        parts = rel.split("/")
        skill = next((SKILL_FOLDERS[part] for part in parts
                      if part in SKILL_FOLDERS), None)
        if not skill:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for slug in INV_DEL_RE.findall(line):
                if slug in known.get(skill, ()):
                    continue
                if slug not in content.slug_to_id:
                    continue  # a local variable name, not an item
                if (skill, slug) in EXPECTED_DELETIONS:
                    continue
                found.setdefault((skill, slug), f"{rel}:{lineno}")

    if found:
        # Plain ASCII, same reason as check_tool_sources: this line has to
        # survive a console with a legacy codepage.
        print("\n  WARNING: skill scripts delete items no recipe of that "
              "skill names - missing ingredient, or missing recipe:", flush=True)
        for (skill, slug), where in sorted(found.items()):
            print(f"    {skill:<11} {slug:<24} {where}", flush=True)
    return found


def check_tool_sources(content, recipes):
    """
    Warn about any tool a recipe requires that nothing in the game can give you.

    This is the check that caught death runecrafting: `death_talisman` is
    required by a real config row, but the only places the slug appears are its
    own item definition and a test cheat. A recipe gated behind an item with no
    source is a recipe no player can do.

    A warning rather than an error, because it is a grep heuristic and a false
    positive should not block a rebuild — but a new one means a row wants
    looking at, and probably an entry in UNRELEASED.
    """
    tools = sorted({t for r in recipes.values() for t in r.get("tools", ())})
    by_id = {gid: slug for slug, gid in content.slug_to_id.items()}
    orphans = []
    for gid in tools:
        slug = by_id.get(gid)
        if not slug:
            continue
        pattern = re.compile(r"\b" + re.escape(slug) + r"\b")
        found = False
        for rel, text in content.tree.items():
            # .obj/.param/.dbtable say what an item is, not where it comes
            # from; /_test/ is cheat commands, not the game.
            if "/_test/" in rel or rel.endswith((".obj", ".param", ".dbtable")):
                continue
            # The table that *requires* the tool is not a way to obtain it.
            if rel.endswith(".dbrow") and pattern.search(text):
                continue
            if pattern.search(text):
                found = True
                break
        if not found:
            orphans.append(slug)
    if orphans:
        # Plain ASCII: this is the one line that must survive being printed to
        # a console with a legacy codepage, which is where a warning gets read.
        print("\n  WARNING: tools with no source in Content - the recipes "
              "needing them may be unreleased:", flush=True)
        for slug in orphans:
            print(f"    {slug}", flush=True)
    return orphans


def main():
    DATA_DIR.mkdir(exist_ok=True)
    obj_pack_text, tree = fetch_content_tree()
    content = Content(obj_pack_text, tree)
    print(f"  {len(content.slug_to_id)} item ids, {len(content.structs)} structs, "
          f"{len(content.dbrows)} dbrows", flush=True)

    recipes = Recipes(content)
    for handler in HANDLERS:
        before = len(recipes.out)
        handler(content, recipes)
        print(f"  {handler.__name__:20} +{len(recipes.out) - before}", flush=True)

    # A stale exclusion is as bad as a missing one: if a row named in
    # UNRELEASED is gone, the note about it is now describing nothing.
    missed = set(UNRELEASED) - SKIPPED_UNRELEASED
    if missed:
        raise BuildError(
            f"UNRELEASED names rows that no longer exist: {sorted(missed)}. "
            "Either Content moved them or they finally shipped — check before "
            "deleting the entry."
        )
    check_tool_sources(content, recipes.out)
    check_deletions(content, recipes.out)

    # Items alchemy refuses, so the alch plan cannot quietly eat them:
    # anything carrying param=no_alchemy, plus coins themselves
    # ("Coins are already made of gold." — alchemy.rs2:91).
    no_alch = {content.oid("coins")}
    for slug, (_rel, kv) in content.objs.items():
        if param(kv, "no_alchemy") and slug in content.slug_to_id:
            no_alch.add(content.oid(slug))

    payload = {
        "meta": {
            "contentBuild": CONTENT_BUILD,
            "noAlch": sorted(no_alch),
            "source": "https://github.com/LostCityRS/Content",
            "count": len(recipes.out),
            "bySkill": dict(sorted(recipes.counts.items())),
            "notCovered": NOT_COVERED,
            "knownGaps": KNOWN_GAPS,
            "unreleased": UNRELEASED,
            "note": "xp is real xp; Content stores tenths and this build "
                    "divides them out. `chance` marks a recipe whose outcome "
                    "is a roll — {kind:flat} is a fixed probability, "
                    "{kind:level,low,high} scales with the player's level.",
        },
        "recipes": recipes.out,
    }

    print(f"\nDone: {len(recipes.out)} recipes", flush=True)
    for skill, n in sorted(recipes.counts.items(), key=lambda kv: -kv[1]):
        print(f"    {skill:12} {n}", flush=True)

    RECIPES_PATH.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {RECIPES_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\nFATAL ERROR: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
