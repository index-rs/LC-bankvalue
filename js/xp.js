// xp.js — turns bank contents + data/recipes.json into "what is this bank
// worth in XP, per skill".
//
// The other currency players hold banks in. Same file, same catalog as the gp
// report; the only new input is the recipe table built by build_recipes.py.
//
// Three ideas do most of the work here:
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
//   3. **One stated tie-break.** When two recipes want the same item, the one
//      paying more xp per unit of that item wins. That is a deliberate choice,
//      not an approximation nobody noticed: for fletching it is exactly right
//      (longbow beats shortbow at every tier), and where it isn't, the step
//      list shows which branch was taken.

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

  // Safety rail for the walk. Content has genuine round trips (a bucket of
  // sand becomes molten glass and an empty bucket), so the loop is bounded
  // rather than trusted to run dry. Real banks and the one-of-everything audit
  // both settle inside 35 passes; if anything ever hits the cap the result is
  // flagged rather than quietly reported short.
  const MAX_PASSES = 400;

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

    const stock = new Map(baseStock);
    const consumed = new Map(); // id -> qty taken out of the original bank
    const produced = new Map(); // id -> qty of things that ended up made
    const steps = [];
    const byKey = new Map();

    let totalXp = 0;
    let estimatedXp = 0; // the slice of totalXp that came from a roll
    let alchCoins = 0;   // coins alchemy hands back, which are a real product
    let truncated = false; // did the walk hit MAX_PASSES with work left to do?

    // recipeList is [key, recipe] pairs — destructure, or every recipe reads
    // as undefined and the filter silently empties the whole skill.
    const usable = recipeList.filter(([, r]) => !capToLevel || r.level <= level);

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
        const have = stock.get(input.id) || 0;
        times = Math.min(times, Math.floor(have / input.n));
        if (times <= 0) return 0;
      }
      if (times === Infinity) return 0; // no inputs at all — not a bank recipe
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
      return worst;
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
    function limitingInput(recipe, times) {
      for (const input of recipe.in) {
        if (Math.floor((stock.get(input.id) || 0) / input.n) === times) return input;
      }
      return recipe.in[0];
    }

    function fire(recipe, key, times) {
      recipe.in.forEach((input) => {
        const take = input.n * times;
        stock.set(input.id, (stock.get(input.id) || 0) - take);
        consumed.set(input.id, (consumed.get(input.id) || 0) + take);
      });
      recipe.out.forEach((out) => {
        const made = outputCount(recipe, out, level) * times;
        stock.set(out.id, (stock.get(out.id) || 0) + made);
        produced.set(out.id, (produced.get(out.id) || 0) + made);
      });

      const each = expectedXp(recipe, level);
      const gained = each * times;
      totalXp += gained;
      if (recipe.chance) estimatedXp += gained;

      const existing = byKey.get(key);
      if (existing) {
        existing.times += times;
        existing.xp += gained;
      } else {
        const step = {
          key,
          recipe,
          limit: limitingInput(recipe, times),
          label: recipe.label,
          level: recipe.level,
          xpEach: each,
          times,
          xp: gained,
          aboveLevel: recipe.level > level,
          chance: recipe.chance || null,
          quest: recipe.quest || null,
          note: recipe.note || null,
          src: recipe.src,
          in: recipe.in,
          out: recipe.out,
          tools: recipe.tools || [],
        };
        byKey.set(key, step);
        steps.push(step);
      }
    }

    for (let pass = 0; pass < MAX_PASSES; pass++) {
      let best = null;
      let bestScore = -Infinity;
      let bestTimes = 0;

      for (const [key, recipe] of usable) {
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
    for (const [key, recipe] of usable) {
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
    // Only recipes that lost on xp are listed. A whole tier of smithing ties
    // exactly (same xp per bar whatever you hammer), and listing eight
    // identical numbers would say nothing.
    steps.forEach((step) => {
      const limit = step.limit;
      const alternatives = [];
      if (limit) {
        for (const [, other] of usable) {
          if (other === step.recipe || other.anyItem) continue;
          const slot = other.in.find((i) => i.id === limit.id);
          if (!slot || slot.n !== limit.n) continue;
          const each = expectedXp(other, level);
          if (Math.abs(each - step.xpEach) < 1e-9) continue;
          // An alternative is only worth as much as its *other* ingredients
          // allow. 14,583 iron ore is 255k xp of steel bars on paper and 1.5k
          // in practice if the bank holds 168 coal — offering the paper figure
          // would be the same double-counting the per-skill split exists to
          // avoid, one level down. Measured against the original bank, since
          // that is what "if you had spent it this way instead" means.
          let times = step.times;
          let capped = false;
          for (const input of other.in) {
            if (input.id === limit.id) continue;
            const possible = Math.floor((baseStock.get(input.id) || 0) / input.n);
            if (possible < times) {
              times = possible;
              capped = true;
            }
          }
          if (times <= 0) continue;
          alternatives.push({
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
        step.limitQty = step.times * limit.n;
      }
      delete step.recipe;
      delete step.limit;
    });

    // gp: what went in, and what came out and survived. A product that a later
    // recipe ate is not counted twice — only stock still standing at the end.
    let valueIn = 0;
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
      totalXp,
      estimatedXp,
      valueIn,
      valueOut,
      consumed,
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

      const result = solveSkill(skill, list, baseStock, {
        itemsDb, pricesDb, level, capToLevel, noAlch,
      });
      if (!result.steps.length) return;

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
      results.push(result);
    });

    results.sort((a, b) => b.totalXp - a.totalXp);

    return {
      skills: results,
      capToLevel,
      knownStats: !!stats,
      meta: recipesDb.meta || {},
    };
  }

  window.BankXP = {
    solve, levelFor, xpForLevel, SKILL_ORDER, SKILL_LABELS, MAX_LEVEL,
  };
})();
