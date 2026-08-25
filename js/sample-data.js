// sample-data.js — a plausible bank and a plausible character, in the same
// shapes savParser.js produces, so visitors without a save file can see a real
// report. Ids are real Lost City item ids, so this renders through the same
// catalog and price lookup as a genuine save.
(function () {
  window.SAMPLE_BANK = [
    { id: 995, count: 1750000 },   // Coins
    { id: 561, count: 4200 },      // Nature rune
    { id: 565, count: 1800 },      // Blood rune
    { id: 560, count: 3000 },      // Death rune
    { id: 563, count: 2400 },      // Law rune
    { id: 556, count: 12000 },     // Air rune
    { id: 554, count: 9000 },      // Fire rune
    { id: 892, count: 5000 },      // Rune arrow
    { id: 890, count: 8000 },      // Adamant arrow
    { id: 453, count: 5000 },      // Coal
    { id: 2361, count: 400 },      // Adamantite bar
    { id: 444, count: 900 },       // Gold ore
    { id: 1515, count: 1200 },     // Yew logs
    { id: 1513, count: 300 },      // Magic logs
    { id: 257, count: 300 },       // Ranarr weed
    { id: 267, count: 150 },       // Dwarf weed
    { id: 1617, count: 120 },      // Uncut diamond
    { id: 1619, count: 260 },      // Uncut ruby
    { id: 379, count: 850 },       // Lobster
    { id: 385, count: 400 },       // Shark
    { id: 1333, count: 1 },        // Rune scimitar
    { id: 1127, count: 1 },        // Rune platebody
    { id: 1201, count: 1 },        // Rune kiteshield
    { id: 536, count: 260 },       // Dragon bones
    { id: 1753, count: 700 },      // Green dragonhide
    { id: 1777, count: 2000 },     // Bow string
    { id: 314, count: 14000 },     // Feather
    { id: 1042, count: 1 },        // Blue partyhat  (rare — volatile)
    { id: 1050, count: 1 },        // Santa hat      (rare — volatile)
  ];

  // Stats in savParser.js's shape ({ xp, current }), so the XP tab can show the
  // "60 → 68" line it exists for rather than falling back to level 1.
  //
  // These belong to the bank above: someone mid-fletching-grind with 1,200 yew
  // logs and 2,000 bow string, who has not reached the level 85 magic longbows
  // also sitting in there. That makes the sample show the three things that are
  // easy to miss — a recipe badged above your level, a recipe this bank cannot
  // reach at all, and yew logs contested between Fletching and Firemaking.
  //
  // Fletching and Firemaking are set just *over* the yew requirements (70 and
  // 60) rather than just under. They used to sit under, which stopped mattering
  // when the solve started refusing recipes a bank cannot pay its way up to:
  // a level 60 fletcher holding nothing but yew logs can do nothing with them,
  // so the sample demonstrated two empty skills instead of the contention it
  // exists to show. The magic logs stay out of reach on purpose — that is the
  // "1 recipe out of reach" note earning its place.
  //
  // `current` is the drained/boosted level a save stores; nothing reads it, and
  // it is here only so the sample has the same shape as a parsed save.
  window.SAMPLE_STATS = {
    attack: { xp: 759693, current: 70 },
    defence: { xp: 616157, current: 68 },
    strength: { xp: 1044234, current: 73 },
    hitpoints: { xp: 911089, current: 72 },
    ranged: { xp: 424954, current: 64 },
    prayer: { xp: 52006, current: 43 },
    magic: { xp: 305979, current: 61 },
    cooking: { xp: 347887, current: 62 },
    woodcutting: { xp: 823265, current: 71 },
    fletching: { xp: 751400, current: 70 },
    fishing: { xp: 227386, current: 58 },
    firemaking: { xp: 318220, current: 61 },
    crafting: { xp: 232702, current: 58 },
    smithing: { xp: 527748, current: 66 },
    mining: { xp: 374716, current: 63 },
    herblore: { xp: 62954, current: 45 },
    agility: { xp: 78925, current: 47 },
    thieving: { xp: 44162, current: 41 },
    slayer: { xp: 0, current: 1 },
    farming: { xp: 0, current: 1 },
    runecraft: { xp: 19135, current: 33 },
  };
})();
