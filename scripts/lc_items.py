#!/usr/bin/env python3
"""
lc_items.py — item classification and dose normalization.

Category rules are pure functions of slug/name, so the whole catalog is
re-derived on every scraper run (a rules change must propagate to items
that haven't traded recently).
"""

import re

# Substring containment (not strict endswith) so gilded/trimmed/(g) variants
# like "adamant_kiteshield_gold" or "black_platebody_trim" still match on
# their base equipment-slot fragment.
EQUIP_KEYWORDS = (
    "dagger", "sword", "scimitar", "battleaxe", "_axe", "mace", "warhammer",
    "hammer", "spear", "halberd", "claws", "hatchet", "pickaxe", "full_helm",
    "med_helm", "helm", "platebody", "platelegs", "plateskirt", "chainbody",
    "chainmail", "sq_shield", "square_shield", "kiteshield", "boots",
    "gauntlets", "gloves", "shield", "bow", "crossbow", "staff", "wand",
    "amulet", "ring_of", "necklace", "cape", "cavalier", "headband",
    "hat", "trim", "_gold", "robe", "vambraces", "coif", "apron", "mask",
    "partyhat", "halo", "boater", "scarf", "cane", "sceptre",
)
AMMO_KEYWORDS = ("arrow", "bolt", "dart", "javelin", "throwing", "cannonball")

# Weapons get their own category — melee, ranged, staves, cannon parts.
WEAPON_KEYWORDS = (
    "dagger", "sword", "scimitar", "battleaxe", "_axe", "mace", "warhammer",
    "spear", "halberd", "claws", "hatchet", "pickaxe", "whip", "flail",
    "staff", "wand", "shortbow", "longbow", "crossbow", "ogre_bow",
    "crystal_bow", "seercull", "sceptre", "godsword",
    "mcannon", "dragonfire",
)
# Jewellery: rings, amulets, necklaces, holy symbols and emblems.
JEWEL_KEYWORDS = (
    "ring_of", "amulet", "necklace", "holy_symbol", "unholy_symbol",
    "_emblem", "symbol_of",
)
JEWEL_RING_RE = re.compile(r"^(gold|silver|sapphire|emerald|ruby|diamond|dragonstone)_ring$")
# Fletching intermediates live with crafting.
FLETCH_KEYWORDS = ("unstrung", "arrowheads", "arrow_shaft", "bow_string")
# Bows below magic tier — plus magic longbows — are fletching stock rather
# than gear anyone actually fights with.
FLETCH_BOWS = {
    "shortbow", "longbow",
    "oak_shortbow", "oak_longbow",
    "willow_shortbow", "willow_longbow",
    "maple_shortbow", "maple_longbow",
    "yew_shortbow", "yew_longbow",
    "magic_longbow",
}
# Plain tools that would otherwise be caught by a broader keyword rule
# ("knife" as ammo, "lobster_pot"/"harpoon" as food, "pot_empty" as food).
TOOL_SLUGS = {
    "knife", "hammer", "chisel", "tinderbox", "spade", "rope", "bucket",
    "bucket_empty", "pot_empty", "jug_empty", "vial_empty", "lobster_pot",
    "harpoon", "small_fishing_net", "big_fishing_net", "fishing_rod",
    "fly_fishing_rod", "fishing_bait", "feather", "needle", "shears",
    "glassblowing_pipe", "pestle_and_mortar", "ammo_mould", "bar_mould",
    "holy_mould", "necklace_mould", "amulet_mould", "ring_mould",
}
POTION_KEYWORDS = ("potion", "dose", "_oil", "antipoison", "restore", "antidragon")
HERB_KEYWORDS = (
    "leaf", "weed", "tarromin", "marentill", "harralander", "irit", "avantoe",
    "kwuarm", "cadantine", "lantadyme", "guam", "herb", "grimy", "snape_grass",
    "limpwurt", "eye_of_newt", "red_spiders_eggs", "mushroom",
    "toadflax", "snapdragon", "torstol",
)
ORE_BAR_KEYWORDS = ("_ore", "_bar", "coal", "molten_glass")
LOG_KEYWORDS = ("_logs", "logs_")
FOOD_KEYWORDS = (
    "lobster", "shark", "tuna", "swordfish", "bass", "cake", "bread", "meat",
    "stew", "pie", "wine", "beer", "cooked", "shrimp", "anchovie", "sardine",
    "herring", "salmon", "trout", "pike", "kebab", "chocolate", "banana",
    "curry", "ugthanki", "oomlie",
)
GEM_KEYWORDS = ("sapphire", "emerald", "ruby", "diamond", "dragonstone", "opal", "jade")
SEED_KEYWORDS = ("seed",)
BONE_KEYWORDS = ("bones", "ashes")
CRAFTING_KEYWORDS = (
    "dragonhide", "leather", "hide", "flax", "bow_string", "feather",
    "vial", "silk", "thread", "wool", "ball_of_wool", "unstrung",
    "cowhide", "fur", "glass", "soft_clay", "clay",
)

