/* PRNG tất định: dòng byte = SHA-256(seed || counter_LE).
   Mọi lấy mẫu (ma trận công khai, randomness, mask, thử thách) đều từ đây,
   nên một seed cho ra đúng một kết quả — tái lập được, giống tinh thần KAT. */
(function (ZK) {
  "use strict";

  function Prng(seedBytes) {
    this.seed = seedBytes instanceof Uint8Array ? seedBytes : ZK.strBytes(String(seedBytes));
    this.ctr = 0;
    this.buf = new Uint8Array(0);
    this.pos = 0;
  }
  Prng.prototype._refill = function () {
    var c = new Uint8Array(4);
    c[0] = this.ctr & 255; c[1] = (this.ctr >>> 8) & 255;
    c[2] = (this.ctr >>> 16) & 255; c[3] = (this.ctr >>> 24) & 255;
    this.ctr++;
    this.buf = ZK.sha256(ZK.concatBytes([this.seed, c]));
    this.pos = 0;
  };
  Prng.prototype.byte = function () {
    if (this.pos >= this.buf.length) this._refill();
    return this.buf[this.pos++];
  };
  Prng.prototype.bytes = function (n) {
    var out = new Uint8Array(n);
    for (var i = 0; i < n; i++) out[i] = this.byte();
    return out;
  };
  // số nguyên không âm < 2^32
  Prng.prototype.u32 = function () {
    return ((this.byte() << 24) | (this.byte() << 16) | (this.byte() << 8) | this.byte()) >>> 0;
  };
  // số nguyên đều trong [0, m) bằng loại bỏ (rejection) để tránh lệch
  Prng.prototype.below = function (m) {
    if (m <= 0) return 0;
    var limit = Math.floor(0x100000000 / m) * m;
    var x;
    do { x = this.u32(); } while (x >= limit);
    return x % m;
  };

  ZK.Prng = Prng;
  ZK.prng = function (seed) { return new Prng(seed); };
})(window.ZK = window.ZK || {});
