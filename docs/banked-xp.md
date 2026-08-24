# Spec: banked XP calculator

Status: **built** (2026-08-23). `scripts/build_recipes.py` -> `data/recipes.json`
(354 recipes, 8 skills), `js/xp.js` + `js/xpReport.js`, stats capture in `js/savParser.js`,
and a Value / XP tab pair. Steps 0.1-0.5 of the ladder below are done. See the
**Banked XP** section of the README for what shipped; this file is kept as the design
record, with the places reality differed marked inline.

## The question it answers

> You have 12,300 yew logs, 4,100 bow string and a knife. What is that worth in
> Fletching XP, and where does it put you?

Today the site answers *what is my bank worth in gp*. This answers *what is my bank
worth in XP* — the other currency players actually hold banks in. Both questions read
the same `.sav` file and the same catalog; the second one just needs a recipe table
the repo doesn't have yet.

The pitch, concretely:

```
Fletching — 74 → 91                    1,847,300 xp available
  String yew longbow    4,100 × 75 xp  =   307,500   limited by bow string
  Cut yew longbow      12,300 × 75 xp  =   922,500   yew logs
  ...
  24.1M gp of stock in → 28.6M gp of bows out — the XP pays you 4.5M
```

That last line is the part no other calculator can do, because no other calculator
already knows what the stock is worth. It's the reason this belongs in *this* repo
rather than as a standalone tool.

## Where the XP numbers come from

