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
# Fletching: bow stock and arrow components.
#
# "unstrung" is deliberately NOT a bare keyword here — an unstrung sapphire
# amulet is jewellery-making, not fletching. Unstrung bows are listed out
# below instead.
FLETCH_KEYWORDS = ("arrowheads", "arrow_shaft", "headless_arrow", "bow_string")
# Bows below magic tier — plus magic longbows — are fletching stock rather
# than gear anyone actually fights with. The magic SHORTBOW is the one bow
# people genuinely fight with, so it stays in Weapons.
FLETCH_BOWS = {
    "shortbow", "longbow",
    "oak_shortbow", "oak_longbow",
    "willow_shortbow", "willow_longbow",
    "maple_shortbow", "maple_longbow",
    "yew_shortbow", "yew_longbow",
    "magic_longbow",
}
# An unstrung bow is stock at every tier — including the magic shortbow's,
# which only becomes a weapon once someone strings it.
FLETCH_BOWS |= {f"unstrung_{bow}" for bow in FLETCH_BOWS}
FLETCH_BOWS.add("unstrung_magic_shortbow")
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
# "_logs"/"logs_" miss plain "logs" and "newbielogs" — the ordinary tree log,
# which was falling all the way through to Other.
LOG_KEYWORDS = ("_logs", "logs_")
LOG_SLUGS = {"logs", "newbielogs"}
FOOD_KEYWORDS = (
    "lobster", "shark", "tuna", "swordfish", "bass", "cake", "bread", "meat",
    "stew", "pie", "wine", "beer", "cooked", "shrimp", "anchovie", "sardine",
    "herring", "salmon", "trout", "pike", "kebab", "chocolate", "banana",
    "curry", "ugthanki", "oomlie",
)
# Cookable food that a later rule would otherwise claim: "swordfish" contains
# "sword", "raw gnomebowl" contains "bow", so both were landing in Weapons /
# Armour. Checked early, straight after the junk gate — junk still wins, so a
# burnt or spoilt version of any of these stays junk.
FOOD_PREFIXES = ("premade_", "raw_")
FOOD_KEYWORDS_EARLY = (
    "crunchies", "batta", "gnomebowl", "karambwan", "mantaray", "seaturtle",
    "mackerel", "lava_eel", "slimey_eel", "giant_carp", "chocolaty_milk",
)
FOOD_SLUGS = {
    "cod", "swordfish", "mackerel", "seaturtle", "mantaray", "lava_eel",
    "spicy_crunchies", "toad_batta", "toad_crunchies", "vegetable_batta",
    "fruit_batta", "worm_batta", "worm_crunchies", "chocchip_crunchies",
}

GEM_KEYWORDS = ("sapphire", "emerald", "ruby", "diamond", "dragonstone", "opal", "jade")
SEED_KEYWORDS = ("seed",)
BONE_KEYWORDS = ("bones", "ashes")
CRAFTING_KEYWORDS = (
    "dragonhide", "leather", "hide", "flax", "feather",
    "vial", "silk", "thread", "wool", "ball_of_wool",
    "cowhide", "fur", "glass", "soft_clay", "clay",
)

# Potion dose slugs look like "3dose1attack", "4doseprayerrestore" —
# a leading dose count then a family key shared by every dose variant.
DOSE_RE = re.compile(r"^(\d)dose(.+)$")

# One potion breaks the naming convention: the 4-dose strength potion is
# "strength4", not "4dose1strength". Without this it is orphaned from its own
# dose family and falls back to whatever stray listing exists (a 1,000gp ask,
# against 400gp for the 3-dose).
DOSE_ALIASES = {"strength4": (4, "1strength")}

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
_override("fletching", [
    "arrow_shaft", "ogre_arrow_shaft",
    "headless_arrow", "ogre_headless_arrow",
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
    "bucket", "bucket_empty", "bucket_water", "bucket_milk",
    "pot_empty", "cooking_pot",
])
# Sacred oil is a Shades of Mort'ton consumable, not a herblore potion — the
# "_oil" in its slug was landing it in Potions.
_override("other", ["sacred_oil1", "sacred_oil2", "sacred_oil3", "sacred_oil4"])
# Crafting stock. A bucket of sand is glassmaking input, not a filled bucket:
# it trades on its own (788gp against an empty bucket's 220) so it keeps its
# own price rather than following bucket_empty like water and milk do.
_override("crafting", [
    "bucket_sand", "seaweed", "soda_ash", "molten_glass",
    "air_orb", "water_orb", "earth_orb", "fire_orb", "stafforb",
    # The plain battlestaff is the blank you enchant; the elemental ones are
    # real weapons and stay in Weapons.
    "battlestaff",
])
# Thrown weapons are ammunition — they stack and get consumed.
_override("ammunition", [
    "bronze_thrownaxe", "iron_thrownaxe", "steel_thrownaxe",
    "mithril_thrownaxe", "adamnt_thrownaxe", "rune_thrownaxe",
    "bolt", "bolts",
])
# Bolt tips are fletching stock, same as arrowheads.
_override("fletching", ["opal_bolttips", "pearl_bolttips", "barbed_bolttips"])
_override("herblore", ["jangerberries"])
_override("junk", ["bread"])
_override("herblore", [
    "unidentified_ardrigal", "unidentified_rogues_purse",
    "unidentified_sito_foil", "unidentified_volencia_moss",
    "unidentified_snake_weed", "unidentified_ranarr",
])
# Requested explicitly. NOTE: its 1/2/3-dose siblings are in Potions — see the
# handover note; move all four together if this should be Potions instead.
_override("herblore", ["strength4"])
_override("food", ["swordfish", "raw_swordfish"])

