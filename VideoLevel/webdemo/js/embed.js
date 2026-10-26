/* Nhúng/trích bit vào bit cuối của |hệ số| tại các vị trí carrier (LSB, giữ dấu).
   Giống bước vá bitstream của hệ thật: chỉ chạm carrier, giữ nguyên mọi thứ khác. */
(function (ZK) {
  "use strict";

  function bytesToBits(bytes) {
    var bits = new Uint8Array(bytes.length * 8), o = 0, i, b;
    for (i = 0; i < bytes.length; i++) for (b = 7; b >= 0; b--) bits[o++] = (bytes[i] >> b) & 1;
    return bits;
  }
  function bitsToBytes(bits, nbytes) {
    var out = new Uint8Array(nbytes), i, b, v;
    for (i = 0; i < nbytes; i++) { v = 0; for (b = 0; b < 8; b++) v = (v << 1) | (bits[i * 8 + b] || 0); out[i] = v; }
    return out;
  }

  // ghi bit vào model.blocks tại carriers (tại chỗ). Trả số carrier đã đổi.
  function embed(model, carriers, bytes) {
    var bits = bytesToBits(bytes), need = bits.length;
    if (need > carriers.length) throw new Error("Không đủ dung lượng: cần " + need + " carrier, có " + carriers.length);
    var changed = 0;
    for (var i = 0; i < need; i++) {
      var c = carriers[i], v = model.blocks[c.b][c.k];
      var s = v < 0 ? -1 : 1, a = Math.abs(v);
      var na = (a & ~1) | bits[i];
      var nv = s * na;
      if (nv !== v) changed++;
      model.blocks[c.b][c.k] = nv;
    }
    return { bitsWritten: need, carriersUsed: need, changed: changed };
  }

  function extract(model, carriers, nbytes) {
    var nbits = nbytes * 8, bits = new Uint8Array(nbits);
    for (var i = 0; i < nbits; i++) {
      var c = carriers[i], v = model.blocks[c.b][c.k];
      bits[i] = Math.abs(v) & 1;
    }
    return bitsToBytes(bits, nbytes);
  }

  ZK.embed = { embed: embed, extract: extract, bytesToBits: bytesToBits, bitsToBytes: bitsToBytes };
})(window.ZK = window.ZK || {});
