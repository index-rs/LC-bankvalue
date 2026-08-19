// main.js — wires the dropzone to the parser, price data, and the report.
// The .sav file is read with FileReader and parsed in-page; it is never
// uploaded anywhere.
(function () {
  let itemsDb = null;
  let pricesDb = null;
  let dataPromise = null;

  function loadData() {
    if (!dataPromise) {
      dataPromise = Promise.all([
        fetch('data/items.json').then((r) => {
          if (!r.ok) throw new Error(`items.json: HTTP ${r.status}`);
          return r.json();
        }),
        fetch('data/prices.json').then((r) => {
          if (!r.ok) throw new Error(`prices.json: HTTP ${r.status}`);
          return r.json();
        }),
      ]).then(([items, prices]) => {
        itemsDb = items;
        pricesDb = prices;
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
    const statusEl = document.getElementById('status');

    function setStatus(msg, kind) {
      if (!statusEl) return;
      statusEl.textContent = msg || '';
      statusEl.className = 'status' + (kind ? ' ' + kind : '') + (msg ? ' visible' : '');
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
            const rows = window.BankReport.buildRows(window.SAMPLE_BANK, itemsDb, pricesDb);
            window.BankReport.renderReport(reportEl, rows, { priceAsOf: priceAsOf() });
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
          const rows = window.BankReport.buildRows({ bank }, itemsDb, pricesDb);
          const r = window.BankReport.renderReport(reportEl, rows, {
            priceAsOf: priceAsOf(),
            scopeLabel: 'Audit — one of every item',
          });
          setStatus(
            `Audit bank: ${bank.length} catalog items, ${r.itemCount} rows ` +
            `(×1 each, so every row total is its unit price).`,
            'ok'
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
          return;
        }

        const heldCount =
          (parsed.bank ? parsed.bank.items.length : 0) +
          (parsed.inventory ? parsed.inventory.items.length : 0) +
          (parsed.worn ? parsed.worn.items.length : 0);
        if (!heldCount) {
          setStatus('That save parsed fine, but the character holds nothing.', 'error');
          reportEl.classList.remove('visible');
          return;
        }

        const containers = {
          bank: parsed.bank ? parsed.bank.items : [],
          inventory: parsed.inventory ? parsed.inventory.items : [],
          worn: parsed.worn ? parsed.worn.items : [],
        };

        loadData()
          .then(() => {
            const rows = window.BankReport.buildRows(containers, itemsDb, pricesDb);
            const r = window.BankReport.renderReport(reportEl, rows, {
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