# ---------------------------------------------------------------------
# Treasure Trails — clue scroll rewards.
#
# These are cosmetics priced entirely by scarcity rather than by their (usually
# identical) combat stats: a gilded platebody is rune armour that alchs for 38k
# and sells for 30M. Scattered through Armour and Other they made a bank's most
# valuable holdings the hardest to find, so they get their own category.
#
# Build 274 carries the 2004 reward table: black/adamant/rune trimmed and
# gold-trimmed sets, the rune god sets, gilded rune, the god book pages, and the
# cosmetic headwear and boots. The bronze/iron/steel/mithril trimmed sets and
# the heraldic items came later and are absent here — see the OSRS wiki's
# Ornamental armour and Gilded equipment pages for the full modern table.
# ---------------------------------------------------------------------
_TRAIL_TIERS = ("black", "adamant", "rune")
_TRAIL_PIECES = ("full_helm", "kiteshield", "platebody", "platelegs", "plateskirt")

TREASURE_TRAIL_SLUGS = {
    # (t) and (g) ornamental sets
    f"{tier}_{piece}_{suffix}"
    for tier in _TRAIL_TIERS
    for piece in _TRAIL_PIECES
    for suffix in ("trim", "gold")
}
TREASURE_TRAIL_SLUGS |= {
    # gilded and the three rune god sets — rune only in this build
    f"rune_{piece}_{suffix}"
    for piece in _TRAIL_PIECES
    for suffix in ("goldplate", "saradomin", "zamorak", "guthix")
}
TREASURE_TRAIL_SLUGS |= {
    # headwear
    "robinhoodhat", "highwaymanmask", "highwayman_mask", "piratehat",
    "berret_black", "berret_blue", "berret_white",
    "cavalier_black", "cavalier_brown", "cavalier_dark",
    "headband_black", "headband_brown", "headband_red",
    # boots
    "boots_ranger", "boots_wizard",
    # the god books built from the torn pages
    "saradominbook_complete", "zamorakbook_complete", "guthixbook_complete",
    "unfinished_saradominbook", "unfinished_zamorakbook", "unfinished_guthixbook",
}
# Torn pages: holy_book_{g,s,z}_page{1..4}.
TREASURE_TRAIL_PREFIXES = ("holy_book_",)


