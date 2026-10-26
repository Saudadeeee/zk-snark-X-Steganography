/* Chứng minh mở (opening proof) kiểu Lyubashevsky / BDLOP — Fiat–Shamir có abort.
   Chứng minh: "tôi biết r NGẮN sao cho t1 = B1·r", mà KHÔNG lộ r.
   Sơ đồ (phi tương tác):
     1. mask y ngắn  →  w = B1·y
     2. thử thách c = Hash(khoá, t1, w, D)   (D = digest ràng buộc video/phiên)
     3. phản hồi z = y + c·r
     4. rejection: chỉ nhận nếu ||z||_inf ≤ gamma − beta (nếu quá lớn, z sẽ lộ r → thử lại)
   Kiểm tra: tính lại w' = B1·z − c·t1, rồi c' = Hash(khoá, t1, w', D); nhận nếu c'=c và z ngắn.
   Vì D nằm trong hàm băm, sửa video → D đổi → c' đổi → TỪ CHỐI. */
(function (ZK) {
  "use strict";

  // SampleInBall: tạo đa thức thử thách có đúng kappa hệ số ±1 từ một hạt băm
  function challenge(ring, P, keySeed, t1, w, D) {
    var input = ZK.concatBytes([keySeed, ring.toBytes(t1), ring.toBytes(w), D]);
    var h = ZK.sha256(input);
    var prng = ZK.prng(h);
    var N = ring.N, q = ring.q, c = ring.zero();
    for (var i = N - P.kappa; i < N; i++) {
      var j = prng.below(i + 1);
      c[i] = c[j];
      c[j] = prng.below(2) ? (q - 1) : 1; // -1 hoặc +1
    }
    return c;
  }

  function polyEqual(a, b) {
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  var MAX_ATTEMPTS = 400;

  // r: width đa thức ngắn; t1: msisRank đa thức; D: Uint8Array
  function prove(ring, P, key, t1, r, D, randSeedBytes, onAttempt) {
    var attempts = 0;
    for (var a = 0; a < MAX_ATTEMPTS; a++) {
      attempts++;
      var sub = ZK.sha256(ZK.concatBytes([ZK.strBytes("prove/" + a + "/"), randSeedBytes]));
      var prng = ZK.prng(sub);
      var y = [];
      for (var j = 0; j < P.width; j++) y.push(ring.sampleMask(prng, P.gamma));
      var w = ring.matVec(key.A, key.rows, key.cols, y);
      var c = challenge(ring, P, key.seed, t1, w, D);
      var z = [], ok = true, maxNorm = 0;
      for (j = 0; j < P.width; j++) {
        var zj = ring.add(y[j], ring.mul(c, r[j]));
        z.push(zj);
        var nj = ring.infNorm(zj);
        if (nj > maxNorm) maxNorm = nj;
      }
      ok = maxNorm <= P.zBound;
      if (onAttempt) onAttempt(attempts, ok, maxNorm);
      if (ok) return { accepted: true, attempts: attempts, c: c, z: z, w: w, maxNorm: maxNorm };
    }
    return { accepted: false, attempts: attempts };
  }

  // bản bất đồng bộ: nhường luồng sau mỗi lần thử để UI không bị treo (dùng cho N=256)
  function proveAsync(ring, P, key, t1, r, D, randSeedBytes, onAttempt) {
    return new Promise(function (resolve) {
      var a = 0, attempts = 0;
      function tick() {
        if (a >= MAX_ATTEMPTS) { resolve({ accepted: false, attempts: attempts }); return; }
        attempts++;
        var sub = ZK.sha256(ZK.concatBytes([ZK.strBytes("prove/" + a + "/"), randSeedBytes]));
        var prng = ZK.prng(sub), y = [], j;
        for (j = 0; j < P.width; j++) y.push(ring.sampleMask(prng, P.gamma));
        var w = ring.matVec(key.A, key.rows, key.cols, y);
        var c = challenge(ring, P, key.seed, t1, w, D);
        var z = [], maxNorm = 0;
        for (j = 0; j < P.width; j++) {
          var zj = ring.add(y[j], ring.mul(c, r[j]));
          z.push(zj);
          var nj = ring.infNorm(zj); if (nj > maxNorm) maxNorm = nj;
        }
        var ok = maxNorm <= P.zBound;
        if (onAttempt) onAttempt(attempts, ok, maxNorm);
        a++;
        if (ok) { resolve({ accepted: true, attempts: attempts, c: c, z: z, w: w, maxNorm: maxNorm }); return; }
        setTimeout(tick, 0);
      }
      setTimeout(tick, 0);
    });
  }

  function verify(ring, P, key, t1, c, z, D) {
    // (1) z phải ngắn
    var maxNorm = 0;
    for (var j = 0; j < P.width; j++) { var n = ring.infNorm(z[j]); if (n > maxNorm) maxNorm = n; }
    if (maxNorm > P.zBound) return { ok: false, reason: "z vượt ngưỡng (" + maxNorm + " > " + P.zBound + ")", maxNorm: maxNorm };
    // (2) dựng lại w' = B1·z − c·t1
    var Bz = ring.matVec(key.A, key.rows, key.cols, z);
    var wp = [];
    for (var i = 0; i < key.rows; i++) wp.push(ring.sub(Bz[i], ring.mul(c, t1[i])));
    // (3) thử thách tính lại phải trùng
    var cp = challenge(ring, P, key.seed, t1, wp, D);
    var same = polyEqual(c, cp);
    return { ok: same, reason: same ? "thử thách khớp — hợp lệ" : "thử thách KHÔNG khớp", maxNorm: maxNorm };
  }

  // serialize (c, z) thành byte để nhúng vào video; c: N trị 0/1/2(-1); z: width·N hệ số 4 byte
  function serializeProof(ring, P, c, z) {
    var N = ring.N, q = ring.q;
    var cb = new Uint8Array(N);
    for (var i = 0; i < N; i++) cb[i] = c[i] === 0 ? 0 : (c[i] === 1 ? 1 : 2);
    var zb = ring.toBytes(z);
    return ZK.concatBytes([cb, zb]);
  }
  function deserializeProof(ring, P, bytes) {
    var N = ring.N, q = ring.q;
    var c = ring.zero();
    for (var i = 0; i < N; i++) c[i] = bytes[i] === 0 ? 0 : (bytes[i] === 1 ? 1 : (q - 1));
    var off = N, z = [];
    for (var jz = 0; jz < P.width; jz++) {
      var p = ring.zero();
      for (var t = 0; t < N; t++) {
        var v = (bytes[off] | (bytes[off+1] << 8) | (bytes[off+2] << 16) | (bytes[off+3] << 24)) >>> 0;
        off += 4; p[t] = v % q;
      }
      z.push(p);
    }
    return { c: c, z: z };
  }

  ZK.opening = {
    challenge: challenge, prove: prove, proveAsync: proveAsync, verify: verify,
    serializeProof: serializeProof, deserializeProof: deserializeProof,
    MAX_ATTEMPTS: MAX_ATTEMPTS
  };
})(window.ZK = window.ZK || {});
