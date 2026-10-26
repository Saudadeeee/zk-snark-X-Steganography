/* SHA-256 thuần JS (không phụ thuộc crypto.subtle, chạy trong mọi sandbox).
   Dùng cho Fiat–Shamir, PRNG tất định và digest ràng buộc statement. */
(function (ZK) {
  "use strict";
  var K = [
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];

  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }

  // data: Uint8Array -> Uint8Array(32)
  function sha256(data) {
    var H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var l = data.length;
    var withOne = l + 1;
    var k = (56 - (withOne % 64) + 64) % 64;
    var total = withOne + k + 8;
    var msg = new Uint8Array(total);
    msg.set(data);
    msg[l] = 0x80;
    var bitLenHi = Math.floor((l * 8) / 0x100000000);
    var bitLenLo = (l * 8) >>> 0;
    var dv = new DataView(msg.buffer);
    dv.setUint32(total - 8, bitLenHi);
    dv.setUint32(total - 4, bitLenLo);

    var w = new Int32Array(64);
    for (var off = 0; off < total; off += 64) {
      for (var i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4);
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i-15],7) ^ rotr(w[i-15],18) ^ (w[i-15] >>> 3);
        var s1 = rotr(w[i-2],17) ^ rotr(w[i-2],19) ^ (w[i-2] >>> 10);
        w[i] = (w[i-16] + s0 + w[i-7] + s1) | 0;
      }
      var a=H[0],b=H[1],c=H[2],d=H[3],e=H[4],f=H[5],g=H[6],h=H[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[i] + w[i]) | 0;
        var S0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        h=g; g=f; f=e; e=(d + t1)|0; d=c; c=b; b=a; a=(t1 + t2)|0;
      }
      H[0]=(H[0]+a)|0; H[1]=(H[1]+b)|0; H[2]=(H[2]+c)|0; H[3]=(H[3]+d)|0;
      H[4]=(H[4]+e)|0; H[5]=(H[5]+f)|0; H[6]=(H[6]+g)|0; H[7]=(H[7]+h)|0;
    }
    var out = new Uint8Array(32), o = new DataView(out.buffer);
    for (i = 0; i < 8; i++) o.setUint32(i * 4, H[i] >>> 0);
    return out;
  }

  function toHex(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    return s;
  }
  function strBytes(s) {
    var b = [], i, c;
    for (i = 0; i < s.length; i++) {
      c = s.charCodeAt(i);
      if (c < 128) b.push(c);
      else if (c < 2048) { b.push(192 | (c >> 6), 128 | (c & 63)); }
      else { b.push(224 | (c >> 12), 128 | ((c >> 6) & 63), 128 | (c & 63)); }
    }
    return new Uint8Array(b);
  }
  function concat(arrs) {
    var n = 0, i;
    for (i = 0; i < arrs.length; i++) n += arrs[i].length;
    var out = new Uint8Array(n), off = 0;
    for (i = 0; i < arrs.length; i++) { out.set(arrs[i], off); off += arrs[i].length; }
    return out;
  }

  ZK.sha256 = sha256;
  ZK.sha256hex = function (data) { return toHex(sha256(data)); };
  ZK.hex = toHex;
  ZK.strBytes = strBytes;
  ZK.concatBytes = concat;
})(window.ZK = window.ZK || {});
