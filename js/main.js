// main.js — wires the dropzone to the parser, price data, and the report.
// The .sav file is read with FileReader and parsed in-page; it is never
// uploaded anywhere.
(function () {
  let itemsDb = null;
  let pricesDb = null;
  let recipesDb = null;
  let dataPromise = null;

  function loadJson(path) {
    return fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    });
  }

  function loadData() {
    if (!dataPromise) {
      dataPromise = Promise.all([
        loadJson('data/items.json'),
        loadJson('data/prices.json'),
        loadJson('data/recipes.json'),
      ]).then(([items, prices, recipes]) => {
        itemsDb = items;
        pricesDb = prices;
        recipesDb = recipes;
      });
    }
    return dataPromise;
  }

  function priceAsOf() {
    for (const key in pricesDb) {
      if (pricesDb[key] && pricesDb[key].asOf) return pricesDb[key].asOf.slice(0, 10);
    }
    return null;
  }

  // Audit mode — a synthetic "bank" holding one of every item in the catalog,
  // built client-side so it can never drift from data/items.json.
  //
  // This is the regression harness for pricing and categorisation: every item
  // renders through the real report path, so a mispriced or miscategorised item
  // is visible rather than waiting for someone to happen to hold one. Sorting
  // is by row value, and at one-of-each that IS the unit price — so the top of
  // each category is exactly where a bad price shows up first.
  //
  //   ?audit        every tradeable item
  //   ?audit=all    plus untradeables, so quest junk is checked too
  function auditBank(mode) {
    const all = mode === 'all';
    return Object.keys(itemsDb)
      .filter((gid) => all || itemsDb[gid].tradeable)
      .map((gid) => ({ id: Number(gid), count: 1 }));
  }

  function init() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('sav-input');
    const sampleBtn = document.getElementById('sample-btn');
    const reportEl = document.getElementById('report');
    const xpReportEl = document.getElementById('xp-report');
    const tabsEl = document.getElementById('tabs');
    const statusEl = document.getElementById('status');

    // The last parse, kept in memory so the XP tab can re-solve when the level
    // filter is toggled without asking for the file again. It never leaves the
    // page, same as everything else here.
    let current = null;         // { containers, stats }
    let capToLevel = false;
    // Pinned recipes, per skill: { smithing: { 453: 'smelt_mithril_bar' } }.
    // The solve's default tie-break is a stated choice rather than the only
    // sane one, so the reader gets to overrule it per contested item.
    let choices = {};

    function setStatus(msg, kind) {
      if (!statusEl) return;
      statusEl.textContent = msg || '';
      statusEl.className = 'status' + (kind ? ' ' + kind : '') + (msg ? ' visible' : '');
    }

    // Roving tabindex: only the selected tab is in the Tab order, and the
    // arrow keys move between them — the behaviour a role="tablist" promises.
    function showTab(name, focus) {
      if (!tabsEl) return;
      tabsEl.querySelectorAll('[data-tab]').forEach((btn) => {
        const on = btn.dataset.tab === name;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        btn.tabIndex = on ? 0 : -1;
        if (on && focus) btn.focus();
      });
      if (reportEl) reportEl.hidden = name !== 'value';
      if (xpReportEl) xpReportEl.hidden = name !== 'xp';
    }

    if (tabsEl) {
      const tabButtons = [...tabsEl.querySelectorAll('[data-tab]')];
      tabButtons.forEach((btn, i) => {
        btn.addEventListener('click', () => showTab(btn.dataset.tab));
        btn.addEventListener('keydown', (e) => {
          const step = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: tabButtons.length - 1 - i }[e.key];
          if (step === undefined) return;
          e.preventDefault();
          const next = (i + step + tabButtons.length) % tabButtons.length;
          showTab(tabButtons[next].dataset.tab, true);
        });
      });
      showTab('value');
    }

    // Renders the XP tab from `current`, and re-binds the level filter — the
    // checkbox lives inside the rendered markup, so it is fresh each time.
    function renderXp() {
      if (!xpReportEl || !current) return;
      // Which skill panels are open survives the re-render; otherwise picking
      // a recipe would collapse everything the reader had opened to find it.
      const openSkills = new Set(
        [...xpReportEl.querySelectorAll('.xp-skill.open')].map((el) => el.dataset.skill)
      );
      const solved = window.BankXP.solve(
        current.containers, itemsDb, pricesDb, recipesDb, current.stats,
        { capToLevel, choices }
      );
      window.BankXPReport.renderXpReport(xpReportEl, solved, itemsDb, {
        capToLevel,
        openSkills: openSkills.size ? openSkills : null,
        onPick,
      });
      const box = xpReportEl.querySelector('#xp-cap-level');
      if (box) {
        box.addEventListener('change', () => {
          capToLevel = box.checked;
          renderXp();
        });
      }
      return solved;
    }

    // Pin one recipe to one contested item, or clear the whole skill when the
    // item is null (the "back to best rate" button).
    function onPick(skill, itemId, key) {
      if (itemId === null) delete choices[skill];
      else {
        const forSkill = { ...(choices[skill] || {}) };
        if (key) forSkill[itemId] = key;
        else delete forSkill[itemId];
        if (Object.keys(forSkill).length) choices[skill] = forSkill;
        else delete choices[skill];
      }
      renderXp();
    }

    // One entry point for every source of a bank: a dropped save, the sample,
    // or the audit harness. Both tabs are always built, so switching between
    // them is instant and neither view can go stale against the other.
    function render(containers, stats, meta) {
      current = { containers, stats: stats || null };
      choices = {}; // a different bank has different forks
      const rows = window.BankReport.buildRows(containers, itemsDb, pricesDb);
      const r = window.BankReport.renderReport(reportEl, rows, meta || {});
      renderXp();
      if (tabsEl) tabsEl.classList.add('visible');
      return r;
    }

    if (dropzone && fileInput) {
      dropzone.addEventListener('click', () => fileInput.click());
      ['dragenter', 'dragover'].forEach((evt) =>
        dropzone.addEventListener(evt, (e) => {
          e.preventDefault();
          dropzone.classList.add('drag-over');
        })
      );
      ['dragleave', 'drop'].forEach((evt) =>
        dropzone.addEventListener(evt, (e) => {
          e.preventDefault();
          dropzone.classList.remove('drag-over');
        })
      );
      dropzone.addEventListener('drop', (e) => {
        const file = e.dataTransfer.files[0];
        if (file) handleFile(file);
      });
      fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFile(file);
        e.target.value = ''; // allow re-picking the same file
      });
    }

    if (sampleBtn && reportEl) {
      sampleBtn.addEventListener('click', () => {
        if (!window.SAMPLE_BANK) return;
        setStatus('Showing a sample bank.', 'info');
        loadData()
          .then(() => {
            render(window.SAMPLE_BANK, window.SAMPLE_STATS || null,
                   { priceAsOf: priceAsOf() });
            reportEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
          })
          .catch((err) => setStatus(`Could not load price data: ${err.message}`, 'error'));
      });
    }

    const auditMode = new URLSearchParams(location.search).get('audit');
    if (auditMode !== null && reportEl) {
      setStatus('Building the audit bank…', 'info');
      loadData()
        .then(() => {
          const bank = auditBank(auditMode);
          const r = render({ bank }, null, {
            priceAsOf: priceAsOf(),
            scopeLabel: 'Audit — one of every item',
          });
          // Drift check between the two builders. recipes.json is keyed by
          // the same numeric ids as items.json, but they are generated by
          // different scripts against different parts of Content — if a
          // rebuild ever drops an item the recipes still name, the XP tab
          // would quietly lose those recipes. Say so instead.
          const orphans = new Set();
          Object.values(recipesDb.recipes).forEach((rec) => {
            [...rec.in, ...rec.out].forEach((slot) => {
              if (!itemsDb[String(slot.id)]) orphans.add(slot.id);
            });
          });
          setStatus(
            `Audit bank: ${bank.length} catalog items, ${r.itemCount} rows ` +
            `(×1 each, so every row total is its unit price). ` +
            `${Object.keys(recipesDb.recipes).length} recipes` +
            (orphans.size
              ? ` — ${orphans.size} reference items missing from the catalog.`
              : `, every ingredient resolves.`),
            orphans.size ? 'error' : 'ok'
          );
        })
        .catch((err) => setStatus(`Could not load price data: ${err.message}`, 'error'));
    }

    function handleFile(file) {
      setStatus(`Reading ${file.name}…`, 'info');
      const reader = new FileReader();

      reader.onerror = () => setStatus('Could not read that file.', 'error');
      reader.onload = () => {
        let parsed;
        try {
          parsed = window.SavParser.parseSave(reader.result);
        } catch (err) {
          setStatus(err.message, 'error');
          reportEl.classList.remove('visible');
          if (tabsEl) tabsEl.classList.remove('visible');
          return;
        }

        const heldCount =
          (parsed.bank ? parsed.bank.items.length : 0) +
          (parsed.inventory ? parsed.inventory.items.length : 0) +
          (parsed.worn ? parsed.worn.items.length : 0);
        if (!heldCount) {
          setStatus('That save parsed fine, but the character holds nothing.', 'error');
          reportEl.classList.remove('visible');
          if (tabsEl) tabsEl.classList.remove('visible');
          return;
        }

        const containers = {
          bank: parsed.bank ? parsed.bank.items : [],
          inventory: parsed.inventory ? parsed.inventory.items : [],
          worn: parsed.worn ? parsed.worn.items : [],
        };

        loadData()
          .then(() => {
            const r = render(containers, parsed.stats, {
              priceAsOf: priceAsOf(),
              scopeLabel: 'Total value',
            });
            const parts = Object.entries(containers)
              .filter(([, list]) => list.length)
              .map(([name, list]) => `${list.length} ${name}`);
            setStatus(`Parsed ${file.name} — ${parts.join(', ')}; ${r.itemCount} distinct items.`, 'ok');
            reportEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
          })
          .catch((err) => setStatus(`Could not load price data: ${err.message}`, 'error'));
      };

      reader.readAsArrayBuffer(file);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
