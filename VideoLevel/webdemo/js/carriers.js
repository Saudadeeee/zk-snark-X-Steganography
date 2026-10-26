/* Chọn carrier + chuẩn hoá cho digest — mô phỏng carrier "magnitude" của hệ thật:
   chỉ dùng hệ số AC (vị trí != 0 trong khối) có |giá trị| đủ lớn, vì đổi bit cuối
   của nó gần như không ảnh hưởng hình và bên trích tính lại được y hệt. */
(function (ZK) {
  "use strict";

  // trả danh sách vị trí carrier [{b: chỉ số khối, k: chỉ số hệ số}]
  function select(model, minMag) {
    minMag = minMag || 2;
    var list = [], blocks = model.blocks, bi, k, v;
    for (bi = 0; bi < blocks.length; bi++) {
      var blk = blocks[bi];
      for (k = 1; k < 64; k++) { // bỏ DC (k=0)
        v = blk[k];
        if (v >= minMag || v <= -minMag) list.push({ b: bi, k: k });
      }
    }
    return list;
  }

  // byte đã "chuẩn hoá carrier" để băm: xoá bit cuối của |hệ số| tại mọi carrier,
  // giữ nguyên phần còn lại. Nhờ vậy việc NHÚNG (chỉ đổi bit cuối) không làm đổi
  // digest, nhưng mọi thay đổi khác (sửa pixel/cú pháp) thì có → phát hiện tamper.
  function normalizedBytes(model, carriers) {
    var isCarrier = {};
    for (var i = 0; i < carriers.length; i++) isCarrier[carriers[i].b * 64 + carriers[i].k] = 1;
    var blocks = model.blocks, out = new Int32Array(blocks.length * 64), o = 0, bi, k, v;
    for (bi = 0; bi < blocks.length; bi++) {
      for (k = 0; k < 64; k++) {
        v = blocks[bi][k];
        if (isCarrier[bi * 64 + k]) {
          var s = v < 0 ? -1 : 1, a = Math.abs(v) & ~1;
          v = s * a;
        }
        out[o++] = v;
      }
    }
    // Int32 → Uint8 little-endian
    var bytes = new Uint8Array(out.length * 4), bo = 0, t;
    for (t = 0; t < out.length; t++) {
      var u = out[t] >>> 0;
      bytes[bo++] = u & 255; bytes[bo++] = (u >>> 8) & 255; bytes[bo++] = (u >>> 16) & 255; bytes[bo++] = (u >>> 24) & 255;
    }
    return bytes;
  }

  ZK.carriers = { select: select, normalizedBytes: normalizedBytes };
})(window.ZK = window.ZK || {});