Same principle as the item catalog: read the game's own content, don't hand-type a
table off a wiki. `build_catalog.py` already downloads
[`LostCityRS/Content@274`](https://github.com/LostCityRS/Content/archive/refs/heads/274.tar.gz)
(~16MB) and walks it. A sibling script — call it `build_recipes.py` — walks the same
tarball for XP.

XP lives in four different shapes in that repo, and the extractor needs all four:

| Shape | Example | Skills covered |
|---|---|---|
| **`.dbrow` rows against a `.dbtable`** — typed, one row per recipe | `skill_fletching/configs/stringing/bows.dbrow` | fletching, cooking, gem cutting, leather, runecraft, magic, mining, woodcutting, thieving |
| **`param=` on the item itself** — the XP is an item property | `bones` carries `param=bone_exp,45` | prayer (bury), herblore (identify), firemaking (`productexp` on logs), smithing (`xpperbar`) |
| **`.struct` configs** — a named bag of params the script looks up | `skill_herblore/configs/brewing/brew_potion.struct` | herblore brewing, jewellery, spinning, pottery, glass, studded leather, battlestaves |
| **Hardcoded in `.rs2`** — a literal in the script body | `stat_advance(fletching, multiply($arrow_count, 10))` in `arrows.rs2` (headless arrows) | scattered one-offs |

The first three are mechanically extractable and should be. The fourth is not, and
shouldn't be faked — a short hand-maintained table with a file:line citation per entry
is the honest answer, in the same spirit as `FIXED_PRICES` in `lc_items.py`. Keep it
short, and make every line say where it came from.

### XP is stored in tenths

> **Confirmed, and it goes further than this section assumed:** the *save file* stores xp in
> tenths too. A fletching field reading 130,344,716 is 13,034,471.6 xp — level 99. Nothing
> in the byte layout advertises that.

Every XP value in Content is the real XP × 10, because `stat_advance` takes tenths.
Verified against known values:

| Content says | Real XP | Check |
|---|---|---|
| `stringing_normal_shortbow` `experience=50` | 5.0 | shortbow stringing is 5 xp |
| `cooking_generic_lobster` `experience=1200` | 120.0 | lobster is 120 xp |
| `diamond_cutting` `experience=1075` | 107.5 | diamond cutting is 107.5 xp |
| `bones` `param=bone_exp,45` | 4.5 | burying bones is 4.5 xp |
| `magic_logs` `param=productexp,3038` | 303.8 | magic logs firemaking |

Divide by 10 on extraction, store real XP in `recipes.json`, and the report never has
to think about it again.

### `product,<obj>,<n>` is a batch cap, not a yield

This one will silently produce a 15× wrong answer if you get it backwards.

```
[fletching_bronze_arrow]
data=item,bronze_arrowheads
data=product,bronze_arrow,15      <- NOT "makes 15 arrows"
data=experience,13
```

> **Right, and it is worse than one reading:** the same column means *both* things in the
> same file. In `bolts.dbrow`, `make_bolts` reads `product,opal_bolt,10` as a batch cap
> while `make_bolt_tips` reads `product,opal_bolttips,12` as a real yield — and which
> handler a row goes to is decided by an explicit `case opal, smalloysterpearls,
> bigoysterpearls` label in `uncut_gem.rs2`, not by anything in the table.

`arrows.rs2` reads that `15` as `$max_count` — the most the action will process in one
click — then deletes `$arrows_count` supplies and grants
`multiply($arrows_count, experience)`. So it is **1 tip + 1 headless arrow → 1 arrow,
1.3 xp**, fifteen at a time. The number in the row is UI batching, not a recipe
multiplier. Always read the `.rs2` that consumes a table before trusting the table's
shape.

### The tables only name *one* input

`fletching_table` has an `item` column and a `product` column. Arrows take a headless
arrow *and* a tip; headless arrows take a shaft *and* a feather; the second ingredient
only exists in the script:

```
inv_del(inv, feather, $arrow_count);
inv_del(inv, arrow_shaft, $arrow_count);
```

So `build_recipes.py` needs a co-input table keyed by dbrow id, hand-written and
reviewed. It's small — a few dozen lines across the whole game — but it is the part
that will rot when Content updates, so it should fail loudly: if a dbrow id in the
co-input table no longer exists, the build errors rather than silently dropping the
recipe.

## The data file

One new artifact, built rarely (same cadence as `items.json`), served static:

```jsonc
// data/recipes.json
{
  "fletch_string_yew_longbow": {
    "skill": "fletching",
    "level": 70,
    "xp": 75,
    "in":  [{ "id": 66, "n": 1 }, { "id": 1777, "n": 1 }],   // unstrung yew longbow + bow string
    "out": [{ "id": 855, "n": 1 }],
    "tools": [],
    "src": "skill_fletching/configs/stringing/bows.dbrow#stringing_yew_longbow"
  },
  "fletch_cut_yew_longbow": {
    "skill": "fletching",
    "level": 70,
    "xp": 75,
    "in":  [{ "id": 1515, "n": 1 }],
    "out": [{ "id": 66, "n": 1 }],
    "tools": [946],                                           // knife
    "src": "skill_fletching/configs/cut_logs/cut_logs.dbrow#fletching_yew"
  }
}
```

Notes on the shape:

* **Item ids, not slugs.** Everything downstream (`.sav`, `items.json`, `prices.json`)
  is keyed by numeric game id; recipes should be too. Slugs go in `src` for humans.
* **`src` is mandatory.** Every recipe cites the file and row it came from. Same
  discipline as the tier badges — an estimate is never presented as a fact.
* **`tools` is advisory.** You need a knife, you don't consume it. Use it to warn
  ("you hold no knife"), never to zero out the estimate.
* Probabilistic recipes carry their success model rather than pretending to be
  deterministic (see below).

## Chains are the whole problem

Raw logs are not one recipe deep. A bank holding yew logs and bow string and nothing
else can cut unstrung bows *and then* string them — two XP grants off one log — and a
calculator that only matches direct recipes reports roughly half the truth.

So the model is a small bill-of-materials solve, not a lookup:

1. Build a graph: item → recipes that consume it → products → recipes that consume
   *those*.
2. Walk it from what the bank actually holds, consuming stock as you go.
3. Stop at the first product with no further recipe in the chosen skill.

The greedy walk is fine, and should be stated as a deliberate choice rather than an
approximation nobody noticed: when two recipes compete for the same input, take the
one with more XP per input. For fletching that's exactly right — longbow beats shortbow
at every tier. Where it isn't, show the branch taken and let the reader flip it.

Depth needs a cap and a cycle guard. Content has round trips (filled bucket → empty
bucket → filled bucket) that will otherwise spin forever.

## One input, many skills — never total them

Yew logs are Fletching XP or Firemaking XP, not both. Iron ore is Smithing. A herb is
Herblore. Any single "your bank is worth 14M XP" number is a lie by double-counting,
and it would be the most quotable number on the page — which is exactly why it must
not exist.

The report is **per skill**, each computed as if you spent the whole bank on that
skill, with contention shown explicitly:

```
Fletching   1,847,300 xp    yew logs also feed Firemaking
Firemaking    998,600 xp    same 12,300 yew logs
```

Same reasoning as reporting bank value excluding and including rares side by side: show
both framings rather than picking one and hiding the choice.

## Level gates need the stats block, which the parser currently skips

`savParser.js` already walks past exactly what's needed:

```js
// stats: 21 skills, each (exp:int32, level:byte)
for (let i = 0; i < 21; i++) {
  p.g4s(); // exp
  p.g1();  // level
}
```

Capturing those into `parsed.stats` is a handful of lines, and is the only parser change
this feature needs.

Two caveats:

> **Both caveats held, and a third one appeared.** The mapping is the engine's RS2 order
> (attack, defence, strength, hitpoints, ranged, prayer, magic, cooking, woodcutting,
> fletching, fishing, firemaking, crafting, smithing, mining, herblore, agility, thieving,
> slayer, farming, runecraft) — slots 18 and 19 are the unimplemented ones and always read
> zero. The level check pinned it across four saves. But the anomaly is not only hitpoints:
> **the stored byte is the *current* level, not the base level**, so it is drained by damage
> *and* by praying. Base level has to be computed from xp; the byte is kept as `current`.

* **The index → skill mapping must be verified, not assumed.** Content's
  `scripts/player/configs/stat.constant` lists 19 named stats (attack=1 … fletching=19)
  while the save writes 21 slots. Don't guess the offset. There's a free check: for
  every stat, `level` should equal `levelFor(exp)` — except Hitpoints, which starts at
  level 10 / 1,154 xp. That single anomaly pins the mapping against any real save.
* **The XP curve is computed, not stored.** Standard RS: level *L* needs
  `floor( Σ(n=1..L-1) floor(n + 300 × 2^(n/7)) / 4 )`. Ten lines, no data file.

With levels in hand the report can say the thing players actually want — *1.8M xp:
74 → 91* — and grey out recipes above the current level, with a toggle for "show
everything, I'll level up on the way", which is the truthful default for a long grind
since you *do* unlock the better recipe partway through.

## Some skills aren't deterministic

Cooking burns. Gem cutting fails. Those rows carry a success model in Content:

```
data=successchance,38,332
data=successchance_gauntlets,55,368
```

— a low/high pair interpolated across the level range, plus a variant for cooking
gauntlets. So cooked-food XP is an *expectation*, not a count, and it moves as you level.

v1 should ship deterministic skills only and label the probabilistic ones as not yet
covered, rather than quietly reporting an expected value as though it were a total.

> **Shipped a shade differently.** Cooking is excluded wholesale, as planned. But the odd
> roll inside an otherwise deterministic skill turned out to be worth keeping rather than
> dropping — iron smelting (flat 50%), opal/jade/topaz cutting and pottery firing
> (level-scaled). They carry a `chance` field, are rendered with an `estimate` badge, and
> their contribution is tallied separately so the skill header can say what fraction of
> itself is an expectation. Sapphire, emerald, ruby, diamond and dragonstone cutting have
> no roll at all and are ordinary recipes.
When they land they need their own badge, the same way `ask` is tiered apart from
`market`.

## Scope ladder

| Step | Scope | Why here |
|---|---|---|
| 0.1 | Fletching only, direct recipes, no chains | Proves the extractor against the cleanest data in the repo |
| 0.2 | Chains (logs → unstrung → strung), tool warnings | The first genuinely useful answer |
| 0.3 | All deterministic dbrow skills, plus the param skills | Extractor generalises; no new UI |
| 0.4 | Stats block, level gates, "74 → 91" | Needs the parser change |
| 0.5 | gp per xp, and the value delta of processing | The thing only this repo can say |
| later | Probabilistic skills, struct-driven herblore brewing | Needs the success model and a new badge |

Steps 0.1 through 0.5 shipped together, and 0.3 went wider than planned: fletching,
crafting, smithing, herblore (including struct-driven brewing, which landed early because
`brew_potion.struct` turned out to be completely mechanical), firemaking, runecraft, prayer
and magic. Still open: cooking, and a proper success model for the rolls that are currently
reported as expectations.

## Risks

* **Content drift.** Build 274 is pinned today. The co-input table and any hardcoded
  `.rs2` values are the fragile parts; make the build fail loudly on a missing row id
  rather than dropping recipes silently.
* **Missing recipes are invisible.** Same failure mode as prices: a missing recipe just
  makes a number smaller and nobody notices. It wants the `?audit` treatment — a
  synthetic bank holding one of every item, rendered through the real path, so an
  unreachable recipe shows up as a row that produces nothing.
* **Scope creep into a full skill planner.** "How long will that take" needs actions per
  hour, which is not in Content and would be the first invented number in the project.
  Leave it out — or take it from `preservation-sim`, which already models action rates
  and says where they came from.
