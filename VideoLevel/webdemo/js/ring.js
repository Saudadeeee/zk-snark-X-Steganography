/* Số học trên vành R_q = Z_q[X]/(X^N + 1) — "vành negacyclic".
   Đây đúng là vành mà commitment BDLOP của hệ thống thật dùng (N=256, q=2^30-35).
   Hệ số giữ trong [0, q). Nhân dùng tách limb 15-bit để mọi tích < 2^53 (an toàn
   với Number, không cần BigInt), nên chạy được cả bộ tham số sản xuất. */
(function (ZK) {
  "use strict";

  // (a*b) mod q với a,b trong [0,q), q < 2^31. Mọi trung gian < 2^46.
  function mulmod(a, b, q) {
    var bh = Math.floor(b / 32768), bl = b - bh * 32768;
    var lo = (a * bl) % q;
    var hi = ((a * bh) % q) * 32768 % q;
    var r = lo + hi;
    if (r >= q) r -= q;
    return r;
  }

  function Ring(N, q) { this.N = N; this.q = q; }

  Ring.prototype.zero = function () { return new Float64Array(this.N); };

  Ring.prototype.add = function (a, b) {
    var N = this.N, q = this.q, c = new Float64Array(N);
    for (var i = 0; i < N; i++) { var s = a[i] + b[i]; c[i] = s >= q ? s - q : s; }
    return c;
  };
  Ring.prototype.sub = function (a, b) {
    var N = this.N, q = this.q, c = new Float64Array(N);
    for (var i = 0; i < N; i++) { var s = a[i] - b[i]; c[i] = s < 0 ? s + q : s; }
    return c;
  };

  // nhân negacyclic: X^N = -1
  Ring.prototype.mul = function (a, b) {
    var N = this.N, q = this.q;
    var acc = new Float64Array(N); // tích con đã rút mod q nên tổng < N*q < 2^38
    for (var i = 0; i < N; i++) {
      var ai = a[i];
      if (ai === 0) continue;
      for (var j = 0; j < N; j++) {
        var bj = b[j];
        if (bj === 0) continue;
        var p = mulmod(ai, bj, q);
        var k = i + j;
        if (k < N) { acc[k] += p; } else { acc[k - N] -= p; }
      }
    }
    var out = new Float64Array(N);
    for (var t = 0; t < N; t++) {
      var v = acc[t] % q;
      if (v < 0) v += q;
      out[t] = v;
    }
    return out;
  };

  // biểu diễn tâm hoá trong (-q/2, q/2] để tính chuẩn vô cùng
  Ring.prototype.centered = function (x) {
    var q = this.q;
    return x > q / 2 ? x - q : x;
  };
  Ring.prototype.infNorm = function (a) {
    var N = this.N, m = 0;
    for (var i = 0; i < N; i++) {
      var v = this.centered(a[i]); if (v < 0) v = -v; if (v > m) m = v;
    }
    return m;
  };

  // ma trận (mảng các đa thức theo hàng-rồi-cột) nhân vector đa thức
  Ring.prototype.matVec = function (A, rows, cols, r) {
    var out = [];
    for (var i = 0; i < rows; i++) {
      var acc = this.zero();
      for (var j = 0; j < cols; j++) acc = this.add(acc, this.mul(A[i * cols + j], r[j]));
      out.push(acc);
    }
    return out;
  };

  // lấy mẫu đều một đa thức trong R_q
  Ring.prototype.sampleUniform = function (prng) {
    var N = this.N, q = this.q, p = new Float64Array(N);
    for (var i = 0; i < N; i++) p[i] = prng.below(q);
    return p;
  };
  // hệ số trong {-1,0,1} (lưu -1 = q-1)
  Ring.prototype.sampleTernary = function (prng) {
    var N = this.N, q = this.q, p = new Float64Array(N);
    for (var i = 0; i < N; i++) {
      var b = prng.below(3); // 0,1,2 -> 0,1,-1
      p[i] = b === 2 ? q - 1 : b;
    }
    return p;
  };
  // mask: hệ số đều trong [-B, B], lưu mod q
  Ring.prototype.sampleMask = function (prng, B) {
    var N = this.N, q = this.q, p = new Float64Array(N), span = 2 * B + 1;
    for (var i = 0; i < N; i++) {
      var v = prng.below(span) - B;
      p[i] = v < 0 ? v + q : v;
    }
    return p;
  };

  // nối các đa thức thành byte (để băm / serialize), 4 byte/hệ số
  Ring.prototype.toBytes = function (polys) {
    var N = this.N, out = new Uint8Array(polys.length * N * 4), o = 0, i, t, v;
    for (i = 0; i < polys.length; i++) {
      for (t = 0; t < N; t++) {
        v = polys[i][t] >>> 0;
        out[o++] = v & 255; out[o++] = (v >>> 8) & 255; out[o++] = (v >>> 16) & 255; out[o++] = (v >>> 24) & 255;
      }
    }
    return out;
  };

  ZK.Ring = Ring;
  ZK.mulmod = mulmod;
})(window.ZK = window.ZK || {});
