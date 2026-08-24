# Spec: bank diff / loot tracking

Status: **design, not built.** Lower priority than [banked XP](banked-xp.md).

## The idea

Drop in two `.sav` files instead of one. Report the difference.

> Save a copy of your `.sav`, kill 1,000 green dragons, save another. Upload both
> and see exactly what dropped, what it's worth, and what that came to per kill.

The mechanics are nearly free — a diff over two parsed saves is a few dozen lines, and
every hard part (the parser, the catalog, prices, categories, the renderer) already
exists. What makes it worth specifying is that the *interpretation* is not free.

## What a diff actually is

Both saves are parsed with the existing `SavParser`, and the bank/inventory/worn
containers are merged per side the way `buildRows` already merges them. Then it's a
map subtraction over item ids:

```
delta[id] = after[id] - before[id]
```

Gains and losses both matter and read differently, so the report wants two columns
rather than one signed number: **gained** (drops, loot, things you made) and
**spent** (food eaten, runes cast, coins paid, gear lost to a death).

The existing report path takes rows with a `qty` and prices them. A diff row is the
same shape with a signed qty, so `buildRows` and `renderReport` need surprisingly
little: a sign-aware total, a "net change" header instead of a grand total, and colour
for the direction.

## The honest framing problem

A diff is **not** a loot table. Between two saves you also:

* ate food and drank potions
* used runes, arrows, charges
* bought and sold on the market — coins move for reasons unrelated to killing
* died and lost gear
* banked something you'd been carrying for a week

Nothing in the save distinguishes these. The report must not label the delta "loot from
1,000 kills"; it's "what changed between these two saves", and the user is the one
asserting what happened in between. Give them a place to say so — a kill count and a
monster name they type in — and derive *per kill* from their claim, clearly attributed
to them rather than to the data.

Same discipline as the price tiers: show the evidence and its strength, never launder
an assumption into a fact.

## Where `preservation-sim` comes in

`preservation-sim` (the sibling combat/loot simulator) already carries drop tables transcribed
from the same Content build, keyed by the same slugs:

```js
{ id:'cow', name:'Cow', ..., loot:[ always('Cowhide',1,'cow_hide'), always('Raw beef',1,'raw_beef') ] }
```

Those slugs are Content `obj.pack` slugs, and `items.json` maps id → slug. So the two
sides already speak the same language, with no translation layer to build. That makes
one genuinely new thing possible:

**Expected vs observed.** For N kills of a monster the sim gives an expected drop count
per item. The diff gives an actual count. Putting them side by side answers questions
neither tool can answer alone:

```
Green dragon × 1,000                     expected      observed
  Dragon bones                              1,000         1,000
  Green dragonhide                          1,000         1,000
  Rune longsword (1/128)                      7.8             4     -49%
  ...
  gp/kill                                   3,140         2,890     -8%
```

That is a drop-rate check, a sim validation harness, and a "was I unlucky or is my
setup wrong" answer at the same time. It's also the natural regression test for the
sim's drop tables — a real 1,000-kill sample is worth more than any amount of rereading
the `.rs2`.

Note the direction of scepticism: with a few hundred kills, an outlier is variance, not
evidence the table is wrong. Any comparison should show the sampling interval, not just
the point estimate, or it will produce confident nonsense on small samples.

## Unidentified herbs

The one drop that doesn't diff cleanly, and worth writing down because the data says
something counter-intuitive.

**This repo already prices unids per species.** All 14 unids are named just `Herb` in
Content, so `disambiguate_name` renames them ("Herb (Ranarr)") and
`apply_unidentified_herb_pricing` (`scrape_prices.py`) prices each one at its
identified counterpart, always overriding whatever the market quoted. So the diff needs
no help from the sim here — the sim's herb pricing is the weaker of the two.

**The sim's herb EV is the LC market's unid price.** `preservation-sim` maps
`_randomherb_avg -> unidentified_guam` in its own scraper, i.e. it uses the *blended*
unid quote as the value of one `~randomherb` roll. That is a defensible choice, and it
lands almost exactly where the arithmetic does:

| Method | Value of one herb roll |
|---|---|
| Weighted EV — `randomherb` drop weights x this repo's identified prices | **1,916 gp** |
| Actual `unidentified_guam` sales, 60-day window (3 sales, 1,383 herbs) | **1,600-1,700 gp** |
| Sim's scraped `_randomherb_avg` | 1,890 gp |

