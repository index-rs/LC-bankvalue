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
_override("crafting", ["swamp_paste", "swamppaste", "rawswamppaste"])
_override("runecrafting", ["blankrune"])
_override("equipment", [
    "splitbark_helm", "splitbark_body", "splitbark_legs",
    "splitbark_gauntlets", "splitbark_greaves",
    "elemental_shield",
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
    "petes_candlestick", "candlestick", "pot_of_cream", "cream",
    "elemental_shield",
    "bolt", "bolts",
}
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
    # Thrown weapons: a tiered knife ("rune_knife") is ammunition, while a bare
    # "knife" is the cooking/fletching tool and is junk.
    if any(k in s for k in AMMO_KEYWORDS) or TIERED_KNIFE_RE.match(s):
        return "ammunition"
    # Dragonhide armour is worn; raw hide and leather stay crafting materials.
    if "dragonhide" in s and any(k in s for k in ("_body", "_chaps", "_vambraces", "_coif")):
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
    "dragonhide_vambraces": "Green", "blue_dragonhide_vambraces": "Blue",
    "red_dragonhide_vambraces": "Red", "black_dragonhide_vambraces": "Black",
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
    """Dragonhide items all share a name ('Dragonhide body' x4). Add the colour."""
    colour = HIDE_COLOURS.get(slug)
    if not colour or not name:
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
