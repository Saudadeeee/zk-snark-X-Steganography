/* Commitment BDLOP.
   Khoá công khai: ma trận B1 (msisRank × width) và vector b2 (1 × width),
   sinh tất định từ một seed công khai. Randomness r = width đa thức tam phân (ngắn).
   t1 = B1 · r           (phần "binding", ràng buộc r — thứ được chứng minh)
   t2 = <b2, r> + enc(m) (phần cam kết payload cho chế độ in-band)
   Ý tưởng: giống niêm phong r (và payload m) vào phong bì; r ngắn nên khó giả,
   nhưng nhìn t1,t2 không suy ra được r hay m (M-LWE). */
(function (ZK) {
  "use strict";

  function deriveKey(ring, P, seedBytes) {
    var prng = ZK.prng(ZK.concatBytes([ZK.strBytes("BDLOP/key/"), seedBytes]));
    var A = [], i;
    for (i = 0; i < P.msisRank * P.width; i++) A.push(ring.sampleUniform(prng));
    var b2 = [];
    for (i = 0; i < P.width; i++) b2.push(ring.sampleUniform(prng));
    return { A: A, b2: b2, rows: P.msisRank, cols: P.width, seed: seedBytes };
  }

  function sampleRandomness(ring, P, seedBytes) {
    var prng = ZK.prng(ZK.concatBytes([ZK.strBytes("BDLOP/rand/"), seedBytes]));
    var r = [];
    for (var j = 0; j < P.width; j++) r.push(ring.sampleTernary(prng));
    return r;
  }

  // mã hoá payload (Uint8Array) thành một đa thức: mỗi hệ số mang vài bit
  function encodePayload(ring, bytes) {
    var N = ring.N, m = ring.zero(), bits = [], i, b;
    for (i = 0; i < bytes.length; i++) for (b = 7; b >= 0; b--) bits.push((bytes[i] >> b) & 1);
    // 12 bit/hệ số (đủ cho demo & sản xuất vì q > 2^12)
    var per = 12, idx = 0;
    for (i = 0; i < N && idx < bits.length; i++) {
      var v = 0;
      for (var k = 0; k < per && idx < bits.length; k++) v = (v << 1) | bits[idx++];
      m[i] = v;
    }
    return m;
  }

  function commit(ring, key, r) {
    return ring.matVec(key.A, key.rows, key.cols, r); // t1: msisRank đa thức
  }
  function commitMessage(ring, key, r, m) {
    var acc = ring.zero();
    for (var j = 0; j < key.cols; j++) acc = ring.add(acc, ring.mul(key.b2[j], r[j]));
    return ring.add(acc, m); // t2
  }

  ZK.bdlop = {
    deriveKey: deriveKey,
    sampleRandomness: sampleRandomness,
    encodePayload: encodePayload,
    commit: commit,
    commitMessage: commitMessage
  };
})(window.ZK = window.ZK || {});
