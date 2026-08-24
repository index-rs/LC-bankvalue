// xpReport.js — renders the banked-XP view: what this bank is worth in each
// skill, and where that lands you.
//
// Deliberately has no grand total. One bank cannot be spent twice, so every
// skill is shown as its own answer to "if I spent all of this on you, what
// happens", with the items two skills both want called out by name. See xp.js
// for the solve.

(function () {
  function fmt(n) {
    return Math.round(n).toLocaleString('en-US');
  }

  function fmtCompact(n) {
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, '') + 'B';
    if (abs >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M';
    if (abs >= 1e3) return (n / 1e3).toFixed(1).replace(/\.?0+$/, '') + 'K';
    return String(Math.round(n));
  }

  function fmtXpEach(n) {
    return Number.isInteger(n) ? String(n) : n.toFixed(n < 10 ? 2 : 1);
  }

  const SKILL_COLORS = {
    fletching: 'var(--green)',
    crafting: 'var(--amber)',
    smithing: 'var(--blue)',
    herblore: 'var(--green)',
    firemaking: 'var(--red)',
    runecraft: 'var(--violet)',
    prayer: 'var(--text-2)',
    magic: 'var(--violet)',
  };

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (ch) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }

  function levelLine(skill) {
    if (!skill.knownStats) {
      return `<span class="xp-level-unknown">from level 1 &mdash; no stats in this save</span>`;
    }
    if (skill.endLevel > skill.baseLevel) {
      return `<span class="xp-level">${skill.baseLevel} <span class="arrow">&rarr;</span> ` +
             `<b>${skill.endLevel}</b></span>`;
    }
    if (skill.baseLevel >= window.BankXP.MAX_LEVEL) {
      return `<span class="xp-level">99 <span class="xp-level-note">maxed</span></span>`;
    }
    const short = skill.toNextLevel - skill.totalXp;
    return `<span class="xp-level">${skill.baseLevel} <span class="xp-level-note">` +
           `${fmtCompact(short)} short of ${skill.baseLevel + 1}</span></span>`;
  }

  function stepRow(step, itemsDb) {
    const badges = [];
    if (step.aboveLevel) {
      badges.push(`<span class="xp-badge above" title="You are not this level yet — ` +
                  `it unlocks partway through the grind">lvl ${step.level}</span>`);
    }
    if (step.chance) {
      badges.push(`<span class="xp-badge chance" title="${esc(step.note || '')}">estimate</span>`);
    }
    if (step.fee) {
      badges.push(`<span class="xp-badge prep" title="Costs ${fmt(step.fee)} gp each ` +
                  `and pays no xp, but the recipes downstream need it done">prep</span>`);
    }
    if (step.quest) {
      badges.push(`<span class="xp-badge quest" title="Needs ${esc(step.quest)}` +
                  `">quest</span>`);
    }
    const eaten = step.eaten && step.eaten.length
      // Listed in the order they are actually eaten, because that order is now
      // a deliberate priority rather than a tiebreak — seeing the bows go
      // first is the point.
      ? `<div class="xp-step-note">Consumes ${fmt(step.eaten.reduce((s, e) => s + e.n, 0))} ` +
        `items, in priority order &mdash; ` +
        step.eaten.slice(0, 4).map((e) => {
          const it = itemsDb[String(e.id)];
          return `${esc(it ? it.name : e.id)} &times;${fmt(e.n)}`;
        }).join(', ') +
        (step.eaten.length > 4 ? `, +${step.eaten.length - 4} more` : '') +
        (step.coins ? ` &mdash; pays ${fmtCompact(step.coins)} gp in coins` : '') +
        `</div>`
      : '';
    const alts = step.alternatives && step.alternatives.length
      ? `<div class="xp-step-note xp-alts">Same ${fmt(step.limitQty)} ` +
        `${esc((step.limitName || 'stock').toLowerCase())} instead &mdash; ` +
        step.alternatives.map((a) =>
          `<span class="xp-alt${a.aboveLevel ? ' is-above' : ''}"` +
          `${a.aboveLevel ? ` title="needs level ${a.level}"` : ''}` +
          `${a.capped ? ' title="limited by its other ingredients in this bank"' : ''}>` +
          `${esc(a.label)}${a.capped ? ` &times;${fmt(a.times)}` : ''} ` +
          `<b>${fmtCompact(a.xp)}</b>` +
          `${a.aboveLevel ? ` <i>lvl ${a.level}</i>` : ''}</span>`
        ).join('') +
        (step.altMore ? `<span class="xp-alt-more">+${step.altMore} more</span>` : '') +
        `</div>`
      : '';
    return `
      <div class="xp-step${step.aboveLevel ? ' is-above' : ''}">
        <span class="xp-step-label" title="${esc(step.src)}">${esc(step.label)}${badges.join('')}</span>
        <span class="xp-step-times">&times;${fmt(step.times)}</span>
        <span class="xp-step-each">${
          step.fee && !step.xp ? `${fmt(step.fee)} gp` : `${fmtXpEach(step.xpEach)} xp`
        }</span>
        <span class="xp-step-total">${
          step.fee && !step.xp ? `&mdash;${
            step.fee * step.times
              ? ` <span class="xp-fee">-${fmtCompact(step.fee * step.times)} gp</span>`
              : ''}` : fmt(step.xp)
        }</span>
        ${eaten}${alts}
      </div>`;
  }

  function renderXpReport(container, result, itemsDb, opts) {
    const skills = result.skills;
    const meta = result.meta || {};

    const top = skills.length ? skills[0].totalXp || 1 : 1;

    container.innerHTML = `
      <div class="xp-header">
        <div>
          <div class="grand-total-label">Banked XP</div>
          <p class="xp-lede">
            What the bank is worth in each skill, if you spent all of it on that one
            skill. <b>These do not add up</b> &mdash; yew logs are Fletching xp
            <i>or</i> Firemaking xp, never both, so a combined total would be a lie
            by double-counting.
          </p>
        </div>
        <div class="xp-controls">
          <label class="xp-toggle">
            <input type="checkbox" id="xp-cap-level" ${opts && opts.capToLevel ? 'checked' : ''}>
            <span>Only recipes I can use now</span>
          </label>
        </div>
      </div>
      <div class="xp-meta">
        ${meta.count || 0} recipes from Content build ${esc(meta.contentBuild || '?')}
        &middot; ${skills.length} skill${skills.length === 1 ? '' : 's'} with something to make
        ${result.knownStats ? '' : '&middot; <span class="warn">no stats in this save &mdash; levels assumed 1</span>'}
      </div>
      ${skills.length ? '' : `
      <div class="xp-empty">
        <h3>Nothing here feeds a skill this tool covers${opts && opts.capToLevel ? ' at your current levels' : ''}.</h3>
        <p>Banked XP reads ${meta.count || 0} recipes out of Lost City's own content,
           across ${Object.keys(meta.bySkill || {}).length} skills.${
             opts && opts.capToLevel
               ? ' Untick the filter above to include recipes you would unlock on the way.'
               : ' A bank of finished gear and rares has nothing to process.'}</p>
      </div>`}
      <div class="xp-skills"></div>
    `;

    const list = container.querySelector('.xp-skills');

    skills.forEach((skill, idx) => {
      const pct = Math.max(1, (skill.totalXp / top) * 100);
      const delta = skill.valueOut - skill.valueIn;
      const el = document.createElement('div');
      el.className = 'xp-skill' + (idx === 0 ? ' open' : '');
      el.innerHTML = `
        <div class="xp-skill-head">
          <span class="category-caret">&#9656;</span>
          <span class="xp-skill-name">${esc(skill.label)}</span>
          ${levelLine(skill)}
          <span class="category-bar"><span class="category-bar-fill"
            style="width:${pct.toFixed(1)}%; background:${SKILL_COLORS[skill.skill] || 'var(--accent)'}"></span></span>
          <span class="xp-skill-total">${fmt(skill.totalXp)}<span class="unit">xp</span></span>
        </div>
        <div class="xp-skill-body">
          <div class="xp-gp">
            <span><b>${fmtCompact(skill.valueIn)}</b> gp of stock in</span>
            <span class="arrow">&rarr;</span>
            <span><b>${fmtCompact(skill.valueOut)}</b> gp out</span>
            <span class="xp-gp-delta ${delta >= 0 ? 'up' : 'down'}">
              ${delta >= 0 ? 'the xp pays you' : 'the xp costs you'}
              ${fmtCompact(Math.abs(delta))} gp${
                skill.totalXp ? ` &middot; ${(Math.abs(delta) / skill.totalXp).toFixed(2)} gp per xp` : ''
              }
            </span>
          </div>
          ${skill.truncated ? `
          <div class="xp-caveat">
            The chain walk hit its pass limit with work still to do, so this total is a
            floor, not the answer. Worth reporting as a bug.
          </div>` : ''}
          ${skill.estimatedXp ? `
          <div class="xp-caveat">
            ${fmt(skill.estimatedXp)} xp of this (${((skill.estimatedXp / skill.totalXp) * 100).toFixed(0)}%)
            comes from recipes that can fail &mdash; an expectation, not a count.
          </div>` : ''}
          <div class="xp-steps"></div>
          ${skill.contention.length ? `
          <div class="xp-contested">
            <b>Also wanted elsewhere.</b>
            ${skill.contention.slice(0, 4).map((c) =>
              `${esc(c.name)} &times;${fmt(c.qty)} <span class="rival">${esc(c.skills.join(', '))}</span>`
            ).join(' &middot; ')}
            ${skill.contention.length > 4 ? ` &middot; +${skill.contention.length - 4} more` : ''}
          </div>` : ''}
          ${skill.missingTools.length ? `
          <div class="xp-tools">
            You hold no ${skill.missingTools.map((t) => esc(t.name.toLowerCase())).join(', ')}.
            Tools aren't consumed, so this is a shopping note, not a deduction.
          </div>` : ''}
        </div>
      `;
      el.querySelector('.xp-skill-head')
        .addEventListener('click', () => el.classList.toggle('open'));

      const stepsEl = el.querySelector('.xp-steps');
      const shown = skill.steps.slice(0, 8);
      stepsEl.innerHTML = shown.map((s) => stepRow(s, itemsDb)).join('');
      if (skill.steps.length > shown.length) {
        const more = document.createElement('button');
        more.type = 'button';
        more.className = 'btn tiny xp-more';
        more.textContent = `Show ${skill.steps.length - shown.length} more steps`;
        more.addEventListener('click', () => {
          stepsEl.innerHTML = skill.steps.map((s) => stepRow(s, itemsDb)).join('');
          more.remove();
        });
        el.querySelector('.xp-skill-body').insertBefore(more, stepsEl.nextSibling);
      }
      list.appendChild(el);
    });

    const notCovered = meta.notCovered || {};
    const names = skills.length ? Object.keys(notCovered) : [];
    if (names.length) {
      const panel = document.createElement('div');
      panel.className = 'unpriced-panel';
      panel.innerHTML = `
        <h3>${names.length} skills this does not answer for</h3>
        <p>A missing recipe just makes a number smaller and nobody notices, so the
           gaps are listed rather than left to be inferred.</p>
        <ul>${names.map((n) =>
          `<li><b>${esc(n[0].toUpperCase() + n.slice(1))}</b> &mdash; ${esc(notCovered[n])}</li>`
        ).join('')}</ul>
        ${Object.keys(meta.unreleased || {}).length ? `
        <h3>and ${Object.keys(meta.unreleased).length} recipe${
          Object.keys(meta.unreleased).length === 1 ? '' : 's'} Content describes but the
          2004 game doesn't have</h3>
        <p>A row in a config file is not the same claim as a thing you can do. These are
           dropped on purpose — left in, they'd be the best rate in their skill and would
           quietly dominate the answer.</p>
        <ul>${Object.entries(meta.unreleased).map(([row, why]) =>
          `<li><b>${esc(row)}</b> &mdash; ${esc(why)}</li>`
        ).join('')}</ul>` : ''}
        ${(meta.knownGaps || []).length ? `
        <h3>and ${meta.knownGaps.length} gaps inside the skills it does cover</h3>
        <p>Riskier than a missing skill, because a skill that half works still looks
           like an answer.</p>
        <ul>${meta.knownGaps.map((g) => `<li>${esc(g)}</li>`).join('')}</ul>` : ''}
      `;
      container.appendChild(panel);
    }

    container.classList.add('visible');
    return result;
  }

  window.BankXPReport = { renderXpReport };
})();