# Potion dose slugs look like "3dose1attack", "4doseprayerrestore" —
# a leading dose count then a family key shared by every dose variant.
DOSE_RE = re.compile(r"^(\d)dose(.+)$")

# ---------------------------------------------------------------------
# Explicit per-slug category overrides. These beat every keyword rule, for
# items whose slug or name doesn't reflect how players actually think about
# them (wine of zamorak is a herblore secondary, not a drink).
# ---------------------------------------------------------------------
CATEGORY_OVERRIDES = {}

def _override(category, slugs):
    for s in slugs:
        CATEGORY_OVERRIDES[s] = category

_override("herblore", [
    "ashes", "ibans_ashes",          # no prayer XP in this build — herblore only
    "wine_of_zamorak", "zamorak_wine",
    "white_berries", "whiteberries",
    "dragon_scale_dust", "blue_dragon_scale",
    "potato_cactus", "cactus_potato",
    "unicorn_horn", "cave_unicorn_horn", "unicorn_horn_dust", "ground_unicorn_horn",
    "sinister_key",
])
_override("food", [
    "tangled_toads_legs", "equa_toads_legs", "premade_tangled_toads_legs",
    "seasoned_toads_legs", "spicy_toads_legs", "toads_legs",
])
_override("crafting", [
    "swamp_paste", "swamppaste", "rawswamppaste",
    "arrow_shaft", "ogre_arrow_shaft",
])
_override("runecrafting", ["blankrune"])
_override("jewellery", ["blessedstar", "stringstar"])
_override("herblore", ["vial", "vial_empty", "vial_water", "vial_enchanted"])
_override("food", [
    "pineapple_pizza", "half_pineapple_pizza", "pineapple", "pineapple_ring",
    "pineapple_chunks", "tomato", "bowl_tomato",
])
_override("crafting", [
    "flamtaer_hammer", "silver_sickle", "silver_sickle_blessed", "hardleather_body",
])
_override("junk", [
    "felinemedal",          # cat training medal
    "worm_hole", "premade_worm_hole", "unfinished_worm_hole",
    "rotten_tomato", "machette", "ball_gnomeball_game",
])
_override("equipment", [
    "splitbark_helm", "splitbark_body", "splitbark_legs",
    "splitbark_gauntlets", "splitbark_greaves",
    # "Dragonfire shield" — its slug contains "antidragon", which was landing
    # it in Potions.
    "antidragonbreathshield",
])
_override("herblore", [
    # "_bar" was sending chocolate bars to Ores & Bars.
    "chocolate_bar", "chocolate_dust",
])
_override("other", [
    "mithril_seed",
    # Buckets and pots are supplies people genuinely stock, not junk.
    "bucket", "bucket_empty", "bucket_water", "bucket_milk", "bucket_sand",
    "pot_empty", "cooking_pot", "jug_empty",
])

# Talismans are runecrafting, but "digtalisman" is a quest item.
TALISMAN_RE = re.compile(r"^[a-z]+_talisman$")


