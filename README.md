# Lost City Bank Value Calculator

Estimate what a [Lost City](https://lostcity.rs) (2004scape) bank is worth in gp.

Drop in your `.sav` file, get a categorised valuation. **The save file never leaves your
browser** — parsing happens client-side, nothing is uploaded. That's not a policy promise,
it's how it's built: the site is static files, there's no server to upload to.

Runs on GitHub Pages. No build step, no framework, no dependencies.

## How it works

```
your .sav  ──▶  js/savParser.js  ──▶  bank contents  ──┐
                (in your browser)                       │
                                                        ▼
                                          data/items.json + data/prices.json
                                                        │
                                                        ▼
                                                  js/report.js
```

Two data files are committed to the repo and served as static JSON:

| File | Built by | How often | What it is |
|---|---|---|---|
| `data/items.json` | `scripts/build_catalog.py` | rarely (on content updates) | Every item in the game: id, name, alch cost, category, tradeable flag |
| `data/prices.json` | `scripts/scrape_prices.py` | daily, via GitHub Actions | Current value per item, with a confidence tier |
| `data/history.json` | `scrape_prices.py` + `backfill_history.py` | daily / occasionally | Completed sales, 28-day window for current pricing plus older ones as a fallback |

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
| `market` | Blended from order-book mid `(bid+ask)/2` and the median of recent completed coin sales |
| `bid` | Only a standing buy offer — a real floor, someone is offering that |
| `ask` | Only a standing sell listing — what a seller *hopes* to get. Nothing proves anyone pays it |
| `dose` | Potion priced per-dose from its dose family's best-sampled variant |
| `charge` | Charged jewellery priced off its family's fully-charged variant |
| `noted` | A noted (`cert_`) item, priced from its base item |
| `stale` | No recent trade, but it has sold before — a real old price beats a guess |
| `alch` | No market data; high alch (`cost × 0.6`) minus the nature rune to cast it |
| `vendor` | Worth less than the rune needed to alch it; low alch / shop value (`cost × 0.4`) |
| `unfinished` | An unfinished potion, priced as its herb plus a vial of water |
| `junk` | Vendor tools and clothing nobody trades — deliberately 0 |
| `container` | A filled bucket, priced as the empty one |
| *untradeable* | Can't be sold — counted as 0, not reported as a gap |
| *unknown* | Tradeable but genuinely no price on file |

Every line in the report shows its tier, so an estimate is never presented as a
market fact.

**Potions are priced per dose.** A bank holding 1×(4), 100×(3) and 1×(1) of the same potion
holds 104 doses; pricing every variant off one shared per-dose rate is more accurate and
fills in dose variants that never trade on their own.

**Charged jewellery is normalised.** Only the fully-charged variant trades in volume, so
partial ones would otherwise fall back to alch and be wildly wrong. Two models: amulets of
glory price every charge level (uncharged included) at the glory(4) price, since recharging
is free at the Fountain of Heroes; rings of dueling and games necklaces scale with charges
remaining, since those are consumed rather than recharged.

**Categories follow how players think, not how slugs are spelled.** Rune *equipment*
(`rune_platebody`) is not a *rune* (`naturerune`) — the two look alike as strings and rune
gear was burying the actual runes. Herblore holds herbs, secondaries and unfinished potions;
runecrafting holds essence and talismans. Explicit per-slug overrides in `lc_items.py` win
over every keyword rule.

**Junk is valued at 0 and hidden.** Non-stacking skilling tools and vendor clothing —
hammers, needles, moulds, fishing rods, wizard robes — sell for a few gp from any general
store and are never actively traded. Counting them adds noise, not value. A toggle in the
report reveals them along with untradeables.

**Categories:** Coins, Rares, Runes, Runecrafting, Ammunition, Weapons, Armour, Jewellery,
Potions, Herblore, Crafting / Fletching, Food, Logs, Ores & Bars, Gems, Bones, Seeds, Other,
Junk. Each gets a colour-coded bar showing its share of the total, and there are
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

## Running the scrapers locally

Python 3.12+. No dependencies — standard library only.

```bash
python scripts/build_catalog.py     # rebuild the item catalog (rarely needed)
python scripts/backfill_history.py  # deep sale history for slow-moving items (slow, occasional)
python scripts/scrape_prices.py     # refresh prices (fast, daily)
```

`backfill_history.py` is the one that makes the long tail work. The daily feed only sees
~24 hours of trades, so anything that sells a few times a month was falling back to alch —
body runes trade at a steady 14gp but were being valued at 2. It walks per-item pages
(one request each, ~0.8s apart) and is resumable, so Ctrl-C is safe.

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
        savParser.js  .sav decoder
        report.js   categorisation, totals, rendering
        main.js     file input wiring
data/   items.json, prices.json, history.json
scripts/  build_catalog.py, scrape_prices.py, lc_market.py, lc_items.py
```

`savs/` holds real save files used for local testing. It is **git-ignored** —
saves contain real character data (stats, position, full bank contents) and are never
committed or published.

## Credits

Item data from [LostCityRS/Content](https://github.com/LostCityRS/Content). Market data from
[Lost City Markets](https://markets.lostcity.rs), whose source is
[open](https://github.com/LostCityRS/Markets). The `.sav` format is implemented from
[LostCityRS/Engine-TS](https://github.com/LostCityRS/Engine-TS)'s `PlayerLoading.ts`.

Unofficial fan tool. Not affiliated with the Lost City project.
