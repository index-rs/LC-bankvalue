// packet.js — minimal big-endian byte reader, ported from LostCityRS/Engine-TS's
// src/io/Packet.ts (g1/g2/g4s/g8/gVarInt semantics). Read-only subset — only the
// methods savParser.js actually needs.
(function () {
  class Packet {
    constructor(arrayBuffer) {
      this.data = new Uint8Array(arrayBuffer);
      this.view = new DataView(arrayBuffer);
      this.pos = 0;
    }

    g1() {
      return this.view.getUint8(this.pos++);
    }

    g2() {
      const v = this.view.getUint16(this.pos);
      this.pos += 2;
      return v;
    }

    g4s() {
      const v = this.view.getInt32(this.pos);
      this.pos += 4;
      return v;
    }

    g8() {
      const v = this.view.getBigInt64(this.pos);
      this.pos += 8;
      return v;
    }

    gVarInt() {
      let byte = this.g1();
      let result = 0;
      while ((byte & 0x80) !== 0) {
        result = (result | (byte & 0x7f)) << 7;
        byte = this.g1();
      }
      return (result | byte) >>> 0;
    }
  }

  window.Packet = Packet;
})();