# ---------------------------------------------------------------------
# Junk — non-stacking skilling tools and vendor clothing that sell for a
# few gp from any general store and are never actively traded. Counting
# them adds noise, not value, so they're valued at 0 and hidden by default.
# ---------------------------------------------------------------------
JUNK_SLUGS = {
    # tools
    "knife", "rope", "pestle_and_mortar", "spade", "chisel", "hammer",
    "tinderbox", "needle", "thread", "shears", "glassblowing_pipe",
    "lobster_pot", "harpoon", "big_fishing_net", "small_fishing_net",
    "fishing_rod", "fly_fishing_rod", "oily_fishing_rod", "fishing_bait",
    "bucket", "bucket_empty", "pot_empty", "jug_empty",
    # clothing sold by vendors
    "blue_skirt", "pink_skirt", "black_skirt", "brown_apron",
    "priest_gown_top", "priest_gown_bottom", "priest_top", "priest_bottom",
    "desert_robe", "desert_shirt", "desert_boots",
    "wizards_hat", "wizard_hat", "bluewizhat", "wizards_robe", "wizards_robe_bottom",
    "boots_wizard",
    "fremennik_cloak", "fremennik_shirt", "fremennik_boots", "fremennik_blade",
    # misc
    "pot_of_cream", "cream",
    "elemental_shield", "black_robe", "black_robe_top", "black_robe_bottom",
    "crossbow",          # the plain vendor crossbow
    "bolt", "bolts",
}
# Whole families that are vendor-bought for coppers. A fremennik cloak was
# being valued at 100k off one stale listing; they cost about 1k from an NPC.
JUNK_PREFIXES = (
    "snelm_",
    "flowers_",
    "fremennik_",
    "viking_cloak_", "viking_top_",   # Fremennik cloaks/shirts, ~100gp from an NPC
    "petecandlestick", "petes_",
)
JUNK_SUFFIXES = ("_mould",)
JUNK_KEYWORDS = ("_apron", "_bead", "bead_", "unlit_candle", "lit_candle")

# Flowers are junk EXCEPT black and white, which people actually buy.
FLOWER_PREFIX = "flowers_waterfall_quest"
FLOWER_KEEP = {f"{FLOWER_PREFIX}_black", f"{FLOWER_PREFIX}_white"}


def is_junk(slug):
    s = (slug or "").lower()
    if s in JUNK_SLUGS:
        return True
    if s.startswith(FLOWER_PREFIX):
        return s not in FLOWER_KEEP
    if s.startswith(JUNK_PREFIXES):
        return True
    if s.endswith(JUNK_SUFFIXES):
        return True
    if any(k in s for k in JUNK_KEYWORDS):
        return True
    return False


# Actual runes end in "rune" with no separator (naturerune, airrune).
# Rune-tier EQUIPMENT is "rune_<thing>" — a completely different thing that
# was landing in the Runes category and burying real runes.
RUNE_RE = re.compile(r"^[a-z]+rune$")

# "rune_knife", "adamant_knife_p" -> thrown ammunition. Bare "knife" is a tool.
TIERED_KNIFE_RE = re.compile(
    r"^(bronze|iron|steel|black|mithril|adamant|rune)_(knife|dart|javelin)(_p)?$"
)


def parse_dose(slug):
    """Return (dose_count, family) for a potion slug, else (None, None)."""
    m = DOSE_RE.match(slug or "")
    if not m:
        return None, None
    return int(m.group(1)), m.group(2)


