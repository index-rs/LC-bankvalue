// xpReport.js — renders the banked-XP view: what this bank is worth in each
// skill, and where that lands you.
//
// Deliberately has no grand total. One bank cannot be spent twice, so every
// skill is shown as its own answer to "if I spent all of this on you, what
// happens", with the items two skills both want called out by name. See xp.js
// for the solve.
//
// The tie-break is a control, not a verdict. Every item two recipes fight over
// gets a "make" picker, and the road-not-taken chips under each step are
// buttons: clicking one pins that recipe to the item it was measured against
// and re-runs the walk. The picker says what the default did and what
// overruling it costs, so the choice is informed rather than a shrug.

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
    if (!skill.totalXp) {
      return `<span class="xp-level">${skill.baseLevel} ` +
             `<span class="xp-level-note">nothing usable at this level</span></span>`;
    }
    if (skill.levelCap > skill.baseLevel) {
      // The plan reaches for recipes you have not unlocked yet without quite
      // getting you a level: worth saying, because those steps are badged.
      return `<span class="xp-level">${skill.baseLevel} <span class="xp-level-note">` +
             `using recipes up to ${skill.levelCap}</span></span>`;
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
    // A roll with an answer is not an estimate. Iron smelting carries its 50%
    // because Content does, but the plan wears a ring of forging, so the badge
    // would be claiming an uncertainty the number does not have — the kit note
    // below the step says what it assumes instead.
    if (step.chance && !step.chance.mitigatedBy) {
      badges.push(`<span class="xp-badge chance" title="${esc(step.note || '')}">estimate</span>`);
    }
    // A step that pays nothing is a prerequisite, not a choice — badged
    // whether or not it costs coins. Tanning charges 3 gp a hide; filling a
    // bucket at a sand pit is free, and both are things you have to do before
    // the recipes downstream can happen.
    if (!step.xp) {
      badges.push(`<span class="xp-badge prep" title="${
        step.fee ? `Costs ${fmt(step.fee)} gp each and pays no xp`
                 : 'Pays no xp and costs nothing'}, but the recipes ` +
        `downstream need it done">prep</span>`);
    }
    if (step.quest) {
      badges.push(`<span class="xp-badge quest" title="Needs ${esc(step.quest)}` +
                  `">quest</span>`);
    }
    // What alchemy eats, in the order it eats them — a deliberate priority
    // rather than a tiebreak, so seeing the bows go first is the point.
    //
    // Each one is a button, because "there is nothing here worth alching
    // except the magic longbows" is the normal case and the plan should be
    // able to say so. Dropping an item takes it out of the targets and the
    // cast count follows, so the xp and gp are the ones you would really get.
    const EATEN_SHOWN = 10;
    const eatenList = step.eaten || [];
    const eaten = eatenList.length
      ? `<div class="xp-step-note xp-eats">Consumes ${
          fmt(eatenList.reduce((s2, e) => s2 + e.n, 0))} items, best first &mdash; ` +
        eatenList.slice(0, EATEN_SHOWN).map((e) => {
          const it = itemsDb[String(e.id)];
          return `<button type="button" class="xp-eat" data-drop-item="${e.id}" ` +
            `title="Leave these out of the plan">${esc(it ? it.name : e.id)} ` +
            `&times;${fmt(e.n)} <span class="x">&times;</span></button>`;
        }).join('') +
        (eatenList.length > EATEN_SHOWN
          ? `<span class="xp-alt-more">+${eatenList.length - EATEN_SHOWN} more</span>` : '') +
        (step.coins ? ` <span class="xp-eat-coins">pays ${fmtCompact(step.coins)} gp in coins</span>` : '') +
        `</div>`
      : '';
    const buying = step.buying && step.buying.length
      // A shop ingredient is not a wall and not free either. Say the number,
      // and say it is a trip rather than a deduction from what you hold.
      ? `<div class="xp-step-note xp-buy">Buy ` +
        step.buying.map((b) => {
          const it = itemsDb[String(b.id)];
          return `${esc(it ? it.name.toLowerCase() : b.id)} &times;${fmt(b.n)} ` +
                 `at ${fmt(b.each)} gp`;
        }).join(', ') +
        ` &mdash; <b>${fmtCompact(step.buying.reduce((s2, b) => s2 + b.n * b.each, 0))} gp</b> ` +
        `you do not have to bank, but do have to spend</div>`
      : '';
    const kit = step.mitigation
      ? `<div class="xp-step-note xp-kit">Assumes a ` +
        `${esc((itemsDb[String(step.mitigation.id)] || {}).name || 'ring').toLowerCase()}, ` +
        `which skips the failure roll outright rather than reducing it. ` +
        `They melt after ${fmt(step.mitigation.uses)} &mdash; ` +
        `<b>${fmt(step.mitigation.count)}</b> of them for this many.</div>`
      : '';
    const alts = step.alternatives && step.alternatives.length
      ? `<div class="xp-step-note xp-alts">Same ${fmt(step.limitQty)} ` +
        `${esc((step.limitName || 'stock').toLowerCase())} instead &mdash; ` +
        step.alternatives.map((a) => {
          const why = a.aboveLevel ? `needs level ${a.level}`
            : a.capped ? 'limited by its other ingredients in this bank'
            : `use this instead — ${fmtXpEach(a.xpEach)} xp each`;
          return `<button type="button" class="xp-alt${a.aboveLevel ? ' is-above' : ''}" ` +
            `data-pin-item="${a.on}" data-pin-key="${esc(a.key)}" title="${esc(why)}">` +
            `${esc(a.label)}${a.capped ? ` &times;${fmt(a.times)}` : ''} ` +
            `<b>${fmtCompact(a.xp)}</b>` +
            `${a.aboveLevel ? ` <i>lvl ${a.level}</i>` : ''}</button>`;
        }).join('') +
        (step.altMore ? `<span class="xp-alt-more">+${step.altMore} more</span>` : '') +
        `</div>`
      : '';
    return `
      <div class="xp-step${step.aboveLevel ? ' is-above' : ''}">
        <span class="xp-step-label" title="${esc(step.src)}">${esc(step.label)}${badges.join('')}</span>
        <span class="xp-step-times">&times;${fmt(step.times)}</span>
        <span class="xp-step-each">${
          !step.xp ? (step.fee ? `${fmt(step.fee)} gp` : 'free')
                   : `${fmtXpEach(step.xpEach)} xp`
        }</span>
        <span class="xp-step-total">${
          !step.xp ? `&mdash;${
            step.fee * step.times
              ? ` <span class="xp-fee">-${fmtCompact(step.fee * step.times)} gp</span>`
              : ''}` : fmt(step.xp)
        }</span>
        ${eaten}${buying}${kit}${alts}
      </div>`;
  }

  // The "make" pickers: one per item that two or more recipes in this skill
  // compete for. Which forks exist is decided by the solve (see choiceGroups
  // in xp.js) and never by what has been picked, so the control that changed
  // the plan is still there to change it back.
  //
  // Shown by how much xp rides on the decision, which puts coal above the odd
  // gem nobody has three of. Anything already pinned is shown whatever its
  // rank, or you could pin a fork out of its own control.
  const CHOICES_SHOWN = 5;

  // The value a select carries when the reader wants the item left alone. It
  // cannot collide with a recipe key: those are all slugs built from a handler
  // name and an item, and none of them is bracketed like this.
  const DROP = '--leave-it--';

  function choiceBlock(skill, itemsDb) {
    const groups = skill.choiceGroups || [];
    const dropped = new Set(skill.excluded || []);
    if (!groups.length && !dropped.size) return '';
    // Only pins the solve could actually honour count as pins. Ticking the
    // level filter can put a pinned recipe out of reach, and the control has to
    // agree with the plan about whether it is in force.
    const chosen = {};
    groups.forEach((g) => {
      const pick = (skill.choices || {})[g.id];
      if (pick && g.options.some((o) => o.key === pick)) chosen[g.id] = pick;
    });
    // A dropped item always keeps its control, wherever it ranks — otherwise
    // the only way back from "don't use these" would be the reset button.
    const shown = groups.filter((g, i) =>
      i < CHOICES_SHOWN || chosen[g.id] || dropped.has(g.id));
    const pins = Object.keys(chosen).length + dropped.size;
    const delta = skill.totalXp - skill.autoXp;

    const pickers = shown.map((g) => {
      const off = dropped.has(g.id);
      const pick = off ? DROP : (chosen[g.id] || '');
      const auto = g.options[0];
      const unit = g.name.toLowerCase();
      const autoLabel = g.autoKeys.length
        ? g.options.filter((o) => g.autoKeys.indexOf(o.key) !== -1)
            .map((o) => o.label).join(' + ') || auto.label
        : auto.label;
      return `
        <label class="xp-choice${pick ? ' is-pinned' : ''}${off ? ' is-off' : ''}">
          <span class="xp-choice-item">${esc(g.name)} <i>&times;${fmt(g.qty)}</i></span>
          <select data-skill="${esc(skill.skill)}" data-item="${g.id}">
            <option value=""${pick ? '' : ' selected'}>${
              g.options.length > 1 ? 'Best rate &mdash; ' : 'Use &mdash; '
            }${esc(autoLabel)}</option>
            ${g.options.map((o) =>
              // Rated per unit of the contested item, not per action — the
              // whole point of the control is that a runite bar pays 50 xp and
              // eats eight coal doing it.
              `<option value="${esc(o.key)}"${o.key === pick ? ' selected' : ''}>` +
              `${esc(o.label)} — ${fmtXpEach(o.perUnit)} xp per ${esc(unit)}` +
              `${o.n > 1 ? `, ${o.n} ${esc(unit)} each` : ''}` +
              `${o.aboveLevel ? ` (lvl ${o.level})` : ''}</option>`
            ).join('')}
            <option value="${DROP}"${off ? ' selected' : ''}>Don't use these &mdash; leave in the bank</option>
          </select>
        </label>`;
    }).join('');

    // Anything dropped that never had a fork of its own — an alchemy target,
    // mostly. Those are chosen on the step that eats them, and this is where
    // they come back from.
    const orphans = [...dropped].filter((id) => !groups.some((g) => g.id === id));

    return `
      <div class="xp-choices">
        <div class="xp-choices-head">
          <b>What to make.</b> Every item two recipes want is a fork; the default
          takes the one paying most per unit of it, which is a stated choice and
          not the only sane one. Anything you would rather keep can be dropped
          out of the plan entirely.
          ${pins ? `<button type="button" class="btn tiny xp-choice-reset"
             data-skill="${esc(skill.skill)}">Back to best rate</button>` : ''}
        </div>
        <div class="xp-choice-row">${pickers}</div>
        ${orphans.length ? `
        <div class="xp-dropped">
          <b>Left out.</b>
          ${orphans.map((id) => {
            const it = itemsDb[String(id)];
            return `<button type="button" class="xp-drop-chip" data-skill="${esc(skill.skill)}" ` +
              `data-restore="${id}" title="Put this back in the plan">` +
              `${esc(it ? it.name : id)} <span class="x">&times;</span></button>`;
          }).join('')}
        </div>` : ''}
        ${pins && Math.abs(delta) > 0.5 ? `
        <div class="xp-choice-delta ${delta >= 0 ? 'up' : 'down'}">
          ${delta >= 0 ? `${fmt(delta)} xp <b>more</b> than the default plan`
                       : `${fmt(-delta)} xp <b>less</b> than the default plan`}
          &mdash; ${fmt(skill.autoXp)} xp if you leave every fork alone.
        </div>` : ''}
        ${pins && !skill.steps.length ? `
        <div class="xp-choice-delta down">
          Nothing in this bank feeds the recipes you pinned. Set a fork back to
          best rate to see a plan again.
        </div>` : ''}
      </div>`;
  }

  // How many alchs to actually do.
  //
  // Alchemy is limited by runes, not by anything worth alching: a bank with
  // 39,000 nature runes burns the last 12,000 on bronze arrows and spades. So
  // dropping the junk one item at a time is whack-a-mole — the casts are still
  // there and just reach deeper into the bank. The count is the real control,
  // and since targets are eaten best-first, stopping early keeps the good ones.
  function castBlock(skill) {
    const alch = skill.alch;
    if (!alch || !alch.max) return '';
    const cap = skill.castCap != null ? skill.castCap : alch.max;
    const worth = alch.worthIt;
    return `
      <div class="xp-casts">
        <label>
          <span>Alchs to cast</span>
          <input type="number" class="xp-cast-input" min="0" max="${alch.max}"
                 step="1" value="${cap}" data-skill="${esc(skill.skill)}">
        </label>
        <span class="xp-casts-of">of ${fmt(alch.max)} the runes allow</span>
        ${worth && worth < alch.max ? `
        <button type="button" class="btn tiny xp-cast-preset"
          data-skill="${esc(skill.skill)}" data-casts="${worth}">Just the ${
          fmt(worth)} worth alching</button>` : ''}
        ${skill.castCap != null ? `
        <button type="button" class="btn tiny xp-cast-preset"
          data-skill="${esc(skill.skill)}" data-casts="">All of them</button>` : ''}
        <span class="xp-casts-note">Targets are eaten best-first, so stopping
          early keeps the ones worth alching and leaves the spades alone.</span>
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
          <p class="xp-lede">
            Recipes above your level are included, but only as far as this bank can
            actually carry you: a plan that takes Smithing 67 to 68 will not suggest
            a rune platebody at 99.
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
      // A re-solve rebuilds the whole list, so which panels the reader had
      // open has to be carried across or picking a fork snaps them shut.
      const open = opts && opts.openSkills
        ? opts.openSkills.has(skill.skill)
        : idx === 0;
      el.className = 'xp-skill' + (open ? ' open' : '');
      el.dataset.skill = skill.skill;
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
          ${skill.outOfReach && skill.outOfReach.length ? `
          <div class="xp-caveat">
            <b>${skill.outOfReach.length} recipe${skill.outOfReach.length === 1 ? '' : 's'}
            this bank holds the stock for ${skill.outOfReach.length === 1 ? 'is' : 'are'} out of reach.</b>
            ${skill.outOfReach.map((r) =>
              `${esc(r.label)} <i>level ${r.level}</i>`).join(' &middot; ')}
            &mdash; and ${skill.totalXp
              ? `the ${fmt(skill.totalXp)} xp here only takes you to ${skill.levelCap}`
              : `there is nothing else here to level on`}, so
            ${skill.outOfReach.length === 1 ? 'it is' : 'they are'} not counted.
          </div>` : ''}
          ${skill.truncated ? `
          <div class="xp-caveat">
            The chain walk hit its pass limit with work still to do, so this total is a
            floor, not the answer. That takes a bank holding thousands of one thing and
            a handful of the container it cycles through &mdash; if yours is not shaped
            like that, it is worth reporting.
          </div>` : ''}
          ${skill.estimatedXp ? `
          <div class="xp-caveat">
            ${fmt(skill.estimatedXp)} xp of this (${((skill.estimatedXp / skill.totalXp) * 100).toFixed(0)}%)
            comes from recipes that can fail &mdash; an expectation, not a count.
          </div>` : ''}
          ${skill.shopping && skill.shopping.length ? `
          <div class="xp-shopping">
            <b>Buy on the way.</b>
            ${skill.shopping.map((b) =>
              `${esc(b.name)} &times;${fmt(b.n)} at ${fmt(b.each)} gp` +
              ` = ${fmtCompact(b.n * b.each)} gp`).join(' &middot; ')}
            &mdash; shop stock this plan assumes you buy rather than bank. It is
            counted in the gp-in figure above.
          </div>` : ''}
          ${castBlock(skill)}
          ${choiceBlock(skill, itemsDb)}
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

      // Picking a fork, whether from the select or from a road-not-taken chip
      // under a step, is the same action: pin one recipe to one item and ask
      // for a fresh solve.
      const onPick = opts && opts.onPick;
      const onDrop = opts && opts.onDrop;
      const onCasts = opts && opts.onCasts;
      if (onPick) {
        const box = el.querySelector('.xp-cast-input');
        if (box) {
          box.addEventListener('change', () => {
            const n = Math.max(0, Math.round(Number(box.value) || 0));
            onCasts(box.dataset.skill, n >= skill.alch.max ? null : n);
          });
        }
        el.querySelectorAll('.xp-choices select').forEach((sel) => {
          sel.addEventListener('change', () => {
            const id = Number(sel.dataset.item);
            if (sel.value === DROP) onDrop(sel.dataset.skill, id, true);
            else onPick(sel.dataset.skill, id, sel.value || null);
          });
        });
        const reset = el.querySelector('.xp-choice-reset');
        if (reset) {
          reset.addEventListener('click', () => onPick(skill.skill, null, null));
        }
        el.addEventListener('click', (e) => {
          // Three controls, one delegated listener: pin an alternative, drop
          // an alchemy target, put a dropped item back.
          const alt = e.target.closest('.xp-alt[data-pin-key]');
          if (alt) {
            onPick(skill.skill, Number(alt.dataset.pinItem), alt.dataset.pinKey);
            return;
          }
          const preset = e.target.closest('.xp-cast-preset');
          if (preset) {
            onCasts(skill.skill, preset.dataset.casts === ''
              ? null : Number(preset.dataset.casts));
            return;
          }
          const eat = e.target.closest('[data-drop-item]');
          if (eat) {
            onDrop(skill.skill, Number(eat.dataset.dropItem), true);
            return;
          }
          const back = e.target.closest('[data-restore]');
          if (back) onDrop(skill.skill, Number(back.dataset.restore), false);
        });
      }

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