Two independent routes agreeing inside ~15% is the useful part. The market's unid price
is a lottery-ticket price — buyers can't see the species, because the game shows every
unid as "Herb" — and it sits a little under EV, which is what you'd expect a buyer to
pay for taking the variance and doing the identifying.

The `randomherb` weights are exact, from
`scripts/drop tables/scripts/shared_droptables.rs2`: 32/24/18/14/11/8/6/5/4/3/3 out of
128, guam through dwarf weed. `preservation-sim`'s table matches verbatim.

### So: don't average, except for one number

* **Compare species by species.** The weights are known exactly and the diff observes
  actual species counts, so the comparison should validate the *distribution*, not just
  its mean. That's a stronger test than any averaged figure, and it's the same row shape
  as every other drop.
* **Average only for the gp/kill headline**, where you need one number for the herb
  slot. Use the *weight*-weighted EV (1,916), never a flat mean across the 11 species
  (3,317) — the cheap herbs are the common ones, so an unweighted average runs ~70%
  hot.
* **Members gate.** `randomherb` opens with `if (map_members = ^false) return (coins,
  10)`. On a free world the herb slot is 10 gp, not 1,916. The comparison has to know
  which kind of world the kills happened on.

### The finding that outlives this feature

Unid quotes are *not* the noise the pricing code assumes. Three sales of 302, 1,000 and
81 herbs at 1,600-1,700 are bulk trades, and they corroborate the computed EV. For the
cheap herbs that inverts the current valuation:

| Held as | Identified price | Sold as an unid | Better |
|---|---|---|---|
| Guam | 366 | ~1,600 | **unid, 4.4x** |
| Marentill | 80 | ~1,600 | **unid, 20x** |
| Tarromin | 684 | ~1,600 | **unid, 2.3x** |
| Harralander | 2,350 | ~1,600 | identified |
| Ranarr | 5,700 | ~1,600 | identified |
| Dwarf weed | 9,000 | ~1,600 | identified |

A rational holder takes the better of the two, so "value an unid at its identified
price" is a floor, not the answer, for the four cheapest species.

This is not yet a change to make. All three sales landed inside thirteen hours with no
standing book behind them, which is plausibly one counterparty — thin by the repo's own
`MIN_CORROBORATION` standards, and a lemons market that should decay toward the cheap
herbs once sellers start identifying before listing. What to do now is *record* it: keep
the unid blend as its own number in `prices.json` instead of discarding it, so the diff,
the sim and any future "sell it as an unid" line all read one value from one place, and
so there's a series to watch. Today the only trace of it is in `history.json`.

## Shared price data

The sim currently ships its own `prices.json` and its own `scrape_prices.py`, with
placeholder values in `gamedata.js`. This repo's `data/prices.json` is strictly better
— tiered, sanity-checked against the order book, refreshed daily by CI — and is served
as static JSON from GitHub Pages. Pointing the sim at it is a small change that removes
a whole duplicated scraper, and it would make both tools quote the same number for the
same item, which they currently don't.

One caveat on "strictly better": the sim keeps the blended `unidentified_guam`
quote that this repo deliberately overrides, and that quote is its herb EV. Unifying
the price source means `prices.json` has to carry that number too, or the sim
regresses (see above).

Worth doing regardless of whether the diff feature ever ships.

## UI sketch

Two dropzones, or one dropzone that remembers: drop a save, it becomes the "before",
drop another and the report switches to diff mode. A **before / after / difference**
toggle over the same rendered report, since all three are the same view of different
row sets.

Sessions are the obvious extension — keep a small list of saves in `localStorage`
(item counts only, a few KB, not the file) so you can diff any two points and see a
value-over-time line. That stays inside the privacy promise: the numbers never leave
the browser, same as today.

## Risks and open questions

* **A save is a logout snapshot.** It's written when the character leaves the game, so
  "before" is really "as of last logout", and anything held at the moment of the second
  logout is included. Fine for trip-scale diffs, misleading for anything finer.
* **The value of a diff isn't its gp total.** A trip that converts 500k of food and
  runes into 900k of loot nets 400k, and the interesting number is the 900k, the 500k,
  *and* the ratio — not one headline figure.
* **Untradeables and stack limits.** A delta can be negative on an untradeable
  (a lost pickaxe), which prices at 0 today and would silently vanish from a diff. Diff
  mode probably wants untradeables shown by default, unlike the value report.
* **Scope.** This is a second product sharing a parser. It's worth being explicit that
  it lives behind its own entry point rather than growing the main report, so the
  landing page keeps answering one question well.