# ---------------------------------------------------------------------
# Bundle caps — per-unit sanity limits, in gp.
#
# Some items are routinely used as the listing slot for a whole SET: full rune
# sets get posted under "rune platebody", full dragonhide sets under the body,
# and super attack/strength/defence sets under one of the supers. Those listings
# are real coin sales, so nothing about the data marks them as bundles — the
# sale history just goes bimodal, with a cluster of genuine singles and a
# cluster at 2-4x for the sets. Taking a median across both lands between the
# two and is wrong for everyone.
#
# Calibrated from actual sale history (see README). Retune when prices move:
# pull an item page, look for the low cluster, and set the cap just above it.
BUNDLE_CAPS = {
    "rune_platebody": 70_000,          # singles ~42k; full rune sets 145-170k
    "dragonhide_body": 7_000,          # green: singles 3-5k; sets 9-20k
    "blue_dragonhide_body": 9_000,     # singles ~5.4k; sets 18-60k
    "red_dragonhide_body": 17_000,     # singles 10-15k; sets 25-35k
    "black_dragonhide_body": 17_000,   # singles 10-15k; sets 20-27k
    # Supers share their slug with super SETS (3 potions in one listing).
    "3dose2attack": 2_200,
    "3dose2defense": 2_200,
    "3dose2strength": 5_200,
    "4dose2attack": 2_900,
    "4dose2defense": 2_900,
    "4dose2strength": 6_900,
}


# Splitbark is priced from its fine cloth cost. The pieces barely trade
# individually (the helm has no coin sales at all, so it was falling back to a
# 6k alch value), but fine cloth is liquid and the crafting requirement is
# fixed, which makes it a far better anchor than alch.
FINE_CLOTH_SLUG = "fine_cloth"
SPLITBARK_CLOTH = {
    "splitbark_helm": 2,
    "splitbark_body": 4,
    "splitbark_legs": 3,
    "splitbark_gauntlets": 1,
    "splitbark_greaves": 1,   # the boots slot
}


# Charged jewellery: "amulet_of_glory_3", "ring_of_dueling_8". Only the max-charge
# variant trades in any volume, so the partial ones would otherwise fall back to
# alch value and be wildly mispriced (a glory(1) alched at 10.5k next to a
# glory(4) worth 272k).
#
# Two models, because recharging works differently:
#   "full"         every charge level is worth the full max-charge price.
#                  Glories recharge free at the Fountain of Heroes, so an
#                  uncharged one is worth essentially what a charged one is.
#                  Applies to the bare, uncharged slug too.
#   "proportional" value scales with charges remaining (half charges = half
#                  worth). Dueling rings and games necklaces can't be recharged
#                  — you consume them and buy another — so the charges are the
#                  product.
CHARGE_FAMILIES = {
    "amulet_of_glory": {"max": 4, "model": "full"},
    "ring_of_dueling": {"max": 8, "model": "proportional"},
    "necklace_of_minigames": {"max": 8, "model": "proportional"},
}

CHARGE_RE = re.compile(r"^(.*?)_(\d+)$")


def parse_charges(slug):
    """Return (charges, family, spec) for charged jewellery, else (None, None, None).

    The bare uncharged slug (e.g. "amulet_of_glory") reports 0 charges.
    """
    s = slug or ""
    if s in CHARGE_FAMILIES:
        return 0, s, CHARGE_FAMILIES[s]
    m = CHARGE_RE.match(s)
    if m and m.group(1) in CHARGE_FAMILIES:
        family = m.group(1)
        return int(m.group(2)), family, CHARGE_FAMILIES[family]
    return None, None, None