def is_treasure_trail(slug):
    s = (slug or "").lower()
    return s in TREASURE_TRAIL_SLUGS or s.startswith(TREASURE_TRAIL_PREFIXES)


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
    "fremennik_cloak", "fremennik_shirt", "fremennik_boots", "fremennik_blade",
    # misc
    "pot_of_cream", "cream",
    "elemental_shield", "black_robe", "black_robe_top", "black_robe_bottom",
    "crossbow",          # the plain vendor crossbow
    "phoenix_crossbow", "magic_staff", "plainstaff", "flier",
    # vendor drinks and food nobody stocks
    "asgarnian_ale", "beer", "beer_glass", "brandy", "dragon_bitter",
    "dwarven_stout", "gin", "greenmans_ale", "grog", "karamja_rum",
    "keg_of_beer", "moonlight_mead", "vodka", "whisky", "viking_tankard_empty",
    "viking_tankard_full", "viking_beerkeg", "viking_low_alcahol_beerkeg",
    "kebab", "cabbage", "magic_cabbage", "cadavaberries", "redberries",
    "grapes", "grain", "gnome_spice", "grinder", "onion", "potato",
    "lemon", "lemon_chunks", "lemon_slices",
    "lime", "lime_chunks", "lime_slices",
    "orange_chunks", "orange_slices",     # plain oranges stay
    "pizza_base", "plain_pizza", "half_plain_pizza", "incomplete_pizza",
    "limestone", "limestonebrick", "papyrus", "papyrus_used",
    "insect_repellent", "shantay_pass", "thshantaydisc", "vampire_dust",
    "wizards_mind_bomb", "woodplank", "worm", "skull", "ghostskull",
    "poison", "chompy_bird_obj", "archery_ticket", "arravcertificate",
    "shiloshipticket", "paramayaticket", "agilityarena_ticket",
    "arravshield1", "arravshield2", "black_ring", "amulet_of_accuracy",
    # vendor clothing
    "black_cape", "blue_cape", "orange_cape", "purple_cape", "red_cape",
    "yellow_cape", "chefs_hat", "wooden_shield",
    "priest_gown", "priest_robe", "druidrobetop", "druidrobebottom",
    "vikingrobetop", "vikingrobebottom",
    # crafting leftovers with no real market
    "fur", "grey_wolf_fur", "silk", "glassblowingpipe", "smashed_glass",
    "charcoal", "hollow_bark", "bronzecraftwire", "woadleaf", "acne_potion",
    "cocktail_shaker", "cocktail_glass_empty",
}
# Whole families that are junk. Prefix-matched, so a new colour or tier of the
# same vendor item is covered without another edit here.
JUNK_FAMILY_PREFIXES = (
    "burnt",              # every burnt fish and burnt cooked food
    "spoilt_",            # odd/ruined gnome food
    "bowl_",              # empty bowls and the bowl-stage gnome dishes
    "horsey_",            # toy horseys
    "oliveoil",
    "shellpoint_", "shellround_",
    "wolfen",             # the whole wolfen robe set
    "gnome_hat_", "gnome_boots_", "gnome_robetop_", "gnome_robebottoms_",
    "ice_arrow",
    "unfired_",
)
# Substrings that mark a whole junk family.
JUNK_FAMILY_KEYWORDS = (
    "dye", "scroll", "unfired", "dough", "cheese", "wire",
)

# Keys, books and pearls are junk EXCEPT for a handful that genuinely trade.
# Without these the crystal key (272k) and the god-book torn pages (up to 509k)
# would be written down to zero.
JUNK_EXCEPT = {
    "crystal_key", "keyhalf1", "keyhalf2", "sinister_key",
    "half_full_wine_jug",          # a rare, not a drink
}


def _is_junk_family(s):
    """Key / book / pearl / jug families, with their real-value exceptions."""
    if s in JUNK_EXCEPT:
        return False
    # "monkey" contains "key" — the monkey bones and corpses are not keys.
    if "key" in s and "monkey" not in s:
        return True
    # Torn pages are god-book pages worth 20k-509k, not reading material.
    if ("book" in s or "guide" in s) and not s.startswith("holy_book_"):
        return True
    if "oyster" in s:
        return True
    if "pearl" in s and "bolt" not in s:   # pearl bolts are ammunition
        return True
    if "jug" in s:
        return True
    return False
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
    if s in JUNK_EXCEPT:
        return False
    if s in JUNK_SLUGS:
        return True
    if s.startswith(JUNK_FAMILY_PREFIXES):
        return True
    if any(k in s for k in JUNK_FAMILY_KEYWORDS):
        return True
    if _is_junk_family(s):
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
    s = slug or ""
    if s in DOSE_ALIASES:
        return DOSE_ALIASES[s]
    m = DOSE_RE.match(s)
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

