/* Nối toàn bộ các bước thành một pipeline, thao tác trên một object "state".
   Theo đúng kiến trúc hệ thật: bằng chứng được ràng buộc và kiểm tra ở MIỀN HỆ SỐ
   (tương tự bitstream H.264). Ảnh dựng lại chỉ để xem và tính PSNR. */
(function (ZK) {
  "use strict";

  function copyModel(m) {
    return { blocks: m.blocks.map(function (b) { return Int32Array.from(b); }),
      bw: m.bw, bh: m.bh, qstep: m.qstep, w: m.w, h: m.h };
  }

  // Bước 1 — phân tích video → hệ số, carrier, dung lượng
  function loadSource(state, luma, w, h, name, qstep) {
    var P = state.P, ring = state.ring;
    var model = ZK.dct.analyze(luma, w, h, qstep);
    var carriers = ZK.carriers.select(model, 2);
    state.source = { name: name, luma: luma, w: w, h: h, qstep: qstep };
    state.cover = { model: model, luma: ZK.dct.reconstruct(model), carriers: carriers };
    state.cover.normBytes = ZK.carriers.normalizedBytes(model, carriers);
    return {
      blocks: model.blocks.length, carriers: carriers.length,
      capacityBits: carriers.length, capacityBytes: Math.floor(carriers.length / 8)
    };
  }

  // Bước 2 — khoá công khai + bí mật + commitment
  function setupKeys(state, mode, payloadStr) {
    var P = state.P, ring = state.ring;
    var keySeed = ZK.strBytes("public-ck/" + P.id);
    var key = ZK.bdlop.deriveKey(ring, P, keySeed);
    var r = ZK.bdlop.sampleRandomness(ring, P, ZK.strBytes("holder-secret/" + Math.random()));
    var t1 = ZK.bdlop.commit(ring, key, r);
    var out = { mode: mode, width: P.width, t1Polys: t1.length };
    state.key = key; state.r = r; state.t1 = t1; state.mode = mode;
    if (mode === "in-band") {
      var pl = ZK.strBytes(payloadStr || "");
      var m = ZK.bdlop.encodePayload(ring, pl);
      state.payload = pl; state.msg = m;
      state.t2 = ZK.bdlop.commitMessage(ring, key, r, m);
      out.payloadBytes = pl.length;
    } else { state.payload = null; state.msg = null; state.t2 = null; }
    // kích thước phong bì (tính theo serialize proof + commitment)
    out.commitBytes = ring.toBytes(t1).length + (state.t2 ? ring.toBytes([state.t2]).length : 0);
    return out;
  }

  // Bước 3 — dựng statement + chạy chứng minh ZKP
  function makeProof(state, onAttempt) {
    var P = state.P, ring = state.ring;
    state.session = ZK.statement.sessionChallenge("S-" + Math.random());
    state.sessionConsumed = false;
    // cỡ proof (và do đó số khung) tính được trước khi chứng minh
    var bytesLen = ring.N + P.width * ring.N * 4;
    var cap = state.cover.carriers.length;
    var F = Math.max(1, Math.ceil((bytesLen * 8) / cap));
    state.frameCount = F;
    // digest ràng buộc đúng bố cục F khung (các khung là bản sao → chuẩn hoá lặp F lần)
    var parts = []; for (var f = 0; f < F; f++) parts.push(state.cover.normBytes);
    state.D = ZK.statement.digest(ZK.concatBytes(parts), F * cap, state.session);
    var seed = ZK.strBytes("prove-nonce/" + Math.random());
    var t0 = performance.now();
    return ZK.opening.proveAsync(ring, P, state.key, state.t1, state.r, state.D, seed, onAttempt)
      .then(function (pr) {
        pr.ms = performance.now() - t0;
        state.proof = pr;
        if (pr.accepted) {
          state.proofBytes = ZK.opening.serializeProof(ring, P, pr.c, pr.z);
          // tự kiểm nội bộ: verify ngay để chắc chứng minh đúng
          pr.selfCheck = ZK.opening.verify(ring, P, state.key, state.t1, pr.c, pr.z, state.D).ok;
        }
        return pr;
      });
  }

  function setLSB(model, c, bit) {
    var v = model.blocks[c.b][c.k], s = v < 0 ? -1 : 1, a = Math.abs(v);
    model.blocks[c.b][c.k] = s * ((a & ~1) | bit);
  }
  function getLSB(model, c) { return Math.abs(model.blocks[c.b][c.k]) & 1; }

  // Bước 4 — nhúng phong bì vào carrier. Nếu một khung không đủ chỗ, rải qua
  // nhiều khung (đúng như hệ thật chia chunk qua các đoạn 100 khung hình).
  function embedProof(state) {
    var ring = state.ring;
    var bits = ZK.embed.bytesToBits(state.proofBytes);
    var cap = state.cover.carriers.length;             // bit/khung
    var frames = Math.max(1, Math.ceil(bits.length / cap));
    var changed = 0, off = 0, out = [];
    for (var f = 0; f < frames; f++) {
      var sm = copyModel(state.cover.model);
      var carriers = ZK.carriers.select(sm, 2);
      var n = Math.min(cap, bits.length - off);
      for (var i = 0; i < n; i++) { var b = bits[off + i]; if (getLSB(sm, carriers[i]) !== b) changed++; setLSB(sm, carriers[i], b); }
      off += n;
      out.push({ model: sm, carriers: carriers, bits: n });
    }
    var luma0 = ZK.dct.reconstruct(out[0].model);
    state.stego = { frames: out, nframes: frames, luma: luma0, totalBits: bits.length,
      psnr: ZK.metrics.psnr(state.cover.luma, luma0), ssim: ZK.metrics.ssim(state.cover.luma, luma0), changed: changed };
    return { nframes: frames, capacityPerFrame: cap, totalBits: bits.length, changed: changed,
      psnr: state.stego.psnr, ssim: state.stego.ssim };
  }

  // Bước 5 — kiểm tra mù từ video stego (+ mô phỏng tấn công)
  // opts: {tamperPicture, tamperCarrier, replay}
  function verifyStego(state, opts) {
    opts = opts || {};
    var P = state.P, ring = state.ring, i;
    // bản sao các khung stego (verifier chỉ thấy "video")
    var frames = state.stego.frames.map(function (fr) {
      return { model: copyModel(fr.model) };
    });

    if (opts.tamperPicture) {
      // sửa nội dung ảnh: đổi hệ số DC một khối (DC không bao giờ là carrier)
      var bi = Math.floor(frames[0].model.blocks.length / 2);
      frames[0].model.blocks[bi][0] += 8;
    }
    if (opts.tamperCarrier) {
      var cs = ZK.carriers.select(frames[0].model, 2), c0 = cs[0];
      var v = frames[0].model.blocks[c0.b][c0.k], s = v < 0 ? -1 : 1, a = Math.abs(v);
      frames[0].model.blocks[c0.b][c0.k] = s * (a ^ 1); // lật bit cuối 1 carrier
    }

    if (opts.replay && state.sessionConsumed) {
      return { ok: false, stage: "phiên", reason: "Thử thách phiên đã bị tiêu thụ → chống phát lại chặn.",
        Dhex: ZK.hex(state.D).slice(0, 24) };
    }

    // verifier tự tính lại mọi thứ từ video (miền hệ số), gộp digest + bit qua các khung
    var normParts = [], totalCarriers = 0, gotBits = [], need = state.stego.totalBits, read = 0;
    for (i = 0; i < frames.length; i++) {
      var carriers = ZK.carriers.select(frames[i].model, 2);
      normParts.push(ZK.carriers.normalizedBytes(frames[i].model, carriers));
      totalCarriers += carriers.length;
      var n = Math.min(carriers.length, need - read);
      for (var j = 0; j < n; j++) gotBits.push(getLSB(frames[i].model, carriers[j]));
      read += n;
    }
    var normBytes = ZK.concatBytes(normParts);
    var Dv = ZK.statement.digest(normBytes, totalCarriers, state.session);
    var gotBytes = ZK.embed.bitsToBytes(gotBits, state.proofBytes.length);
    var dp = ZK.opening.deserializeProof(ring, P, gotBytes);
    var res = ZK.opening.verify(ring, P, state.key, state.t1, dp.c, dp.z, Dv);

    var bytesMatch = true;
    for (i = 0; i < state.proofBytes.length; i++) if (gotBytes[i] !== state.proofBytes[i]) { bytesMatch = false; break; }

    if (res.ok && !opts.replay) state.sessionConsumed = true;

    return {
      ok: res.ok,
      stage: res.ok ? "hoàn tất" : "chứng minh",
      reason: res.ok ? "Hợp lệ — kiểm tra mù từ video thành công." : ("Từ chối: " + res.reason),
      Dhex: ZK.hex(Dv).slice(0, 24),
      Dmatch: (ZK.hex(Dv) === ZK.hex(state.D)),
      bytesMatch: bytesMatch,
      maxNorm: res.maxNorm
    };
  }

  ZK.pipeline = { loadSource: loadSource, setupKeys: setupKeys, makeProof: makeProof,
    embedProof: embedProof, verifyStego: verifyStego, copyModel: copyModel };
})(window.ZK = window.ZK || {});