def categorize(slug, name="", is_set=False):
    s = (slug or "").lower()

    if s == "coins":
        return "coins"
    if s in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[s]
    if is_junk(s):
        return "junk"
    if is_set:
        return "equipment"

    # Runecrafting: essence and talismans.
    if TALISMAN_RE.match(s):
        return "runecrafting"

    if any(k in s for k in SEED_KEYWORDS):
        return "seeds"
    if parse_dose(s)[0] is not None or any(k in s for k in POTION_KEYWORDS):
        return "potions"
    # Unfinished potions ("guamvial", "ranarrvial") are herblore intermediates.
    if s.endswith("vial") and s not in ("vial", "vial_water", "vial_empty"):
        return "herblore"
    # Fletching stock first: an unstrung yew longbow is material, and bows
    # below magic tier aren't gear anyone actually fights with.
    if any(k in s for k in FLETCH_KEYWORDS) or s in FLETCH_BOWS:
        return "crafting"
    # Thrown weapons: a tiered knife ("rune_knife") is ammunition, while a bare
    # "knife" is the cooking/fletching tool and is junk.
    if any(k in s for k in AMMO_KEYWORDS) or TIERED_KNIFE_RE.match(s):
        return "ammunition"
    if any(k in s for k in JEWEL_KEYWORDS) or JEWEL_RING_RE.match(s):
        return "jewellery"
    if any(k in s for k in WEAPON_KEYWORDS):
        return "weapons"
    # Dragonhide armour is worn; raw hide and leather stay crafting materials.
    if ("dragonhide" in s or "dragon_vambraces" in s) and any(
        k in s for k in ("_body", "_chaps", "_vambraces", "_coif")
    ):
        return "equipment"
    if any(k in s for k in GEM_KEYWORDS):
        return "gems"
    if any(k in s for k in HERB_KEYWORDS):
        return "herblore"
    if any(k in s for k in LOG_KEYWORDS):
        return "logs"
    if any(k in s for k in ORE_BAR_KEYWORDS):
        return "ores_bars"
    if any(k in s for k in FOOD_KEYWORDS):
        return "food"
    if any(k in s for k in BONE_KEYWORDS):
        return "bones"

    # Real runes only — "rune_scimitar" must fall through to equipment.
    if RUNE_RE.match(s):
        return "runes"

    if any(k in s for k in CRAFTING_KEYWORDS):
        return "crafting"
    if s in TOOL_SLUGS:
        return "tools"
    if any(k in s for k in EQUIP_KEYWORDS):
        return "equipment"
    # Rune/dragon-tier gear that dodged the keyword list.
    if s.startswith(("rune_", "dragon_", "adamant_", "mithril_", "steel_",
                     "iron_", "bronze_", "black_")):
        return "equipment"
    return "other"



# ---------------------------------------------------------------------
# Variants that should be priced — and displayed — as their base item.
#
# Poisoned weapons barely trade; a rune arrow(p) is worth what a rune arrow is.
# Dragon leather is tanned dragonhide of the same colour, and trades alongside
# it. Rather than pricing these separately (badly) or hiding them, the report
# folds them into the base item's row and notes the split: "Rune arrow x5,200
# (+200 poisoned)".
# ---------------------------------------------------------------------
POISON_SUFFIXES = ("_p", "_p_", "_poisoned")

# dragon_leather -> dragonhide_green, dragon_leather_blue -> dragonhide_blue, ...
LEATHER_TO_HIDE = {
    "dragon_leather": "dragonhide_green",
    "dragon_leather_blue": "dragonhide_blue",
    "dragon_leather_red": "dragonhide_red",
    "dragon_leather_black": "dragonhide_black",
}

# Colour words for disambiguating the many identically-named dragonhide items.
HIDE_COLOURS = {
    "dragonhide_green": "Green", "dragonhide_blue": "Blue",
    "dragonhide_red": "Red", "dragonhide_black": "Black",
    "dragon_leather": "Green", "dragon_leather_blue": "Blue",
    "dragon_leather_red": "Red", "dragon_leather_black": "Black",
    "dragonhide_body": "Green", "blue_dragonhide_body": "Blue",
    "red_dragonhide_body": "Red", "black_dragonhide_body": "Black",
    "dragonhide_chaps": "Green", "blue_dragonhide_chaps": "Blue",
    "red_dragonhide_chaps": "Red", "black_dragonhide_chaps": "Black",
    "dragon_vambraces": "Green", "blue_dragon_vambraces": "Blue",
    "red_dragon_vambraces": "Red", "black_dragon_vambraces": "Black",
}

# Torn pages are all named "Torn page N" across three different god books;
# the slug's g/s/z is the only thing telling them apart.
TORN_PAGE_GODS = {"g": "Guthix", "s": "Saradomin", "z": "Zamorak"}