# ---------------------------------------------------------------------
# Enchanted equivalents — a ceiling on plain gem jewellery.
#
# Enchanting is slow, fiddly work: you need the runes, the magic level and a
# lot of clicking. Nobody pays MORE for the unenchanted piece than for the
# finished article, so when a thin market quotes one higher (a sapphire
# necklace at 1,000gp next to a games necklace(8) at 975) that's noise, not a
# premium. The unenchanted price is capped at its enchanted counterpart's.
#
# The cap only bites upward — an unenchanted piece trading well below its
# enchanted form is perfectly normal and left alone.
#
# Each value is the slug the enchant spell actually produces: enchanting an
# emerald ring yields a ring of dueling(8), not a spent one. Necklaces other
# than sapphire have no enchanted counterpart in this build.
# ---------------------------------------------------------------------
ENCHANT_PRODUCT = {
    # rings
    "sapphire_ring": "ring_of_recoil",
    "emerald_ring": "ring_of_dueling_8",
    "ruby_ring": "ring_of_forging",
    "diamond_ring": "ring_of_life",
    "dragonstone_ring": "ring_of_wealth",
    # necklaces
    "sapphire_necklace": "necklace_of_minigames_8",
    # amulets — the unstrung one is strictly more work than the strung one
    # (string it, then enchant it), so it takes the same ceiling.
    "strung_sapphire_amulet": "amulet_of_magic",
    "unstrung_sapphire_amulet": "amulet_of_magic",
    "strung_emerald_amulet": "amulet_of_defence",
    "unstrung_emerald_amulet": "amulet_of_defence",
    "strung_ruby_amulet": "amulet_of_strength",
    "unstrung_ruby_amulet": "amulet_of_strength",
    "strung_diamond_amulet": "amulet_of_power",
    "unstrung_diamond_amulet": "amulet_of_power",
    "strung_dragonstone_amulet": "amulet_of_glory",
    "unstrung_dragonstone_amulet": "amulet_of_glory",
}



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

    # A noted item is its base item on a piece of paper — always the same
    # category. build_catalog.py already resolves the base slug, but the
    # scraper re-derives categories straight off the stored slug, and without
    # this "cert_yew_longbow" misses every rule keyed on the bare slug.
    if s.startswith("cert_"):
        s = s[len("cert_"):]

    if s == "coins":
        return "coins"
    if s in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[s]
    # Before junk: wizard's boots and the god books would otherwise be caught by
    # the vendor-clothing and "all books" rules.
    if is_treasure_trail(s):
        return "treasure_trails"
    if is_junk(s):
        return "junk"
    # Cookable stock that a later rule would otherwise claim: "swordfish"
    # contains "sword", "raw gnomebowl" contains "bow". After the junk gate, so
    # the burnt and spoilt versions still read as junk.
    if (s in FOOD_SLUGS or s.startswith(FOOD_PREFIXES)
            or any(k in s for k in FOOD_KEYWORDS_EARLY)):
        return "food"
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
        return "fletching"
    # Every other unstrung thing is a jewellery-crafting intermediate — an
    # unstrung sapphire amulet is a half-made amulet, not something you wear.
    if s.startswith("unstrung_"):
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
    if s in LOG_SLUGS or any(k in s for k in LOG_KEYWORDS):
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

# All three Hallowe'en masks are named "Halloween mask" and are worth
# 135M-399M apiece — the colour is the entire difference between them.
MASK_COLOURS = {
    "halloweenmask_green": "Green",
    "halloweenmask_blue": "Blue",
    "halloweenmask_red": "Red",
}

