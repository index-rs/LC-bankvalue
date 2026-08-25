// xp.js — turns bank contents + data/recipes.json into "what is this bank
// worth in XP, per skill".
//
// The other currency players hold banks in. Same file, same catalog as the gp
// report; the only new input is the recipe table built by build_recipes.py.
//
// Four ideas do most of the work here:
//
//   1. **Never total across skills.** Yew logs are Fletching xp *or* Firemaking
//      xp, never both. A single "your bank is worth 14M xp" number would be a
//      lie by double-counting, and it would be the most quotable number on the
//      page — so it does not exist. Every skill is solved independently, as if
//      you spent the whole bank on it, and items fought over by two skills are
//      named explicitly.
//
//   2. **Chains, not lookups.** A bank holding yew logs and bow string can cut
//      unstrung bows *and then* string them — two xp grants off one log. Only
//      matching recipes against what you literally hold reports about half the
//      truth, so the solve consumes stock, adds the products back, and goes
//      round again.
//
//   3. **One stated tie-break, which you can overrule.** When two recipes want
//      the same item, the one paying more xp per unit of that item wins. That
//      is a deliberate choice, not an approximation nobody noticed: for
//      fletching it is exactly right (longbow beats shortbow at every tier).
//      But it is not the only sane plan — "how does it decide steel or mithril
//      out of my coal" is a question with a personal answer, so every item two
//      or more recipes compete for becomes a choice the reader can pin, and
//      the walk re-runs against it.
//
//   4. **A shop is not a wall.** Battlestaff crafting eats a 7,000 gp staff
//      per orb, and nobody banks those — you buy them on the way. An input
//      Content marks as shop stock does not cap the plan; the shortfall is
//      counted, priced, and reported as something to go and buy.

