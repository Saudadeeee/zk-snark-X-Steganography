/* Biến đổi khối 8×8: DCT-II + lượng tử hoá — bản mô phỏng cho trình duyệt của
   "biến đổi nội khung + lượng tử" trong H.264 (hệ thật dùng biến đổi nguyên 4×4
   của H.264 Baseline; ở đây dùng DCT 8×8 cho dễ minh hoạ, cùng vai trò).
   luma 0..255 → level-shift 128 → DCT → chia qstep làm tròn = hệ số nguyên. */
(function (ZK) {
  "use strict";
  var B = 8;
  var T = []; // T[x][u] = cos((2x+1)uπ/16)
  (function () {
    for (var x = 0; x < B; x++) {
      T[x] = [];
      for (var u = 0; u < B; u++) T[x][u] = Math.cos(((2 * x + 1) * u * Math.PI) / 16);
    }
  })();
  function Cc(u) { return u === 0 ? Math.SQRT1_2 : 1; }

  function fdct(block) { // block: Float [64] đã level-shift
    var out = new Float64Array(64), u, v, x, y, s;
    for (u = 0; u < B; u++) for (v = 0; v < B; v++) {
      s = 0;
      for (x = 0; x < B; x++) for (y = 0; y < B; y++) s += block[x * B + y] * T[x][u] * T[y][v];
      out[u * B + v] = 0.25 * Cc(u) * Cc(v) * s;
    }
    return out;
  }
  function idct(coef) { // → Float [64]
    var out = new Float64Array(64), u, v, x, y, s;
    for (x = 0; x < B; x++) for (y = 0; y < B; y++) {
      s = 0;
      for (u = 0; u < B; u++) for (v = 0; v < B; v++) s += Cc(u) * Cc(v) * coef[u * B + v] * T[x][u] * T[y][v];
      out[x * B + y] = 0.25 * s;
    }
    return out;
  }

  // luma Uint8 (w×h) → danh sách khối hệ số nguyên đã lượng tử
  function analyze(luma, w, h, qstep) {
    var bw = w / B, bh = h / B, blocks = [], bx, by, i, j;
    for (by = 0; by < bh; by++) for (bx = 0; bx < bw; bx++) {
      var blk = new Float64Array(64);
      for (i = 0; i < B; i++) for (j = 0; j < B; j++)
        blk[i * B + j] = luma[(by * B + i) * w + (bx * B + j)] - 128;
      var co = fdct(blk), q = new Int32Array(64);
      for (i = 0; i < 64; i++) q[i] = Math.round(co[i] / qstep);
      blocks.push(q);
    }
    return { blocks: blocks, bw: bw, bh: bh, qstep: qstep, w: w, h: h };
  }

  // khối hệ số → luma Uint8 (dựng lại ảnh)
  function reconstruct(model) {
    var w = model.w, h = model.h, q = model.qstep, B2 = B;
    var luma = new Uint8ClampedArray(w * h), bi = 0, bx, by, i, j;
    for (by = 0; by < model.bh; by++) for (bx = 0; bx < model.bw; bx++) {
      var qc = model.blocks[bi++], co = new Float64Array(64);
      for (i = 0; i < 64; i++) co[i] = qc[i] * q;
      var px = idct(co);
      for (i = 0; i < B2; i++) for (j = 0; j < B2; j++) {
        var v = Math.round(px[i * B2 + j] + 128);
        luma[(by * B2 + i) * w + (bx * B2 + j)] = v < 0 ? 0 : (v > 255 ? 255 : v);
      }
    }
    return luma;
  }

  ZK.dct = { analyze: analyze, reconstruct: reconstruct, BLOCK: B };
})(window.ZK = window.ZK || {});