# Every unfinished potion is just named "Unfinished potion"; the herb is the
# only thing that distinguishes them (and what sets the price).
UNF_HERB_NAMES = {
    "guam": "Guam", "marrentill": "Marrentill", "tarromin": "Tarromin",
    "harralander": "Harralander", "ranarr": "Ranarr", "irit": "Irit",
    "avantoe": "Avantoe", "kwuarm": "Kwuarm", "cadantine": "Cadantine",
    "lantadyme": "Lantadyme", "dwarfweed": "Dwarf weed", "toadflax": "Toadflax",
    "snapdragon": "Snapdragon", "torstol": "Torstol", "ashes": "Ashes",
    "janger": "Jangerberries", "guamjanger": "Guam + jangerberries",
}


def base_variant(slug):
    """Return (base_slug, variant_label) for a poison/leather variant."""
    s = slug or ""
    if s in LEATHER_TO_HIDE:
        return LEATHER_TO_HIDE[s], "leather"
    for suffix in POISON_SUFFIXES:
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)], "poisoned"
    return None, None


def disambiguate_name(slug, name):
    """Add back detail the game's own names drop.

    Dragonhide items all share a name ("Dragonhide body" x4) and torn pages all
    read "Torn page N" across three god books, so neither is identifiable in a
    bank listing without the colour or god.
    """
    if not name:
        return name

    if slug.endswith("vial") and slug not in ("vial", "vial_water", "vial_empty"):
        herb = UNF_HERB_NAMES.get(slug[: -len("vial")])
        if herb and herb.lower() not in name.lower():
            return f"{name} ({herb})"
        return name

    if slug.startswith("holy_book_") and "_page" in slug:
        god = TORN_PAGE_GODS.get(slug.split("_")[2][:1])
        if god and god.lower() not in name.lower():
            return f"{name} ({god})"
        return name

    colour = HIDE_COLOURS.get(slug)
    if not colour:
        return name
    if name.lower().startswith(colour.lower()):
        return name
    return f"{colour} {name[0].lower()}{name[1:]}"


# Unfinished potions are "<herb>vial" and are worth their herb plus a vial of
# water — both of which trade actively, so this is a real price rather than a
# guess. Herb slugs that don't simply prefix the vial slug go here.
UNF_HERB_ALIASES = {
    "guam": "guam_leaf",
    "marrentill": "marentill",
    "tarromin": "tarromin",
    "harralander": "harralander",
    "ranarr": "ranarr_weed",
    "irit": "irit_leaf",
    "avantoe": "avantoe",
    "kwuarm": "kwuarm",
    "cadantine": "cadantine",
    "lantadyme": "lantadyme",
    "dwarfweed": "dwarf_weed",
    "toadflax": "toadflax",
    "snapdragon": "snapdragon",
    "torstol": "torstol",
}
VIAL_WATER_SLUG = "vial_water"


def unfinished_potion_herb(slug):
    """'ranarrvial' -> 'ranarr_weed'. None if not an unfinished potion."""
    s = slug or ""
    if not s.endswith("vial") or s in ("vial", "vial_water", "vial_empty"):
        return None
    stem = s[: -len("vial")]
    return UNF_HERB_ALIASES.get(stem, stem)


# ---------------------------------------------------------------------
# Items that default to vendor (low alch) price regardless of listings.
# Nobody buys these in bulk and they aren't worth alching, so an ask-only
# quote on one is noise rather than signal.
# ---------------------------------------------------------------------
VENDOR_DEFAULT_SLUGS = {
    "silver_sickle", "silver_sickle_blessed",
    "hardleather_body",
    "stringstar",        # unblessed / unstrung symbol
    "unstrung_symbol", "unstrung_emblem",
}
JAVELIN_RE = re.compile(
    r"^((bronze|iron|steel|black|mithril|adamant|rune)_)?javelin(_p)?$"
)


def is_vendor_default(slug):
    s = (slug or "").lower()
    return s in VENDOR_DEFAULT_SLUGS or bool(JAVELIN_RE.match(s))


# Bucket/pot variants that price as their plain empty container: a bucket of
# water is a bucket someone filled up, and only the empty one really trades.
CONTAINER_BASE = {
    "bucket_water": "bucket_empty",
    "bucket_milk": "bucket_empty",
}