(function () {
  // Standard RS xp curve. Ten lines, no data file: level L needs
  // floor( sum(n=1..L-1) floor(n + 300 * 2^(n/7)) / 4 ).
  const XP_TABLE = (() => {
    const table = [0];
    let points = 0;
    for (let n = 1; n < 99; n++) {
      points += Math.floor(n + 300 * Math.pow(2, n / 7));
      table.push(Math.floor(points / 4));
    }
    return table;
  })();

  const MAX_LEVEL = 99;
  const XP_CAP = 200000000;

  function levelFor(xp) {
    let level = 1;
    for (let i = 1; i < XP_TABLE.length; i++) {
      if (xp >= XP_TABLE[i]) level = i + 1;
      else break;
    }
    return level;
  }

  function xpForLevel(level) {
    return XP_TABLE[Math.max(0, Math.min(MAX_LEVEL, level) - 1)];
  }

  // Skills this tool can answer for, in the order they read best: the ones a
  // bank is usually stocked for first.
  const SKILL_ORDER = [
    'fletching', 'crafting', 'smithing', 'herblore', 'firemaking',
    'runecraft', 'prayer', 'magic',
  ];

  const SKILL_LABELS = {
    fletching: 'Fletching', crafting: 'Crafting', smithing: 'Smithing',
    herblore: 'Herblore', firemaking: 'Firemaking', runecraft: 'Runecrafting',
    prayer: 'Prayer', magic: 'Magic',
  };

  // What a nature rune is worth spending on, best first.
  //
  // The old rule was "cheapest first", chosen so the report could never imply
  // you would alch your best armour. That is a fine tiebreak and a poor plan:
  // it spent 39,000 casts on bronze arrows, which pays 1 gp each and is
  // nothing anyone does. These are the things players actually alch — high
  // alch value relative to what the item sells for — and within a tier the
  // most valuable goes first, so a bank holding magic and yew longbows alchs
  // the magic ones.
  //
  // Anything not on the list is still eligible, after all of it, and still
  // cheapest-first: that half of the old rule was right.
  const ALCH_PRIORITY = [
    {
      label: 'Bows',
      // Strung or unstrung, every wood. Anchored so it cannot catch
      // `bow_string` or `bowl_empty`, and `crossbow` fails it too.
      test: (item) => /(^|_)(short|long)bow$/.test(item.slug),
    },
    {
      label: 'Platebodies',
      // Rune excluded as asked. Trimmed and god-plate variants live in
      // treasure_trails and are collector items — alching one is a mistake
      // however good the alch value looks.
      test: (item) => item.slug.includes('platebody')
        && !item.slug.startsWith('rune_platebody')
        && item.category !== 'treasure_trails',
    },
    {
      label: 'Dragonhide armour',
      // Bodies, chaps and vambraces — the finished armour, not the raw hides,
      // which sit in the crafting category and are worth more as leather.
      test: (item) => item.category === 'equipment'
        && (item.slug.includes('dragonhide') || item.slug.includes('dragon_vamb')),
    },
    {
      label: 'Gold amulets',
      test: (item) => /^(un)?strung_gold_amulet$/.test(item.slug),
    },
  ];

  // Safety rail for the walk, and a performance one rather than a correctness
  // one: every recipe the walk will fire has to consume something it does not
  // hand straight back (the `net` check below), and stock is finite integers,
  // so the loop provably runs dry on its own. The cap only bounds how long
  // that takes.
  //
  // It is set high because Content has genuine round trips and one of them is
  // useful. An empty bucket becomes a bucket of sand, which becomes molten
  // glass and an empty bucket again — so five buckets and 10,000 soda ash is
  // 2,000 laps of a two-recipe loop, and the old cap of 400 stopped a fifth of
  // the way in and called the answer truncated. Real banks and the
  // one-of-everything audit still settle inside 35 passes and pay nothing for
  // the headroom; the cap costs time only when the walk genuinely needs it,
  // and 20,000 passes is about 60ms.
  const MAX_PASSES = 20000;

  function mergeStock(containers) {
    const sets = Array.isArray(containers) ? { bank: containers } : containers || {};
    const stock = new Map();
    ['bank', 'inventory', 'worn'].forEach((source) => {
      (sets[source] || []).forEach((it) => {
        stock.set(it.id, (stock.get(it.id) || 0) + it.count);
      });
    });
    return stock;
  }

  function unitPrice(id, itemsDb, pricesDb) {
    const item = itemsDb[String(id)];
    const price = pricesDb[String(id)];
    if (!item || !item.tradeable) return 0;
    return price && price.price != null ? price.price : 0;
  }

  function itemName(id, itemsDb) {
    const item = itemsDb[String(id)];
    return item ? item.name || item.slug : `Item ${id}`;
  }

  // Expected xp for one action. A recipe with a roll pays its full xp on a hit
  // and (for gem cutting) a quarter on a miss, but the honest headline is the
  // expectation — reported as such, and tallied separately so the skill total
  // can say how much of itself is an estimate.
  function expectedXp(recipe, level) {
    const chance = recipe.chance;
    if (!chance) return recipe.xp;
    if (chance.kind === 'flat') return recipe.xp * chance.p;
    // A random *yield* (ogre arrow shafts: 2-6 per log, xp paid per shaft) is
    // stored already averaged, so there is nothing to weight here — but it is
    // still an estimate, and `chance` being set is what makes the report say so.
    if (chance.kind === 'randomYield') return recipe.xp;
    if (chance.kind === 'level') {
      // `stat_random(skill, low, high)` is an engine command, not Content, so
      // this models it rather than reading it: interpolate low..high across
      // levels 1..99 and roll against 256. Good to within a fraction of a
      // percent, which is well inside what "estimate" already promises.
      const t = Math.max(0, Math.min(1, (level - 1) / (MAX_LEVEL - 1)));
      const rate = chance.low + (chance.high - chance.low) * t;
      const p = Math.max(0, Math.min(1, rate / 256));
      // A miss on gem cutting still pays a quarter (uncut_gem.rs2:54); a miss
      // on a smelt or a firing pays nothing. `quarterOnMiss` says which.
      const consolation = chance.quarterOnMiss ? 0.25 : 0;
      return recipe.xp * p + recipe.xp * consolation * (1 - p);
    }
    return recipe.xp;
  }

  // How many runes one essence binds, which grows with level
  // (runecraft.rs2:83). Applied at the player's level as it stands, so the gp
  // side of the report reflects what they'd walk out of the altar with today.
  //
  // Deliberately not re-evaluated as the solve levels them up: a bank that
  // takes runecraft 81 -> 92 really would start yielding more runes per essence
  // partway through, so the gp-out figure here is a floor. The xp is unaffected
  // either way — it is paid per essence, not per rune.
  function outputCount(recipe, out, level) {
    if (recipe.yieldPerLevel) {
      return out.n * (Math.floor(level / recipe.yieldPerLevel) + 1);
    }
    return out.n;
  }

  // --- the solve ----------------------------------------------------------

  function solveSkill(skill, recipeList, baseStock, opts) {
    const { itemsDb, pricesDb, level, capToLevel, noAlch } = opts;
    const choices = opts.choices || {};

    const stock = new Map(baseStock);
    const consumed = new Map(); // id -> qty taken out of the original bank
    const produced = new Map(); // id -> qty of things that ended up made
    const bought = new Map();   // id -> qty of shop stock the plan assumes you buy
    const steps = [];
    const byKey = new Map();

    let totalXp = 0;
    let estimatedXp = 0; // the slice of totalXp that came from a roll
    let alchCoins = 0;   // coins alchemy hands back, which are a real product
    let fees = 0;        // coins paid to NPCs on the way, e.g. the tanner
    let spend = 0;       // coins paid to shops for `buy` ingredients
    let truncated = false; // did the walk hit MAX_PASSES with work left to do?

    // recipeList is [key, recipe] pairs — destructure, or every recipe reads
    // as undefined and the filter silently empties the whole skill.
    const usable = recipeList.filter(([, r]) => !capToLevel || r.level <= level);

    // What the walk is allowed to run. `usable` is everything this level
    // reaches; `active` is what survives the reader's own choices. The two are
    // kept apart on purpose: the alternatives listed under each step are drawn
    // from `usable`, so pinning nature runes still shows what law would have
    // paid rather than hiding the road not taken.
    const reachable = new Set(usable.map(([key]) => key));
    const active = usable.filter(([key, r]) =>
      r.in.every((input) => {
        const pick = choices[input.id];
        // A pin on a recipe this level cannot reach goes inert rather than
        // emptying the fork. Otherwise ticking "only recipes I can use now"
        // would silently delete a whole branch of the plan and leave no
        // control on screen to put it back.
        return !pick || !reachable.has(pick) || pick === key;
      }));

    // A shop-stock ingredient (`buy` in recipes.json) never caps the plan.
    // Nobody banks battlestaves — Zaff sells them five at a time — so what
    // matters is not whether you hold one but what the trip costs.
    function isBought(recipe, id) {
      return !!(recipe.buy && recipe.buy.indexOf(id) !== -1);
    }

    // What a shop input costs to replace. The market price is what a player
    // would actually pay; `cost` is the shop's own number and is the floor
    // under it, used when nothing has traded.
    function buyPrice(id) {
      return unitPrice(id, itemsDb, pricesDb) || (itemsDb[String(id)] || {}).cost || 0;
    }

    // Alchemy and its cousins consume "one item, any item" alongside their
    // runes. The target is chosen from the bank rather than invented here, and
    // cheapest-first, so the report never implies you would alch your best
    // armour to make the number bigger.
    function alchTier(item) {
      for (let i = 0; i < ALCH_PRIORITY.length; i++) {
        if (ALCH_PRIORITY[i].test(item)) return i;
      }
      return ALCH_PRIORITY.length;
    }

    function alchTargets(recipe) {
      // A spell cannot be paid for with the same runes it destroys. Content
      // lets you alch spare fire and nature runes, but only while enough are
      // left to cast (alchemy.rs2:80-89) — and the cast count here was already
      // worked out from that stock, so eating any of it would spend the same
      // runes twice.
      const reagents = new Set(recipe.in.map((i) => i.id));
      const targets = [];
      stock.forEach((qty, id) => {
        if (reagents.has(id)) return;
        const item = itemsDb[String(id)];
        if (!item || !item.tradeable || item.rare) return;
        if (!item.cost) return; // nothing to alch it for
        if (noAlch && noAlch.has(id)) return; // Content refuses these
        // Noted items are not alch targets. They have no config block of
        // their own in Content — they exist only in obj.pack — so the game
        // reads their cost as 0 and a cast would pay 1 gp. items.json copies
        // the base item's cost onto them, which is right for valuing a noted
        // stack and wrong here.
        if (item.notedOf) return;
        targets.push({
          id,
          qty,
          tier: alchTier(item),
          cost: item.cost,
          price: unitPrice(id, itemsDb, pricesDb),
        });
      });
      return targets.sort((a, b) =>
        (a.tier - b.tier) ||
        // Inside a priority tier, alch value first. Past the list, back to
        // cheapest-first, so the leftovers eaten are the ones you'd miss least.
        (a.tier < ALCH_PRIORITY.length ? b.cost - a.cost : a.price - b.price));
    }

    function timesRunnable(recipe) {
      let times = Infinity;
      for (const input of recipe.in) {
        if (isBought(recipe, input.id)) continue; // buy as many as the rest allow
        const have = stock.get(input.id) || 0;
        times = Math.min(times, Math.floor(have / input.n));
        if (times <= 0) return 0;
      }
      // No inputs at all, or nothing but shop stock — not a bank recipe. The
      // second case matters: without it a recipe whose every ingredient can be
      // bought would run forever off an empty bank.
      if (times === Infinity) return 0;
      return times;
    }

    // The stated tie-break: score a recipe by the worst rate it pays across
    // its inputs, so a recipe demanding two coal per action is ranked on the
    // coal, not on the one iron ore.
    function score(recipe) {
      let worst = Infinity;
      for (const input of recipe.in) {
        worst = Math.min(worst, expectedXp(recipe, level) / input.n);
      }
      return worst > 0 ? worst : lookahead(recipe);
    }

    // A step that pays nothing is a prerequisite, not a choice. Tanning hides
    // costs coins and gives no xp, so on its own score it would sort below
    // literally everything and only fire once the walk had nothing better to
    // do — which works, but says nothing about *which* conversion to pick.
    //
    // So a zero-xp step is scored by the best rate its product unlocks. That
    // also settles cowhide, where the answer moves with level: hard leather is
    // 35 xp a hide, soft leather tops out at 27 until coifs open at 38 and
    // make it 37.
    function lookahead(recipe) {
      const inputUnits = recipe.in.reduce((sum, i) => sum + i.n, 0) || 1;
      let best = 0;
      for (const out of recipe.out) {
        for (const [, other] of active) {
          if (other === recipe || other.anyItem) continue;
          const slot = other.in.find((i) => i.id === out.id);
          if (!slot) continue;
          const rate = (expectedXp(other, level) / slot.n) * (out.n / inputUnits);
          if (rate > best) best = rate;
        }
      }
      return best;
    }

    // Every product made from a given bar pays the same xp per bar, so a whole
    // tier of smithing recipes ties on score. Break the tie on what the
    // product is worth: the xp is identical either way, and picking at random
    // would make the gp line meaningless.
    function tieBreak(recipe) {
      return recipe.out.reduce(
        (sum, o) => sum + o.n * unitPrice(o.id, itemsDb, pricesDb), 0);
    }

    // Which input ran out first. That is the one the recipe was really
    // competing for, and so the one an alternative has to be measured against.
    //
    // Must be read BEFORE the step spends anything. Called afterwards it sees
    // the drained stock, matches nothing, and falls through to the first
    // ingredient — which is how "Smelt steel bar ×444" came to report itself
    // limited by iron ore when a bank holding 1,291 iron ore and 889 coal is
    // plainly limited by the coal.
    function limitingInput(recipe, times) {
      for (const input of recipe.in) {
        if (isBought(recipe, input.id)) continue; // a shop never runs you out
        if (Math.floor((stock.get(input.id) || 0) / input.n) === times) return input;
      }
      return recipe.in.find((i) => !isBought(recipe, i.id)) || recipe.in[0];
    }

    function fire(recipe, key, times) {
      const buying = [];
      const limit = limitingInput(recipe, times); // before any stock moves
      recipe.in.forEach((input) => {
        const take = input.n * times;
        if (isBought(recipe, input.id)) {
          // Whatever is already banked counts first; only the shortfall is a
          // trip to the shop. Stock floors at zero rather than going negative,
          // so a bought ingredient never reads as debt to the rest of the walk.
          const have = Math.max(0, stock.get(input.id) || 0);
          const short = Math.max(0, take - have);
          if (short) {
            bought.set(input.id, (bought.get(input.id) || 0) + short);
            spend += short * buyPrice(input.id);
            buying.push({ id: input.id, n: short, each: buyPrice(input.id) });
          }
          stock.set(input.id, have - (take - short));
          consumed.set(input.id, (consumed.get(input.id) || 0) + take);
          return;
        }
        stock.set(input.id, (stock.get(input.id) || 0) - take);
        consumed.set(input.id, (consumed.get(input.id) || 0) + take);
      });
      recipe.out.forEach((out) => {
        const made = outputCount(recipe, out, level) * times;
        stock.set(out.id, (stock.get(out.id) || 0) + made);
        produced.set(out.id, (produced.get(out.id) || 0) + made);
      });

      if (recipe.fee) fees += recipe.fee * times;
      const each = expectedXp(recipe, level);
      const gained = each * times;
      totalXp += gained;
      if (recipe.chance) estimatedXp += gained;

      const existing = byKey.get(key);
      if (existing) {
        existing.times += times;
        existing.xp += gained;
        buying.forEach((b) => {
          const already = existing.buying.find((x) => x.id === b.id);
          if (already) already.n += b.n;
          else existing.buying.push(b);
        });
      } else {
        const step = {
          key,
          recipe,
          limit,
          label: recipe.label,
          level: recipe.level,
          xpEach: each,
          times,
          xp: gained,
          aboveLevel: recipe.level > level,
          chance: recipe.chance || null,
          quest: recipe.quest || null,
          fee: recipe.fee || 0,
          note: recipe.note || null,
          src: recipe.src,
          in: recipe.in,
          out: recipe.out,
          tools: recipe.tools || [],
          buying,
        };
        byKey.set(key, step);
        steps.push(step);
      }
    }

    for (let pass = 0; pass < MAX_PASSES; pass++) {
      let best = null;
      let bestScore = -Infinity;
      let bestTimes = 0;

      for (const [key, recipe] of active) {
        if (recipe.anyItem) continue; // handled after the deterministic walk
        const times = timesRunnable(recipe);
        if (!times) continue;
        // Skip a recipe that hands back everything it took — a round trip
        // would otherwise spin the loop without moving any stock.
        const net = recipe.in.some((input) => {
          const back = recipe.out.find((o) => o.id === input.id);
          return !back || back.n < input.n;
        });
        if (!net) continue;
        const s = score(recipe);
        if (s > bestScore + 1e-9 ||
            (Math.abs(s - bestScore) <= 1e-9 && best && tieBreak(recipe) > tieBreak(best[1]))) {
          bestScore = Math.max(s, bestScore);
          best = [key, recipe];
          bestTimes = times;
        }
      }

      if (!best) break;
      fire(best[1], best[0], bestTimes);
      if (pass === MAX_PASSES - 1) truncated = true;
    }

    // "One item, any item" spells, once the ordinary chains have run: the
    // runes cap the casts, and so does the supply of things worth alching.
    for (const [key, recipe] of active) {
      if (!recipe.anyItem) continue;
      let casts = timesRunnable(recipe);
      if (!casts) continue;
      const targets = alchTargets(recipe);
      let available = targets.reduce((sum, t) => sum + t.qty, 0);
      casts = Math.min(casts, available);
      if (!casts) continue;

      let remaining = casts;
      const eaten = [];
      for (const target of targets) {
        if (remaining <= 0) break;
        const take = Math.min(target.qty, remaining);
        stock.set(target.id, (stock.get(target.id) || 0) - take);
        consumed.set(target.id, (consumed.get(target.id) || 0) + take);
        eaten.push({ id: target.id, n: take });
        remaining -= take;
      }
      fire(recipe, key, casts);
      const step = byKey.get(key);
      step.eaten = eaten;
      // Alchemy pays out in coins, at the rate Content uses:
      // max(cost * rate, 1) per cast (alchemy.rs2:25).
      if (recipe.alchRate) {
        step.coins = eaten.reduce((sum, e) => {
          const item = itemsDb[String(e.id)];
          const each = Math.max(1, Math.round((item.cost || 0) * recipe.alchRate));
          return sum + each * e.n;
        }, 0);
        alchCoins += step.coins;
      }
    }

    // What else that same stock could have become.
    //
    // The walk reports one answer per skill, but "highest xp per unit" is a
    // stated choice, not the only sane one — a runecrafter with 400k essence
    // wants to see the whole ladder, not just the top rung, because law runes
    // being worth more xp than nature does not make nature the wrong call.
    // So every step carries what the *same* limiting stock would have paid
    // through the recipes that lost.
    //
    // Only recipes that pay a different rate are listed. A whole tier of
    // smithing ties exactly (same xp per bar whatever you hammer), and listing
    // eight identical numbers would say nothing.
    //
    // Rate is measured per unit of the limiting item, not per action, which is
    // what makes "steel or mithril out of my coal" answerable: those two want
    // two coal and four, so comparing them action-for-action compares nothing.
    steps.forEach((step) => {
      const limit = step.limit;
      const alternatives = [];
      const perUnit = limit ? step.xpEach / limit.n : 0;
      const limitQty = limit ? step.times * limit.n : 0;
      if (limit) {
        for (const [otherKey, other] of usable) {
          if (other === step.recipe || other.anyItem) continue;
          const slot = other.in.find((i) => i.id === limit.id);
          if (!slot) continue;
          const each = expectedXp(other, level);
          if (Math.abs(each / slot.n - perUnit) < 1e-9) continue;
          // An alternative is only worth as much as its *other* ingredients
          // allow. 14,583 iron ore is 255k xp of steel bars on paper and 1.5k
          // in practice if the bank holds 168 coal — offering the paper figure
          // would be the same double-counting the per-skill split exists to
          // avoid, one level down. Measured against the original bank, since
          // that is what "if you had spent it this way instead" means.
          let times = Math.floor(limitQty / slot.n);
          let capped = false;
          for (const input of other.in) {
            if (input.id === limit.id) continue;
            if (other.buy && other.buy.indexOf(input.id) !== -1) continue;
            const possible = Math.floor((baseStock.get(input.id) || 0) / input.n);
            if (possible < times) {
              times = possible;
              capped = true;
            }
          }
          if (times <= 0) continue;
          alternatives.push({
            key: otherKey,
            on: limit.id,
            label: other.label,
            level: other.level,
            xpEach: each,
            times,
            capped,
            xp: each * times,
            aboveLevel: other.level > level,
          });
        }
        alternatives.sort((a, b) => b.xp - a.xp);
      }
      step.alternatives = alternatives.slice(0, 5);
      step.altMore = Math.max(0, alternatives.length - 5);
      if (limit) {
        step.limitName = itemName(limit.id, itemsDb);
        step.limitQty = limitQty;
      }
      delete step.recipe;
      delete step.limit;
    });

    // The choices this bank actually presents.
    //
    // A group is one item that two or more reachable recipes compete for, and
    // that the plan really spent — so it is never a hypothetical menu of the
    // whole skill, only the forks this bank walks past. Coal is the one the
    // question always gets asked about: steel, mithril, adamantite and runite
    // all want it, at two, four, six and eight a bar.
    //
    // Options are rated per unit of the contested item for the same reason the
    // alternatives above are: a runite bar pays 50 xp to a steel bar's 17.5 and
    // is still the worse use of coal.
    const choiceGroups = [];
    consumed.forEach((qty, id) => {
      const options = [];
      for (const [key, recipe] of usable) {
        if (recipe.anyItem) continue;
        const slot = recipe.in.find((i) => i.id === id);
        if (!slot) continue;
        if (recipe.buy && recipe.buy.indexOf(id) !== -1) continue; // shop stock, not a fork
        options.push({
          key,
          label: recipe.label,
          level: recipe.level,
          aboveLevel: recipe.level > level,
          perUnit: expectedXp(recipe, level) / slot.n,
          n: slot.n,
          value: tieBreak(recipe),
        });
      }
      if (options.length < 2) return;
      // Same order the walk itself uses: rate first, then what the product is
      // worth, so a whole tier of smithing (all 37.5 xp a bar) reads down from
      // the most valuable thing to hammer rather than in table order.
      options.sort((a, b) => (b.perUnit - a.perUnit) || (b.value - a.value));
      choiceGroups.push({
        id,
        name: itemName(id, itemsDb),
        qty,
        options,
        // What the auto walk did with this item, so a reader who has not
        // chosen anything can still see which branch was taken.
        autoKeys: steps.filter((st) => st.in.some((i) => i.id === id))
          .map((st) => st.key),
        // The xp riding on the decision, used to order the controls: the top
        // option applied to everything this item was spent on.
        stake: options[0].perUnit * qty,
      });
    });
    choiceGroups.sort((a, b) => b.stake - a.stake);

    // gp: what went in, and what came out and survived. A product that a later
    // recipe ate is not counted twice — only stock still standing at the end.
    let valueIn = fees + spend;
    consumed.forEach((qty, id) => {
      const fromBank = Math.min(qty, baseStock.get(id) || 0);
      valueIn += fromBank * unitPrice(id, itemsDb, pricesDb);
    });
    let valueOut = alchCoins;
    produced.forEach((qty, id) => {
      const left = Math.max(0, Math.min(qty, stock.get(id) || 0));
      valueOut += left * unitPrice(id, itemsDb, pricesDb);
    });

    steps.sort((a, b) => b.xp - a.xp);

    return {
      skill,
      label: SKILL_LABELS[skill] || skill,
      steps,
      truncated,
      fees,
      spend,
      totalXp,
      estimatedXp,
      valueIn,
      valueOut,
      consumed,
      choiceGroups,
      shopping: [...bought.entries()].map(([id, n]) => ({
        id, n, name: itemName(id, itemsDb), each: buyPrice(id),
      })).sort((a, b) => b.n * b.each - a.n * a.each),
      itemName: (id) => itemName(id, itemsDb),
    };
  }

  /**
   * Solve every covered skill against one bank.
   *
   * `stats` is savParser's stats block ({ fletching: { xp, current }, ... });
   * pass null and every skill is treated as level 1 with nothing banked, which
   * is what the sample report does.
   */
  function solve(containers, itemsDb, pricesDb, recipesDb, stats, options) {
    const opts = options || {};
    const capToLevel = !!opts.capToLevel;
    const allChoices = opts.choices || {};
    const baseStock = mergeStock(containers);

    const bySkill = new Map();
    Object.entries(recipesDb.recipes).forEach(([key, recipe]) => {
      if (!bySkill.has(recipe.skill)) bySkill.set(recipe.skill, []);
      bySkill.get(recipe.skill).push([key, recipe]);
    });

    // Which skills want which items — the contention map, built before any
    // stock is spent so it describes the bank rather than one skill's walk.
    const wantedBy = new Map(); // itemId -> Set(skill)
    bySkill.forEach((list, skill) => {
      list.forEach(([, recipe]) => {
        recipe.in.forEach((input) => {
          if (!baseStock.has(input.id)) return;
          if (!wantedBy.has(input.id)) wantedBy.set(input.id, new Set());
          wantedBy.get(input.id).add(skill);
        });
      });
    });

    const heldTools = new Set([...baseStock.keys()]);
    const noAlch = new Set((recipesDb.meta && recipesDb.meta.noAlch) || []);
    const results = [];

    SKILL_ORDER.forEach((skill) => {
      const list = bySkill.get(skill);
      if (!list) return;
      const stat = stats && stats[skill];
      const currentXp = stat ? stat.xp : 0;
      const level = levelFor(currentXp);

      // Always solve once with nothing pinned. That pass is what the choice
      // controls are built from, so the menu of forks stays put no matter what
      // the reader picks — pin "mithril bar" with no mithril ore in the bank
      // and the coal fork has to still be there to un-pin.
      const auto = solveSkill(skill, list, baseStock, {
        itemsDb, pricesDb, level, capToLevel, noAlch,
      });
      const choices = allChoices[skill] || null;
      const result = choices
        ? solveSkill(skill, list, baseStock, {
            itemsDb, pricesDb, level, capToLevel, noAlch, choices,
          })
        : auto;
      result.choiceGroups = auto.choiceGroups;
      result.choices = choices || {};
      // What the chosen plan gave up against the default one. Stated rather
      // than silently absorbed: overruling the tie-break is a real decision and
      // it usually costs xp.
      result.autoXp = auto.totalXp;
      if (!result.steps.length && !auto.steps.length) return;

      const endXp = Math.min(XP_CAP, currentXp + result.totalXp);
      result.baseXp = currentXp;
      result.baseLevel = level;
      result.endXp = endXp;
      result.endLevel = levelFor(endXp);
      result.toNextLevel = level < MAX_LEVEL ? xpForLevel(level + 1) - currentXp : 0;
      result.knownStats = !!stat;

      // Items this skill's plan takes that another covered skill also has a
      // use for, biggest contested holding first.
      result.contention = [];
      result.consumed.forEach((qty, id) => {
        const others = wantedBy.get(id);
        if (!others || others.size < 2) return;
        const rivals = [...others].filter((s) => s !== skill && bySkill.has(s));
        if (!rivals.length) return;
        result.contention.push({
          id,
          name: itemName(id, itemsDb),
          qty: Math.min(qty, baseStock.get(id) || 0),
          value: Math.min(qty, baseStock.get(id) || 0) * unitPrice(id, itemsDb, pricesDb),
          skills: rivals.map((s) => SKILL_LABELS[s] || s),
        });
      });
      result.contention.sort((a, b) => b.value - a.value);

      // Tools are advisory: you need a knife, you don't consume it, and not
      // holding one never zeroes an estimate — it just gets said out loud.
      const missing = new Map();
      result.steps.forEach((step) => {
        (step.tools || []).forEach((id) => {
          if (!heldTools.has(id)) missing.set(id, itemName(id, itemsDb));
        });
      });
      result.missingTools = [...missing.entries()].map(([id, name]) => ({ id, name }));

      delete result.consumed;
      delete result.itemName;
      delete auto.consumed;
      delete auto.itemName;
      results.push(result);
    });

    results.sort((a, b) => b.totalXp - a.totalXp);

    return {
      skills: results,
      capToLevel,
      choices: allChoices,
      knownStats: !!stats,
      meta: recipesDb.meta || {},
    };
  }

  window.BankXP = {
    solve, levelFor, xpForLevel, SKILL_ORDER, SKILL_LABELS, MAX_LEVEL,
  };
})();
