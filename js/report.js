// report.js — turns parsed bank contents + price data into the rendered report.
//
// Value tiers, strongest evidence first:
//   market    blended from the active order book (bid/ask mid) and/or recent
//             completed coin sales
//   bid       only a standing buy offer — a real floor, weaker than a trade
//   ask       only a standing sell listing — what someone *hopes* to get; treat
//             with suspicion, nothing proves anyone pays it
//   dose      potion priced per-dose from its dose family's best-sampled variant
//   charge    charged jewellery priced off its family's fully-charged variant
//   cloth     splitbark, priced from the fine cloth it takes to make
//   enchant   plain gem jewellery, capped at what its enchanted form sells for
//   stale     no recent trade, but it has sold before — old price beats a guess
//   noted     a noted (cert_) item, priced from its base item
//   alch      no market data; high alch value less the nature rune to cast it
//   vendor    worth less than the rune to alch it; low alch / shop value (cost * 0.4)
//   untradeable  can't be sold — counted as 0, not a gap
//   unknown   tradeable but genuinely no price on file (mostly rares)

(function () {
  const CATEGORY_LABELS = {
    coins: 'Coins',
    rares: 'Rares',
    runes: 'Runes',
    ammunition: 'Ammunition',
    potions: 'Potions',
    herblore: 'Herblore',
    runecrafting: 'Runecrafting',
    junk: 'Junk',
    ores_bars: 'Ores & Bars',
    logs: 'Logs',
    food: 'Food',
    gems: 'Gems',
    equipment: 'Armour',
    weapons: 'Weapons',
    jewellery: 'Jewellery',
    treasure_trails: 'Treasure Trails',
    crafting: 'Crafting',
    fletching: 'Fletching',
    bones: 'Bones',
    seeds: 'Seeds',
    tools: 'Tools',
    other: 'Other / Misc',
  };

  const TIER_LABEL = {
    market: 'Market',
    bid: 'Bid only',
    ask: 'Ask only',
    dose: 'Per-dose',
    charge: 'Charges',
    cloth: 'Fine cloth',
    enchant: 'Enchant cap',
    stale: 'Old sale',
    unfinished: 'Materials',
    junk: 'Junk',
    noted: 'Noted',
    alch: 'Alch est.',
    vendor: 'Vendor',
    untradeable: 'Untradeable',
    unknown: 'No data',
  };

  const VALUED_TIERS = new Set([
    'market', 'bid', 'ask', 'dose', 'charge', 'cloth', 'enchant', 'stale',
    'noted', 'alch', 'vendor', 'unfinished',
  ]);

  function fmtGp(n) {
    return Math.round(n).toLocaleString('en-US');
  }

  function fmtCompact(n) {
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, '') + 'B';
    if (abs >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M';
    if (abs >= 1e3) return (n / 1e3).toFixed(1).replace(/\.?0+$/, '') + 'K';
    return String(Math.round(n));
  }

  const SOURCE_LABELS = { bank: 'Bank', inventory: 'Inventory', worn: 'Worn' };

  // One colour per category so a bar is identifiable at a glance, in the same
  // spirit as the loot-share bars in preservation-sim.
  const CATEGORY_COLORS = {
    coins: 'var(--gold)',
    rares: 'var(--gold)',
    runes: 'var(--violet)',
    ammunition: 'var(--teal)',
    potions: 'var(--red)',

    herblore: 'var(--green)',
    runecrafting: 'var(--violet)',
    junk: 'var(--text-3)',
    ores_bars: 'var(--blue)',
    logs: 'var(--amber)',
    food: 'var(--red)',
    gems: 'var(--violet)',
    equipment: 'var(--teal)',
    weapons: 'var(--red)',
    jewellery: 'var(--amber)',
    treasure_trails: 'var(--gold)',
    crafting: 'var(--amber)',
    fletching: 'var(--green)',
    bones: 'var(--text-2)',
    seeds: 'var(--green)',
    tools: 'var(--text-2)',
    other: 'var(--blue)',
  };

  // Build report rows from a character's containers + the item/price databases.
  //
  // `containers` is either { bank: [...], inventory: [...], worn: [...] } or a
  // bare array (treated as bank only). Each container is [{ id, count }].
  //
  // Quantities are merged across containers — an item can occupy several bank
  // slots, and the same item can sit in the bank and the inventory at once —
  // but each row keeps a per-source breakdown so the header can show where the
  // value actually is.
  function buildRows(containers, itemsDb, pricesDb) {
    const sets = Array.isArray(containers) ? { bank: containers } : containers || {};

    const merged = new Map();  // gid -> qty
    const sources = new Map(); // gid -> { bank, inventory, worn }

    Object.keys(SOURCE_LABELS).forEach((source) => {
      (sets[source] || []).forEach((it) => {
        merged.set(it.id, (merged.get(it.id) || 0) + it.count);
        const bySource = sources.get(it.id) || {};
        bySource[source] = (bySource[source] || 0) + it.count;
        sources.set(it.id, bySource);
      });
    });

    // Fold poisoned weapons and dragon leather into their base item's row, so
    // "Rune arrow x5,000" and "Rune arrow(p) x200" read as one holding with a
    // note rather than two lines at the same price.
    const variantNotes = new Map(); // base gid -> { label: qty }
    merged.forEach((qty, gid) => {
      const item = itemsDb[String(gid)];
      const base = item && item.pricedAs;
      if (!base || Number(base) === gid) return;
      // Create the base row if the player holds only the variant — someone with
      // adamant dart(p) and no plain darts should still see one "Adamant dart"
      // line, not a separately (mis)priced poisoned entry.
      if (!merged.has(Number(base))) {
        merged.set(Number(base), 0);
        sources.set(Number(base), {});
      }
      const notes = variantNotes.get(Number(base)) || {};
      const label = item.variant || 'variant';
      notes[label] = (notes[label] || 0) + qty;
      variantNotes.set(Number(base), notes);
      merged.set(Number(base), merged.get(Number(base)) + qty);
      const baseSrc = sources.get(Number(base)) || {};
      Object.entries(sources.get(gid) || {}).forEach(([sk, sv]) => {
        baseSrc[sk] = (baseSrc[sk] || 0) + sv;
      });
      sources.set(Number(base), baseSrc);
      merged.delete(gid);
      sources.delete(gid);
    });

    const rows = [];
    merged.forEach((qty, gid) => {
      const key = String(gid);
      const item = itemsDb[key];
      const price = pricesDb[key];

      const from = sources.get(gid) || {};

      if (!item) {
        rows.push({
          id: gid, name: `Unknown item (id ${gid})`, qty, from,
          unitPrice: null, tier: 'unknown', category: 'other', rare: false,
        });
        return;
      }

      let tier, unitPrice;
      if (!item.tradeable) {
        tier = 'untradeable';
        unitPrice = 0;
      } else if (price) {
        tier = price.notedFrom ? 'noted' : price.tier;
        unitPrice = price.price;
      } else {
        tier = 'unknown';
        unitPrice = null;
      }

      rows.push({
        id: gid,
        name: item.name || item.slug,
        qty,
        from,
        variants: variantNotes.get(gid) || null,
        unitPrice,
        tier,
        category: item.rare ? 'rares' : item.category || 'other',
        rare: !!item.rare,
      });
    });
    return rows;
  }

  function rowTotal(row) {
    return VALUED_TIERS.has(row.tier) && row.unitPrice != null ? row.qty * row.unitPrice : 0;
  }

  function buildReport(rows) {
    const byCat = new Map();
    rows.forEach((row) => {
      if (!byCat.has(row.category)) byCat.set(row.category, []);
      byCat.get(row.category).push(row);
    });

    const cats = [...byCat.entries()]
      .map(([key, items]) => {
        const sorted = [...items].sort((a, b) => rowTotal(b) - rowTotal(a));
        return { key, items: sorted, subtotal: sorted.reduce((s, r) => s + rowTotal(r), 0) };
      })
      .sort((a, b) => b.subtotal - a.subtotal);

    const rareRows = rows.filter((r) => r.rare);
    const rareTotal = rareRows.reduce((s, r) => s + rowTotal(r), 0);
    const grandTotal = rows.reduce((s, r) => s + rowTotal(r), 0);

    // Per-container value. A row's value is split across the containers it
    // came from, in proportion to the quantity held in each.
    const bySource = {};
    rows.forEach((row) => {
      if (!VALUED_TIERS.has(row.tier) || row.unitPrice == null) return;
      Object.entries(row.from || {}).forEach(([source, qty]) => {
        bySource[source] = (bySource[source] || 0) + qty * row.unitPrice;
      });
    });

    return {
      cats,
      grandTotal,
      bySource,
      rareTotal,
      totalExRares: grandTotal - rareTotal,
      rareCount: rareRows.length,
      rarePriced: rareRows.filter((r) => VALUED_TIERS.has(r.tier)).length,
      rareUnpriced: rareRows.filter((r) => !VALUED_TIERS.has(r.tier)).length,
      unpriced: rows.filter((r) => r.tier === 'unknown'),
      untradeable: rows.filter((r) => r.tier === 'untradeable' || r.tier === 'junk'),
      // Value resting on asking prices nobody has agreed to pay. Worth showing
      // when it's a meaningful slice of the total — one absurd listing can move
      // a whole bank's number.
      askOnlyTotal: rows.filter((r) => r.tier === 'ask').reduce((s, r) => s + rowTotal(r), 0),
      askOnlyCount: rows.filter((r) => r.tier === 'ask').length,
      itemCount: rows.length,
    };
  }

  function renderReport(container, rows, meta) {
    const r = buildReport(rows);
    const hasRares = r.rareCount > 0;

    const metaBits = [];
    if (meta && meta.priceAsOf) metaBits.push(`prices ${meta.priceAsOf}`);
    metaBits.push(`${r.itemCount} distinct items`);
    if (r.untradeable.length) {
      metaBits.push(
        `<button type="button" class="linkish" data-toggle-untradeable>` +
        `${r.untradeable.length} untradeable / junk hidden</button>`
      );
    }
    if (r.unpriced.length) metaBits.push(`<span class="warn">${r.unpriced.length} unpriced</span>`);

    const sourceBits = Object.keys(SOURCE_LABELS)
      .filter((s) => r.bySource[s])
      .map((s) => `<span class="src"><b>${SOURCE_LABELS[s]}</b> ${fmtCompact(r.bySource[s])}</span>`);

    container.innerHTML = `
      <div class="report-header">
        <div class="totals">
          <div class="total-block">
            <div class="grand-total-label">${meta && meta.scopeLabel ? meta.scopeLabel : 'Total value'}${hasRares ? ' &mdash; excluding rares' : ''}</div>
            <div class="grand-total">${fmtGp(r.totalExRares)}<span class="gp">gp</span></div>
          </div>
          ${hasRares ? `
          <div class="total-block secondary">
            <div class="grand-total-label">Including rares</div>
            <div class="grand-total alt">${fmtGp(r.grandTotal)}<span class="gp">gp</span></div>
            <div class="total-note">${
              r.rarePriced
                ? `${r.rarePriced} of ${r.rareCount} rare${r.rareCount === 1 ? '' : 's'} priced &middot; ${fmtCompact(r.rareTotal)} gp &mdash; volatile`
                : `${r.rareCount} rare${r.rareCount === 1 ? '' : 's'} held, none currently listed &mdash; adds nothing to this total`
            }${r.rarePriced && r.rareUnpriced ? ` &middot; ${r.rareUnpriced} unpriced` : ''}</div>
          </div>` : ''}
        </div>
        <div class="report-meta">${metaBits.join(' &middot; ')}</div>
      </div>
      ${
        r.askOnlyTotal > 0 && r.askOnlyTotal / (r.grandTotal || 1) >= 0.02
          ? `<div class="caveat">${fmtCompact(r.askOnlyTotal)} gp (${((r.askOnlyTotal / r.grandTotal) * 100).toFixed(0)}% of the total)
             comes from <b>ask-only</b> items &mdash; a seller's asking price with no buyer.
             Nothing proves anyone pays it; treat those lines as an upper bound.</div>`
          : ''
      }
      <div class="report-toolbar">
        <div class="source-strip">${sourceBits.length > 1 ? sourceBits.join('') : ''}</div>
        <div class="category-controls">
          <button type="button" class="btn tiny" data-expand-all>Expand all</button>
          <button type="button" class="btn tiny" data-collapse-all>Collapse all</button>
        </div>
      </div>
      <div class="categories"></div>
    `;

    const catsEl = container.querySelector('.categories');
    const scale = r.grandTotal > 0 ? r.grandTotal : 1;

    r.cats.forEach((cat, idx) => {
      const pct = (cat.subtotal / scale) * 100;
      const catEl = document.createElement('div');
      catEl.className = 'category' + (idx === 0 ? ' open' : '') + (cat.key === 'rares' ? ' is-rare' : '');
      catEl.innerHTML = `
        <div class="category-head">
          <span class="category-caret">&#9656;</span>
          <span class="category-name">${CATEGORY_LABELS[cat.key] || cat.key}</span>
          <span class="category-count">${cat.items.length}</span>
          <span class="category-bar"><span class="category-bar-fill" style="width:${Math.max(pct, 0).toFixed(1)}%; background:${CATEGORY_COLORS[cat.key] || 'var(--accent)'}"></span></span>
          <span class="category-pct">${pct.toFixed(1)}%</span>
          <span class="category-total">${fmtGp(cat.subtotal)} gp</span>
        </div>
        <div class="category-items"></div>
      `;
      catEl.querySelector('.category-head').addEventListener('click', () => catEl.classList.toggle('open'));

      const itemsEl = catEl.querySelector('.category-items');
      cat.items.forEach((item) => {
        const hidden = item.tier === 'untradeable' || item.tier === 'junk';
        const valued = VALUED_TIERS.has(item.tier) && item.unitPrice != null;
        // Flag anything held outside the bank. When a holding is split across
        // containers the tag carries the outside count, so a mostly-banked
        // stack doesn't read as if it were all in the inventory.
        const from = item.from || {};
        const outside = Object.keys(from).filter((s) => s !== 'bank');
        const splitAcross = outside.length && from.bank;
        const srcTag = outside.length
          ? ` <span class="src-tag" title="${Object.keys(SOURCE_LABELS)
              .filter((s) => from[s])
              .map((s) => `${SOURCE_LABELS[s]}: ${from[s].toLocaleString('en-US')}`)
              .join(', ')}">${outside
              .map((s) =>
                splitAcross
                  ? `+${from[s].toLocaleString('en-US')} ${SOURCE_LABELS[s].toLowerCase()}`
                  : SOURCE_LABELS[s].toLowerCase()
              )
              .join(', ')}</span>`
          : '';
        const row = document.createElement('div');
        row.className = 'item-row' + (hidden ? ' is-hidden-row' : '');
        row.innerHTML = `
          <span class="tier-badge tier-${item.tier}">${TIER_LABEL[item.tier] || item.tier}</span>
          <span class="item-name">${item.name}${
            item.variants
              ? ' <span class="variant-note">' +
                Object.entries(item.variants)
                  .map(([label, n]) => `+${n.toLocaleString('en-US')} ${label}`)
                  .join(', ') + '</span>'
              : ''
          }${srcTag}</span>
          <span class="item-qty">&times;${item.qty.toLocaleString('en-US')}</span>
          <span class="item-unit">${valued ? fmtGp(item.unitPrice) + ' ea' : '&mdash;'}</span>
          <span class="item-total">${valued ? fmtGp(rowTotal(item)) + ' gp' : '&mdash;'}</span>
        `;
        itemsEl.appendChild(row);
      });
      catsEl.appendChild(catEl);
    });

    if (r.unpriced.length) {
      const panel = document.createElement('div');
      panel.className = 'unpriced-panel';
      panel.innerHTML = `
        <h3>${r.unpriced.length} item${r.unpriced.length === 1 ? '' : 's'} with no price data</h3>
        <p>Not counted in the totals. These are tradeable but haven't traded recently enough
           for a price, and have no reliable fallback &mdash; rares in particular are deliberately
           never alch-estimated, since their value is collector-driven.</p>
        <ul>${r.unpriced.map((it) => `<li>${it.name} &times;${it.qty.toLocaleString('en-US')}</li>`).join('')}</ul>
      `;
      container.appendChild(panel);
    }

    const setAllOpen = (open) =>
      container.querySelectorAll('.category').forEach((c) => c.classList.toggle('open', open));
    const expandBtn = container.querySelector('[data-expand-all]');
    const collapseBtn = container.querySelector('[data-collapse-all]');
    if (expandBtn) expandBtn.addEventListener('click', () => setAllOpen(true));
    if (collapseBtn) collapseBtn.addEventListener('click', () => setAllOpen(false));

    const toggle = container.querySelector('[data-toggle-untradeable]');
    if (toggle) {
      toggle.addEventListener('click', () => {
        const shown = container.classList.toggle('show-untradeable');
        toggle.textContent = shown
          ? `${r.untradeable.length} untradeable / junk shown`
          : `${r.untradeable.length} untradeable / junk hidden`;
        // Reveal the categories holding them, so the click visibly does something.
        if (shown) {
          container.querySelectorAll('.item-row.is-hidden-row').forEach((row) => {
            const cat = row.closest('.category');
            if (cat) cat.classList.add('open');
          });
        }
      });
    }

    container.classList.add('visible');
    return r;
  }

  window.BankReport = { renderReport, buildReport, buildRows, CATEGORY_LABELS };
})();
