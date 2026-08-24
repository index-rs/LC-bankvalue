# Lost City Bank Value Calculator

Estimate what a [Lost City](https://lostcity.rs) (2004scape) bank is worth — in gp, and in XP.

Drop in your `.sav` file, get a categorised valuation and, on a second tab, what that same
bank is worth in each skill you could spend it on. **The save file never leaves your
browser** — parsing happens client-side, nothing is uploaded. That's not a policy promise,
it's how it's built: the site is static files, there's no server to upload to.

Runs on GitHub Pages. No build step, no framework, no dependencies.

## How it works

```
your .sav  ──▶  js/savParser.js  ──▶  bank contents + stats
                (in your browser)                │
                     ┌───────────────────────────┴───────────────────────────┐
                     ▼                                                       ▼
          items.json + prices.json                            items.json + recipes.json
                     ▼                                                       ▼
               js/report.js                                             js/xp.js
          "worth 24.1M gp"  Value tab                "1.8M Fletching xp, 94 → 96"  XP tab
```

Four data files are committed to the repo and served as static JSON:

| File | Built by | How often | What it is |
|---|---|---|---|
| `data/items.json` | `scripts/build_catalog.py` | rarely (on content updates) | Every item in the game: id, name, alch cost, category, tradeable flag |
| `data/prices.json` | `scripts/scrape_prices.py` | daily, via GitHub Actions | Current value per item, with a confidence tier |
| `data/history.json` | `scrape_prices.py` + `backfill_history.py` | daily / occasionally | Completed sales, 60-day window for current pricing plus older ones as a fallback |
| `data/recipes.json` | `scripts/build_recipes.py` | rarely (on content updates) | Every XP-paying thing you can make from bank stock: inputs, outputs, level, xp, and where in Content it was read from |

### The item catalog is authoritative, not guessed

`build_catalog.py` reads Lost City's own published content
([LostCityRS/Content](https://github.com/LostCityRS/Content), build 274):

* `pack/obj.pack` — the numeric item id ↔ slug map. **These are the same ids `.sav` files
  use**, so every item in a bank resolves, including ones that have never been traded.
* `scripts/**/*.obj` — each item's name, `cost` (alch base), and `tradeable` flag.

This matters a lot. Market activity alone only covers items that are actively trading
(~300 of 3,894). Reading the game's own content took bank coverage from **30% to 100%** of
items resolved, and means an item with no market price can be correctly reported as
*untradeable* rather than *unknown*.

`pack/inv.pack` also gives the bank's inventory type id (`95=bank`), so the parser reads the
bank by id rather than guessing at the biggest inventory.

### Pricing

`scrape_prices.py` reads three feeds from
[markets.lostcity.rs](https://markets.lostcity.rs) (~56 requests, ~1 minute):

* `/sales` — completed sales → real transaction prices
* `/?tab=buy` — active buy listings → best bid
* `/?tab=sell` — active sell listings → best ask

Price per item, best available evidence first:

| Tier | Meaning |
|---|---|
| `market` | Blended from order-book mid `(bid+ask)/2` and the quantity-weighted median of recent completed coin sales |
| `bid` | Only a standing buy offer — a real floor, someone is offering that |
| `ask` | Only a standing sell listing — what a seller *hopes* to get. Nothing proves anyone pays it |
| `dose` | Potion priced per-dose off its family's 3-dose variant, where nearly all the trading happens |
| `charge` | Charged jewellery priced off its family's fully-charged variant |
| `enchant` | Plain gem jewellery, capped at what its enchanted form sells for |
| `fixed` | A hand-set price, overriding every tier below and the live market too |
| `recipe` | Priced from the materials it's made of — molten glass is a bucket of sand plus soda ash |
| `bulk` | A real per-unit price with no depth behind it — discounted, since the stack can't be sold at the price one buyer pays for one |
| `sameAs` | Worth exactly what another item is worth — filled buckets, broken tools, tool heads, tanned leather, soda ash |
| `noted` | A noted (`cert_`) item, priced from its base item |
| `stale` | No recent trade, but it has sold before — a real old price beats a guess |
| `alch` | No market data; high alch (`cost × 0.6`) minus the nature rune to cast it |
| `vendor` | Worth less than the rune needed to alch it; low alch / shop value (`cost × 0.4`) |
| `unfinished` | An unfinished potion, priced from its materials (herb + vial of water) |
| `junk` | Vendor tools and clothing nobody trades — shop value, hidden by default |
| `container` | A filled bucket, priced as the empty one |
| *untradeable* | Can't be sold — counted as 0, not reported as a gap |
| *unknown* | Tradeable but genuinely no price on file |

Every line in the report shows its tier, so an estimate is never presented as a
market fact.

**Potions are poured into doses.** A bank holding 1×(4), 100×(3) and 1×(1) of the same
potion holds 104 doses, and every dose of a potion is the same thing — so the whole family
gets one per-dose rate and the report shows it as a single row measured in doses
(`Super strength · 343×(4), 4×(3), 1×(2) · ×1,386 doses · ≈347 ×(4) · 1,558 /dose`). That
cuts a real bank's Potions section from 35 rows to 12. Doses are the honest unit but nobody
stocks a bank in them, so each row also carries what the pile comes to in 4-dose potions —
`=` when it divides evenly, `≈` when it doesn't.

**The 3-dose variant sets that rate.** Potions are brewed as (3)s and there's no easy way to
decant, so that's where the trading is — 87% of all dose-family volume — and the other
variants are byproducts whose thin markets say more about scarcity than about what a dose is
worth. Super strength(4) was the proof: two month-old sales totalling 89 units priced it at
3,000 while super strength(3) had four recent sales and a live 3,500 bid, so a (4) came out
worth *less* than a (3) it strictly contains. Families that never trade as (3)s fall back to
their best-evidenced variant — the agility potion only ever sells as a (4).

Sacred oil hid the same bug behind its naming: it numbers doses as a suffix
(`sacred_oil4`), which the dose parser didn't recognise, so the (4) read 2,500 off 1,406
traded units while the (3), (2) and (1) fell to vendor value — 625gp a dose against 12.
Serum 207 and waterskins share that naming but have no market on any variant.

**Charged jewellery is normalised.** Only the fully-charged variant trades in volume, so
partial ones would otherwise fall back to alch and be wildly wrong. Two models: amulets of
glory price every charge level (uncharged included) at the glory(4) price, since recharging
is free at the Fountain of Heroes; rings of dueling and games necklaces scale with charges
remaining, since those are consumed rather than recharged. Under the glory model the anchor
wins even where the variant has sales of its own — an uncharged glory going for less is buyers
pricing in the walk to the fountain, not a different item.

**Unenchanted jewellery is capped at its enchanted form.** Enchanting is slow, fiddly work
— runes, magic level, a lot of clicking — so nobody pays a premium for the plain piece. When
a thin market quotes one higher (a sapphire necklace at 1,000gp beside a games necklace(8) at
975) that's noise, and the enchanted item's price is the better answer for both. The cap only
bites upward; trading below the enchanted form is normal and left alone. See `ENCHANT_PRODUCT`
in `lc_items.py`.

**Categories follow how players think, not how slugs are spelled.** Rune *equipment*
(`rune_platebody`) is not a *rune* (`naturerune`) — the two look alike as strings and rune
gear was burying the actual runes. Herblore holds herbs, secondaries and unfinished potions;
runecrafting holds essence and talismans. Explicit per-slug overrides in `lc_items.py` win
over every keyword rule.

**Junk is priced at shop value and hidden.** Non-stacking skilling tools and vendor
clothing — hammers, needles, moulds, fishing rods, wizard robes — sell for a few gp from any
general store and are never actively traded, so whatever thin listing exists on one is noise.
A shop counter is still a real exit, though, so they carry vendor value rather than a zero:
one of every junk item in the game comes to about 12k, which can't move a bank's total but
does mean a stack of 500 buckets is counted. A toggle in the report reveals them along with
untradeables.

The same list absorbs items whose only market is the occasional single-unit convenience
sale. Swamp tar was reading 8,500gp off two one-at-a-time trades — it picks up off the ground
by the hundred, and if anyone did buy it in quantity, collectors would flatten the price
inside a week. Toad's legs, raw rat meat, ugthanki kebabs and the tool handles (an axe handle
was worth 5,555gp on the strength of one player who collects them and isn't buying) went the
same way.

**Treasure Trails have their own category.** Clue rewards are priced by scarcity, not by
their (usually identical) combat stats: a gilded platebody is rune armour that alchs for 38k
and sells for 30M. Scattered through Armour and Other they made a bank's most valuable
holdings the hardest to find. Build 274 carries the 2004 reward table — black/adamant/rune
trimmed (t) and gold-trimmed (g) sets, the three rune god sets, gilded rune, the god book
torn pages, and the cosmetic headwear and boots. The bronze/iron/steel/mithril trimmed sets
and the heraldic items came later and aren't in this build; see the OSRS wiki's
[Ornamental armour](https://oldschool.runescape.wiki/w/Ornamental_armour) and
[Gilded equipment](https://oldschool.runescape.wiki/w/Gilded_equipment) pages for the full
modern table.

**A few items carry a hand-set price.** Cannon parts trade as a four-piece set, so whichever
part a sale happened to be posted under swallowed the whole cannon's price (a base at 650k
beside a furnace sitting on its 112k alch value); soul runes see so few sales that one whale
bid dragged the median. Both are pinned: 180k a cannon part, 1,500 a soul rune.

The four Fremennik helms are pinned at their 78,000 shop price for a different reason: a
shop sells all four at that price with stock loose enough that scarcity never lifts them
above it. Left to the market they disagreed wildly on thin data — the farseer and warrior
helms have never recorded a sale at all and rested on a 35,662 alch guess, while the archer
helm read 70,000 from a single sale in June.

The table is `FIXED_PRICES` in `lc_items.py` and is meant to stay short — a price that merely
looks off belongs in a fallback rule, since anything listed here stops tracking the market
entirely.

**Some families are priced by fiat, not by the market.** Thrown weapons, low-tier bolts and
bolt tips take vendor price; the melee families nobody trades — claws, warhammers, maces,
daggers, halberds, battleaxes, spears, longswords — take alch value, dragon excepted, since
those genuinely trade. A handful of listings on a mithril halberd says more about the lister
than the item.

The Shilo Village gems are here too — opal, jade and red topaz, cut and uncut. They come out
of gem rocks by the thousand and have never recorded a coin sale between players, so the only
thing that ever moves their price is somebody's asking price: a 1,000gp ask appeared on a red
topaz mid-session, 12x its shop value, which on a bank holding 20,000 of them is 20M out of
thin air. So is the spinach roll, on three single-unit sales at 1.9M-2.5M against an alch
base of 1gp.

The risk in that rule runs the other way too. The plain battlestaff sat on this list and was
valued at 2,800 while it was quietly one of the most liquid items in the game — 500-unit
blocks changing hands at 7,600-7,750 and standing bids for thousands more. "Any shop stocks
it" is not the same as "nobody buys it from players"; an item only belongs here if the market
is genuinely absent, not merely inconvenient.

**Fletching is its own category.** Bow string, arrow shafts, arrowheads, headless arrows and
every bow below magic-shortbow tier (strung or not) are fletching *stock*, not gear anyone
fights with — the magic shortbow is the one bow that stays in Weapons. Unstrung amulets remain
in Crafting, and unstrung items are renamed ("Unstrung yew shortbow") since the game gives them
the same name as the finished article at a very different price.

**Categories:** Coins, Rares, Runes, Runecrafting, Ammunition, Weapons, Armour, Jewellery,
Potions, Herblore, Crafting, Fletching, Treasure Trails, Food, Logs, Ores & Bars, Gems,
Bones, Seeds, Other, Junk. Each gets a colour-coded bar showing its share of the total, and there are
expand/collapse-all controls.

**Variants fold into their base item.** Poisoned weapons and dragon leather barely trade on
their own, so they're priced as (and displayed with) their base: a bank holding 5,000 rune
arrows and 200 poisoned ones shows one row reading `Rune arrow ×5,200 +200 poisoned`. This
holds even when only the variant is held — 774 poisoned adamant darts and no plain ones still
render as a single `Adamant dart +774 poisoned` line at the plain dart's price.
Dragonhide items all share a name in the game data, so the colour is added back to
distinguish them.

**Set listings are capped.** Full rune sets get posted under "rune platebody", dragonhide
sets under the body, super sets under one of the supers. Those are real coin sales, so
nothing in the data marks them as bundles — the history just goes bimodal, and a median
lands between singles and sets. `BUNDLE_CAPS` in `lc_items.py` rejects the high cluster;
they're calibrated from sale history and documented for retuning.

**Sales are sanity-checked against the order book.** A mistyped listing produces a
*genuine* sale record — someone selling 1,000 blood runes who enters the total instead of the
per-unit price records a real 1gp sale, and nothing about the sale itself marks it as wrong.
Four people bidding 800-900 each do. Any sale more than 10x away from the mean of standing
offers is dropped before the median is taken. This is the mirror of the guard on listings,
and it catches cases the internal outlier trim can't — that trim only works when the bad
values are a minority.

That check is *conditional*, because the order book can be the broken side. A single
1,000,000,000gp ask on an adamant platebody (t) set a floor of 100M, threw away all ten
genuine 15k-45k sales, and left nothing for the ask guard downstream to check that ask
against — so the typo became the price. When the reference rejects **every** sale, the
reference is the suspect and the unfiltered sales are used instead — but only when they
corroborate each other (`MIN_CORROBORATION`, 2+ surviving their own trim). One lone sale that
the whole order book disagrees with really is more likely to be the mistake.

**The current-price window is 60 days.** Most of this catalog is thin. A 28-day window left
slow movers — adamant darts, trimmed armour — with no sale median at all, which is precisely
when a stray listing gets to set the price unopposed. Two months of sales still describes a
current price here, and turns a lot of `stale` rows into `market` ones.

**Thin evidence doesn't get weighted.** Below three surviving sales the quantity weighting
is dropped for a plain median, because weighting needs a distribution to weigh — with one or
two sales the "weighted median" is just whichever side moved more units. Super strength(4)
showed it: 59 units at 3,000 against 30 at 5,500 came out as 3,000 flat, below the 3-dose
potion it strictly contains. Two sales support a midpoint and nothing finer.

**Sales are weighted by quantity.** One person buying a single lockpick "for doors" at
10,000 and someone else moving fifty at 4,900 are not equal evidence about what a lockpick is
worth, but an unweighted median counts them one apiece — so the convenience trade wins on
count alone and a bank full of bulk goods gets valued at prices nobody could liquidate into.
Weighting by units traded puts lockpicks at 4,900 instead of 7,000 and drops the tool's
worst offenders across the board.

The outlier trim still runs *unweighted*, deliberately. Letting quantity pick the trim window
would hand a single enormous trade the power to define what counts as an outlier, and the one
1,000,000,000gp sale in this dataset is booked against a quantity of two million.

**Some items have no bulk market at all.** Lockpicks trade all day at 5-7k, in ones and twos,
to someone who wants a door opened today: about 85 units in two months. The per-unit price is
real and the depth is not, so `BULK_UNSELLABLE` marks the stack down by half. It's a blunt
constant standing in for per-item traded volume, which the price file now records (`volume`)
but doesn't yet spend.

**A standing offer far from where an item actually sells is a typo or a troll**, on either
side of the book. A santa hat read 110,000,084gp — the midpoint of a 169gp bid and a
220,000,000gp ask — with real 170-220M sales on file the whole time. Offers more than
`ERROR_RATIO` away from what the item has sold for are dropped before the mid is taken.

The mirror of that guard, sales checked against the book, treats the two sides differently.
Bids are real coins, so they bound sales tightly in both directions. Asks only floor them,
and loosely (`ASK_FLOOR_RATIO`): sellers ask over the market constantly, and letting one do
the tight job read the water talisman at 16,312 against a real 500-1,000 market — a lone
10,000gp ask rejected all 29 units of genuine 500gp sales as implausibly cheap, leaving two
1-unit sales at 20,000 to set both the price and the window it was judged against. The loose
ask floor still earns its place: with no bids at all, it's the only thing standing between a
purple partyhat and a 1gp sale.

**Bids and asks are not equal evidence.** A one-sided *ask* is just someone's asking price —
one absurd listing (a chaos talisman at 350k when every other talisman trades under 10k) can
move a whole bank's total. Ask-only values are kept, because for some items they're the only
signal, but they're tiered separately and the report warns when they're a meaningful slice of
the total.

**Barter trades are ignored.** Only coin-denominated trades price an item — valuing an
item-for-item swap would need the very prices we're trying to compute.

### Rares are totalled separately

Party hats, santa hats, halloween masks, christmas crackers, easter eggs, pumpkins,
half full wine jugs and the disk of returning are reported as their own total, because
their prices are collector-driven, swing hard, and can dwarf an entire normal bank —
one santa hat can be 10× everything else combined. The report shows **bank value excluding
rares** and **including rares** side by side.

Rares are never alch-estimated. A half full wine jug has `cost=1` but trades for millions,
so an alch guess would be wrong by six orders of magnitude. With no market data they stay
unpriced and are reported as such.

## Banked XP

The Value tab answers *what is my bank worth in gp*. The XP tab answers *what is my bank
worth in XP* — the other currency players actually hold banks in.

```
Fletching   94 → 96                                     1,775,551 xp
  10.9M gp of stock in → 7.39M gp out   the xp costs you 3.6M gp · 2.03 gp per xp
  Cut yew logs into longbows       ×22,328   75 xp    1,674,600
  Cut oak logs into longbows        ×3,949   25 xp       98,725
  Attach feathers to arrow shafts   ×2,226    1 xp        2,226
  Also wanted elsewhere. Yew logs ×22,328 Firemaking · Oak logs ×3,949 Firemaking
```

That gp line is the part no standalone XP calculator can do, because no other calculator
already knows what the stock is worth.

### The recipes are read from the game, not typed from a wiki

Same discipline as the item catalog. `build_recipes.py` walks the same
[Content build 274](https://github.com/LostCityRS/Content) tarball, and **every recipe
carries a `src`** naming the file and block it was read out of:

```jsonc
"fletch_string_yew_longbow": {
  "skill": "fletching", "level": 70, "xp": 75,
  "in":  [{ "id": 66, "n": 1 }, { "id": 1777, "n": 1 }],
  "out": [{ "id": 855, "n": 1 }],
  "src": "scripts/skill_fletching/configs/stringing/bows.dbrow#stringing_yew_longbow",
  "note": "skill_fletching/scripts/bows.rs2:39 inv_del(inv, bow_string, 1)"
}
```

XP lives in Content in four different shapes, and three of them are extracted mechanically:

| Shape | Example | Skills |
|---|---|---|
| `.dbrow` rows against a `.dbtable` | `stringing/bows.dbrow` | fletching, gem cutting, leather, smithing, runecraft, magic |
| `param=` on the item itself | `yew_logs` carries `param=productexp,2025` | firemaking, prayer, herb identification |
| `.struct` named param bags | `smelting.struct` | smelting, jewellery, spinning, pottery, glass, studded, battlestaves, potion brewing |
| a literal in an `.rs2` script body | `stat_advance(fletching, multiply($arrow_count, 10))` | scattered one-offs |

The fourth can't be extracted, so it's a short hand-written table (`LITERALS`) with a
`file:line` citation per entry — same spirit as `FIXED_PRICES` in `lc_items.py`. The
hand-maintained parts **fail the build loudly** rather than silently dropping recipes: if a
slug or block they name stops existing, `build_recipes.py` errors out.

### A config row is not a shipped recipe

The extractor's first version treated "this row exists in Content" as "you can do this in
the game". Those are different claims, and the gap between them is invisible in the output.

Lost City is pinned to a 2004 snapshot, but some tables carry rows for content that arrived
later. `runecraft.dbrow` has a death rune row — level 65, 10 XP an essence, the best rate in
the table — so the solver happily told everyone to bind death runes. **Death runecrafting
was added in mid-to-late 2005.** The row is there; the way in is not.

The test that catches it: every tool a recipe requires should appear somewhere that could
put it in a player's hands — a drop table, a shop, a spawn, a quest reward. Grep the whole
`scripts/` tree for the slug, excluding `.obj`/`.param`/`.dbtable` (which say what an item
*is*, not where it comes from) and `/_test/` (cheat commands).

Run across all 22 tool items, exactly one came back empty: `death_talisman` appears only in
`obj.pack`, its own `runecraft.obj` definition, and `_test/scripts/cheats/cheat_bank.rs2`.
Every other talisman has at least one real source — `law_talisman` comes from `quest_death`
and `quest_troll`. The row has a second tell too: it is the only one in the table whose
`enter_coord` and `exit_coord` are both just the `altar_coord`, where every released altar
has distinct ones.

So it lives in `UNRELEASED` with that reasoning attached, the build errors out if the row it
names ever disappears, and `build_recipes.py` re-runs the tool-source grep on every build
and warns about anything new. That check is a warning rather than an error because it is a
grep heuristic, and a false positive shouldn't block a rebuild — but a new name in it means
a row wants looking at.

Two traps in that data, both of which produce a wrong answer rather than an error:

**Everything is in tenths.** `stat_advance` takes tenths of an xp point, so
`experience=750` is 75.0 xp. Divided out on extraction. *The save file is in tenths too* —
a fletching field reading 130,344,716 is 13,034,471.6 xp, which is level 99.

**`product,<obj>,<n>` means two different things.** `make_bolts` reads the 10 in
`product,opal_bolt,10` as a per-click batch cap (1 tip → 1 bolt), while `make_bolt_tips`
reads the 12 in `product,opal_bolttips,12` as a real yield (1 opal → 12 tips). Same table,
same column; which applies is a property of the consuming `.rs2`. Get it backwards and the
number is 15× wrong. Always read the script that consumes a table before trusting the
table's shape.

### One bank, spent many ways — never totalled

Yew logs are Fletching XP *or* Firemaking XP, never both. Iron ore is Smithing. A single
"your bank is worth 14M xp" number would be a lie by double-counting, and it would be the
most quotable number on the page — which is exactly why it doesn't exist.

Each skill is solved independently, as if you spent the whole bank on it, and the items two
skills both want are named along with the rival skill, so the contention is visible rather
than resolved behind your back. Same reasoning as reporting bank value excluding and
including rares side by side: show both framings rather than picking one and hiding the
choice.

### Chains, and the one tie-break

Raw logs are not one recipe deep. A bank holding yew logs and bow string can cut unstrung
bows *and then* string them — two XP grants off one log — so the solve consumes stock, adds
the products back, and goes round again until nothing more can fire.

When two recipes want the same item, **the one paying more XP per unit of that item wins.**
That's a deliberate choice, not an approximation nobody noticed. A recipe is scored on the
worst rate it pays across its inputs, so steel — one iron ore *and two coal* — is ranked on
the coal rather than on the ore.

Ties are broken on what the product is worth — a whole tier of smithing recipes pays the
same XP per bar, so the XP is identical either way and picking at random would make the gp
line meaningless.

**Steps that pay nothing are scored by what they unlock.** Tanning gives no XP and costs
coins, but every `craft_leather_table` row wants tanned leather, so without it a bank of
700 dragonhide reads as worth zero Crafting — which it did, until it didn't. On its own
score a zero-XP step sorts below everything; instead it takes the best rate its product
unlocks. That also settles cowhide, where the right answer moves with level:

| Crafting level | tans into | because |
|---|---|---|
| 30 | hard leather, 3 gp | hardleather body, 35 XP a hide |
| 70 | soft leather, 1 gp | coif opens at 38 and pays 37 |

Those steps are badged `prep`, show the fee per unit rather than an XP rate, and their
total cost lands in the skill's gp line — 14K gp to tan 700 hides is a real cost of the
43,400 XP it leads to.

**And the roads not taken are shown.** One answer per skill is not the same as the only
sane answer: law runes pay more XP per essence than nature, which does not make nature the
wrong call. So every step lists what the same limiting stock would have paid through the
recipes that lost:

```
Bind law runes                    ×467,727   9.5 xp   4,443,407
  Same 467,727 rune essence instead —
  Bind nature runes 4.21M · Bind chaos runes 3.98M · Bind cosmic runes 3.74M
  · Bind body runes 3.51M · Bind fire runes 3.27M  +4 more
```

Alternatives are capped by their *own* ingredients, which matters more than it sounds.
14,583 iron ore is 255K XP of steel bars on paper and 1.5K in a bank holding 168 coal; the
paper figure would be the same double-counting the per-skill split exists to prevent, one
level down. Where an alternative is short it shows the count it could actually reach
(`Smelt steel bar ×84`). Recipes that tie exactly on XP aren't listed — eight identical
numbers say nothing.

### Levels come from the save, and are computed, not read

`savParser.js` now captures the stats block, which is what gives the *94 → 96* line. Two
things about it are not obvious, and both were verified rather than assumed:

* **The 21 stat slots are the engine's RS2 order**, which is not the order in Content's
  `stat.constant` (19 entries). The check that pins it: for every stat, the stored level
  byte should equal the level the xp implies. Across four real saves — 84 stats — that held
  everywhere except hitpoints in three and prayer in one, which is exactly the pair of stats
  that get *drained*.
* **The level byte is the current level, not the base level**, for that same reason. Base
  level is computed from xp with the standard curve (ten lines, no data file).

Recipes above your level are shown greyed with a `lvl N` badge by default — for a long
grind that's the truthful default, since you *do* unlock the better recipe partway through.
A toggle restricts the solve to what you can make right now.

### What it doesn't cover, and says so

A missing recipe just makes a number smaller and nobody notices — the same failure mode as
a missing price. So the gaps are listed in the UI, from `notCovered` in `recipes.json`:

* **Cooking** — every recipe carries a burn roll (`successchance` in
  `cooking_generic.dbrow`), so a total would be an expectation dressed up as a count.
* **Woodcutting, mining, fishing** — gathered from the world, not made from bank stock.
* **Agility, thieving, combat** — no item input.

Whole missing skills are the easy case. The dangerous omission is a recipe missing from a
skill that otherwise works, since that still *looks* like an answer — so those are listed
too, in `knownGaps`. Currently: superheat item and the Crafting half of wolf-bone arrow
tips (both pay two skills off one action, which the one-skill-per-recipe schema can't
express), cape dyeing and snelm carving.

**Raw materials count.** Hides are tanned at the Al Kharid tanner — 1 gp for soft leather,
3 for hard, 20 a dragonhide (`tanner.constant`) — and the report assumes you'll do it,
rather than treating raw hide as inert. The Canifis werewolf tanner charges 2/5/45 and
isn't modelled; nobody walks past Al Kharid to pay double.

**Quest content ships.** The ogre arrow chain needs Big Chompy Bird Hunting, and it is
included rather than dropped — a player knows whether they've done the quest, and leaving
it out made a whole fletching line silently missing. Those steps carry a `quest` badge
naming the requirement. Two of the four have a random yield (`~random_range(2, 6)` shafts
or tips per log or bone, with the xp paid per unit), so their counts and their xp are both
averages, and they're badged `estimate` alongside the burn-style rolls.

Recipes that *can* fail but are otherwise ordinary are kept, flagged `estimate`, and their
contribution is tallied separately so the skill header can say how much of itself is an
expectation: iron smelting (a flat 50% unless you wear a ring of forging), opal/jade/topaz
cutting, and pottery firing (level-scaled rolls).

### What alchemy eats

Alchemy is the odd one out: it consumes one *arbitrary* item per cast alongside its runes,
so the target has to come from the bank rather than be invented.

The first rule was "cheapest first", so the report could never imply you'd alch your best
armour. Defensible as a tiebreak, useless as a plan — it spent 39,000 casts on bronze
arrows at 1 gp each, which is nothing anyone does. It now works down the list players
actually alch, most valuable first inside each tier:

| | matched as |
|---|---|
| 1. Bows, strung and unstrung | slug ends `_longbow` / `_shortbow`, anchored so `bow_string` and `bowl_empty` can't sneak in |
| 2. Platebodies, not rune | slug contains `platebody`, minus `rune_platebody*` and minus the trimmed/god plates in `treasure_trails`, which are collector items |
| 3. Dragonhide armour | `equipment` category, bodies/chaps/vambraces — not the raw hides, which are worth more as leather |
| 4. Gold amulets | `strung_gold_amulet` / `unstrung_gold_amulet` |

Anything else is still eligible, after all of that, still cheapest-first. On a real bank
that turns *"39,036 items, cheapest first — mostly Bronze arrow ×23,761"* into
*"39,036 items, in priority order — Magic longbow ×26,652"*, and the coins the casts pay
back go from 58K to 41M.

Two exclusions matter more than they look:

**Noted items are not alch targets.** They have no config block of their own anywhere in
Content — they exist only as an id and a slug in `obj.pack` — so the game reads their cost
as 0 and a cast would pay 1 gp. `build_catalog.py` copies the base item's cost onto them,
which is right for valuing a noted stack in the gp report and wrong here. Without this, a
bank of noted magic longbows would have gone straight to the top of tier 1 at a price the
game doesn't agree with.

**A spell can't be paid for with the runes it destroys.** The cast count is worked out from
the rune stock, so letting those same runes be eaten as targets spends them twice. Content
does allow alching spare fire and nature runes, but only while enough remain to cast
(`alchemy.rs2:80-89`).

## Running the scrapers locally

Python 3.12+. No dependencies — standard library only.

```bash
python scripts/build_catalog.py     # rebuild the item catalog (rarely needed)
python scripts/build_recipes.py     # rebuild the XP recipe table (rarely needed)
python scripts/backfill_history.py  # deep sale history for slow-moving items (slow, occasional)
python scripts/scrape_prices.py     # refresh prices (fast, daily)
```

`backfill_history.py` is the one that makes the long tail work. The daily feed only sees
~24 hours of trades, so anything that sells a few times a month was falling back to alch —
body runes trade at a steady 14gp but were being valued at 2. It walks per-item pages
(one request each, ~0.8s apart) and is resumable, so Ctrl-C is safe.

**What gets deepened is decided by evidence, never by tier.** This used to skip anything
already reading `market`, which meant a bad price protected itself from the data that would
have corrected it: molten glass caught a single 50,000gp novelty sale, became `market`, and
so was never eligible to have its real market read — 3,600 units at 1,900-2,000, sitting
unread on its own item page the whole time. Now an item is deepened unless its price is a
`market` one off three or more sales with at least one inside 30 days. Prices copied from
another item (dose variants, noted items, filled buckets) are skipped, since the evidence
lives on the item they copy from; `recipe`, `unfinished` and `cloth` prices are *not*,
because each of those rules steps aside for a real market price and should be allowed to.

**It's a rolling refresh, not a one-shot.** State records when each item was last looked at,
so a `--limit`ed run takes the least recently checked. The daily workflow spends 40 lookups
(~32s) before each price refresh, which drains the backlog and stops it re-forming. Molten
glass was the first thing it fixed: `recipe 1,612` became `market 1,988` off nine sales.

Each item page carries **both** months of sale history and the item's currently standing
buy/sell offers, so it also catches quiet items the paginated feeds miss entirely —
adamantite ore had a live 1,000gp buy offer and a 1,000gp sale and was still being priced at
its 160gp vendor value. Standing offers land in `data/book.json`; live feed data always wins.

To preview the site:

```bash
python -m http.server 8123
```

then open <http://localhost:8123>. A server is required — the page `fetch()`es its data
files, which browsers block on `file://`.

## Layout

```
index.html
css/    base.css + two themes (terminal / editorial), toggled and persisted
js/     packet.js  byte reader ported from the engine's Packet.ts
        savParser.js  .sav decoder (bank, inventory, worn, stats)
        report.js   categorisation, totals, rendering        — Value tab
        xp.js       recipe chain solve, per skill            — XP tab
        xpReport.js rendering for the XP tab
        main.js     file input wiring, tab switching
data/   items.json, prices.json, history.json, recipes.json
scripts/  build_catalog.py, build_recipes.py, scrape_prices.py, lc_market.py, lc_items.py
```

`savs/` holds real save files used for local testing. It is **git-ignored** —
saves contain real character data (stats, position, full bank contents) and are never
committed or published.

### Audit mode

Open the page with `?audit` for a synthetic bank holding **one of every tradeable item**
(`?audit=all` includes untradeables). The bank is built in-browser from `data/items.json`, so
it can never drift from the catalog.

This is the regression harness for pricing and categorisation. Every item renders through the
real report path, so a mispriced or miscategorised item is visible immediately instead of
waiting for someone to happen to hold one. At one-of-each, a row's total *is* its unit price —
so the top of each category is exactly where a bad price shows up first, and the tier badges
show at a glance which items are resting on thin evidence.

It also runs a **drift check between the two builders**. `items.json` and `recipes.json` are
keyed by the same numeric game ids but generated by different scripts against different parts
of Content, so a rebuild that drops an item the recipes still name would quietly cost the XP
tab those recipes. The audit status line reports it either way: *"354 recipes, every
ingredient resolves."*

What `?audit` is **not** is a recipe *coverage* harness. The original plan was that a recipe
which never fires against a bank holding one of everything would be one that can't be reached
— but that isn't what happens. 242 of 354 never fire there, and nearly all of them lost to a
rival recipe competing for the same input, which is the solver working correctly. Measuring
genuine unreachability needs a separate non-greedy pass, and doesn't exist yet.

## Credits

Item data from [LostCityRS/Content](https://github.com/LostCityRS/Content). Market data from
[Lost City Markets](https://markets.lostcity.rs), whose source is
[open](https://github.com/LostCityRS/Markets). The `.sav` format is implemented from
[LostCityRS/Engine-TS](https://github.com/LostCityRS/Engine-TS)'s `PlayerLoading.ts`.

Unofficial fan tool. Not affiliated with the Lost City project.
