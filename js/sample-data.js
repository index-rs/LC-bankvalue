// sample-data.js — a plausible bank, in the same shape savParser.js produces
// ([{ id, count }]), so visitors without a save file can see a real report.
// Ids are real Lost City item ids, so this renders through the same catalog
// and price lookup as a genuine save.
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
})();
