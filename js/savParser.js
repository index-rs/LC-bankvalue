// savParser.js — decodes a Lost City player .sav file entirely in the browser.
// Byte layout ported from LostCityRS/Engine-TS's PlayerLoading.ts (MIT-licensed,
// open source engine for the game this data comes from). Verified against a real
// save file during planning: a 240-slot inventory with 235 items, including a
// large coin stack and rune quantities, decoded cleanly — that's the bank.
//
// Runs on a File the user picked/dropped; the file is never sent anywhere.
(function () {
  const SAV_MAGIC = 0x2004;

  // Inventory type ids, from Lost City's Content repo (pack/inv.pack, build 274):
  //   93=inv  94=worn  95=bank
  const INV_BANK = 95;
  const INV_MAIN = 93;
  const INV_WORN = 94;

  class SavParseError extends Error {}

  function parseSave(arrayBuffer) {
    if (arrayBuffer.byteLength < 2) {
      throw new SavParseError('Empty save file (new/unused character — no bank yet).');
    }

    const p = new window.Packet(arrayBuffer);

    const magic = p.g2();
    if (magic !== SAV_MAGIC) {
      throw new SavParseError('Not a recognized Lost City save file.');
    }
    const version = p.g2();

    // position, appearance
    p.g2(); // x
    p.g2(); // z
    p.g1(); // level
    for (let i = 0; i < 7; i++) p.g1(); // body
    for (let i = 0; i < 5; i++) p.g1(); // colors
    p.g1(); // gender
    p.g2(); // runenergy
    if (version >= 2) p.g4s();
    else p.g2(); // playtime

    // stats: 21 skills, each (exp:int32, level:byte)
    for (let i = 0; i < 21; i++) {
      p.g4s(); // exp
      p.g1(); // level
    }

    // varps
    const varpCount = p.g2();
    if (version >= 7) {
      for (let i = 0; i < varpCount; i++) {
        p.g2(); // id
        p.gVarInt(); // value
      }
    } else {
      for (let i = 0; i < varpCount; i++) p.g4s();
    }

    // inventories
    const invCount = p.g1();
    const inventories = [];
    for (let i = 0; i < invCount; i++) {
      const type = p.g2();
      const size = version >= 5 ? p.g2() : null;
      if (size == null) {
        throw new SavParseError('Save format too old to read inventory sizes (pre-v5).');
      }
      const items = [];
      for (let slot = 0; slot < size; slot++) {
        const id = p.g2() - 1;
        if (id === -1) continue;
        let count = p.g1();
        if (count === 255) count = p.g4s();
        items.push({ slot, id, count });
      }
      inventories.push({ type, size, items });
    }

    if (!inventories.length) {
      throw new SavParseError('No inventories found in this save.');
    }

    // Prefer the authoritative bank type id; fall back to "largest inventory"
    // only if a save somehow lacks it (the bank is always by far the biggest —
    // hundreds of slots vs 28 for inventory and 14 for worn).
    const bank =
      inventories.find((inv) => inv.type === INV_BANK) ||
      inventories.reduce((a, b) => (b.size > a.size ? b : a));

    return {
      magic,
      version,
      inventories,
      bank,
      inventory: inventories.find((inv) => inv.type === INV_MAIN) || null,
      worn: inventories.find((inv) => inv.type === INV_WORN) || null,
    };
  }

  window.SavParser = { parseSave, SavParseError, INV_BANK, INV_MAIN, INV_WORN };
})();