# Berets, cavaliers and headbands are each just "Beret"/"Cavalier"/"Headband"
# in game, and the colours are 15k to 650k apart.
TRAIL_COLOURS = {
    "berret_black": "Black", "berret_blue": "Blue", "berret_white": "White",
    "cavalier_black": "Black", "cavalier_brown": "Tan", "cavalier_dark": "Dark",
    "headband_black": "Black", "headband_brown": "Brown", "headband_red": "Red",
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


_NOTED_SUFFIX = " (noted)"


def _qualify(name, extra):
    """Append "(extra)", keeping a trailing "(noted)" last.

    Without this a noted unfinished potion reads "Unfinished potion (noted)
    (Guam)" — the note marker has to stay at the end of the name.
    """
    if name.endswith(_NOTED_SUFFIX):
        return f"{name[: -len(_NOTED_SUFFIX)]} ({extra}){_NOTED_SUFFIX}"
    return f"{name} ({extra})"


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
            return _qualify(name, herb)
        return name

    if slug in UNID_HERB:
        herb = UNF_HERB_NAMES.get(slug[len("unidentified_"):])
        if not herb:
            herb = slug[len("unidentified_"):].replace("_", " ").capitalize()
        if herb.lower() not in name.lower():
            return _qualify(name, herb)
        return name

    if slug.startswith("holy_book_") and "_page" in slug:
        god = TORN_PAGE_GODS.get(slug.split("_")[2][:1])
        if god and god.lower() not in name.lower():
            return _qualify(name, god)
        return name

    # Unstrung bows and amulets carry the SAME name as the finished item
    # ("Yew shortbow" twice, at very different prices), and since the split
    # they sit next to each other in Fletching / Crafting. Prepend rather than
    # append, so a noted item keeps its trailing "(noted)".
    if slug.startswith("unstrung_") and "unstrung" not in name.lower():
        return f"Unstrung {name[0].lower()}{name[1:]}"

    colour = MASK_COLOURS.get(slug) or TRAIL_COLOURS.get(slug) or HIDE_COLOURS.get(slug)
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


# ---------------------------------------------------------------------
# Unidentified herbs are the same herb before you look at it. They're all named
# just "Herb", so the slug is the only thing telling a 20k toadflax from an 80gp
# marrentill — hence both the price mapping and the name disambiguation.
#
# The quest-only herbs (ardrigal, sito foil, snake weed, volencia moss, rogue's
# purse) have no identified counterpart in the catalog and are left alone.
# ---------------------------------------------------------------------
UNID_HERB = {
    "unidentified_guam": "guam_leaf",
    "unidentified_marentill": "marentill",
    "unidentified_tarromin": "tarromin",
    "unidentified_harralander": "harralander",
    "unidentified_ranarr": "ranarr_weed",
    "unidentified_irit": "irit_leaf",
    "unidentified_avantoe": "avantoe",
    "unidentified_kwuarm": "kwuarm",
    "unidentified_cadantine": "cadantine",
    "unidentified_lantadyme": "lantadyme",
    "unidentified_dwarf_weed": "dwarf_weed",
    "unidentified_toadflax": "toadflax",
    "unidentified_snapdragon": "snapdragon",
    "unidentified_torstol": "torstol",
}


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
    # Thrown weapons and the low-tier bolts: shop stock, never traded in bulk.
    "bronze_thrownaxe", "iron_thrownaxe", "steel_thrownaxe",
    "mithril_thrownaxe", "adamnt_thrownaxe", "rune_thrownaxe",
    "bolt", "bolts", "barbed_bolt", "barbed_bolts",
    "opal_bolttips", "pearl_bolttips", "barbed_bolttips",
    # The blank battlestaff; the elemental ones trade properly on their own.
    "battlestaff",
}
JAVELIN_RE = re.compile(
    r"^((bronze|iron|steel|black|mithril|adamant|rune)_)?javelin(_p)?$"
)


def is_vendor_default(slug):
    s = (slug or "").lower()
    return s in VENDOR_DEFAULT_SLUGS or bool(JAVELIN_RE.match(s))


# ---------------------------------------------------------------------
# Melee families that price at alch value rather than off the market.
#
# Nobody trades a steel mace or a mithril halberd — the few listings that exist
# are stale one-offs that say more about the lister than the item. Alch value is
# the real floor, and it's what these actually get used for.
#
# Dragon weapons are excluded: those genuinely trade, at prices nothing to do
# with their alch value.
# ---------------------------------------------------------------------
ALCH_FAMILY_RE = re.compile(
    r"_(claws|warhammer|mace|dagger|halberd|battleaxe|spear|longsword)(_p)?$"
)


def is_alch_default(slug):
    s = (slug or "").lower()
    if s.startswith("dragon_"):
        return False
    return bool(ALCH_FAMILY_RE.search(s))


# ---------------------------------------------------------------------
# Items that are worth exactly what another item is worth.
#
# A bucket of water is a bucket someone filled up; a broken rune pickaxe is a
# rune pickaxe someone has to fix; a pickaxe head is the same pickaxe minus a
# handle worth a few gp; tanned leather is the cow hide it came from. In every
# case only one side of the pair trades in any volume, so the other would
# otherwise fall back to alch and be badly wrong.
# ---------------------------------------------------------------------
SAME_AS_BASE = {
    "bucket_water": "bucket_empty",
    "bucket_milk": "bucket_empty",
    "pot_flour": "pot_empty",
    "newbie_pot_flour": "pot_empty",
    # Tanned leather is the hide it was made from.
    "leather": "cow_hide",
    "hard_leather": "cow_hide",
}

# Broken tools and detached heads price as the working tool.
for _tier in ("bronze", "iron", "steel", "mithril", "adamant", "rune"):
    SAME_AS_BASE[f"macro_broken_{_tier}_pickaxe"] = f"{_tier}_pickaxe"
    SAME_AS_BASE[f"macro_{_tier}_pickaxehead"] = f"{_tier}_pickaxe"
for _tier in ("bronze", "iron", "steel", "black", "mithril", "adamant", "rune"):
    SAME_AS_BASE[f"macro_broken_{_tier}_hatchet"] = f"{_tier}_axe"
    SAME_AS_BASE[f"macro_{_tier}_hatchethead"] = f"{_tier}_axe"
del _tier
