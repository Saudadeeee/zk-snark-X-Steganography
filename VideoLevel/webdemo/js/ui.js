/* Controller giao diện: nối các nút, vẽ canvas, mở khoá từng bước, ghi nhật ký. */
(function (ZK) {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var state = { Praw: null, P: null, ring: null, src: "container", qp: 16, mode: "registered" };
  var frameCache = {};

  /* ---------- theme ---------- */
  var root = document.documentElement, tb = $("#themeBtn");
  function curTheme() { var a = root.getAttribute("data-theme"); if (a) return a; return (matchMedia && matchMedia("(prefers-color-scheme:dark)").matches) ? "dark" : "light"; }
  try { var sv = localStorage.getItem("zkv-theme"); if (sv) root.setAttribute("data-theme", sv); } catch (e) {}
  function paintTheme() { tb.textContent = curTheme() === "dark" ? "☀" : "☾"; }
  paintTheme();
  tb.addEventListener("click", function () { var n = curTheme() === "dark" ? "light" : "dark"; root.setAttribute("data-theme", n); try { localStorage.setItem("zkv-theme", n); } catch (e) {} paintTheme(); redraw(); });

  /* ---------- log ---------- */
  function log(msg, cls) {
    var el = $("#log"), t = new Date(), hh = ("0"+t.getHours()).slice(-2)+":"+("0"+t.getMinutes()).slice(-2)+":"+("0"+t.getSeconds()).slice(-2);
    var line = document.createElement("div");
    line.innerHTML = '<span class="t">'+hh+'</span> <span'+(cls?' class="'+cls+'"':'')+'>'+msg+'</span>';
    el.appendChild(line); el.scrollTop = el.scrollHeight;
  }
  function num(n){ return Number(n).toLocaleString("vi-VN"); }

  /* ---------- param ---------- */
  function setParam(id) {
    state.Praw = ZK.PARAMS[id];
    state.P = ZK.derive(state.Praw);
    state.ring = new ZK.Ring(state.P.N, state.P.q);
    resetFrom(1);
    log('Bộ tham số <span class="hi">'+state.P.id+'</span>: N='+state.P.N+', q='+num(state.P.q)+', width='+state.P.width+', κ='+state.P.kappa+', γ='+num(state.P.gamma)+'.', "");
  }
  (function () {
    var sel = $("#paramSel");
    Object.keys(ZK.PARAMS).forEach(function (k) { var o=document.createElement("option"); o.value=k; o.textContent=ZK.PARAMS[k].label; sel.appendChild(o); });
    sel.value = "demo";
    sel.addEventListener("change", function () { setParam(sel.value); });
  })();

  /* ---------- frames ---------- */
  function loadImageLuma(name) {
    if (frameCache[name]) return Promise.resolve(frameCache[name]);
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth, h = img.naturalHeight;
        var cv = document.createElement("canvas"); cv.width = w; cv.height = h;
        var cx = cv.getContext("2d"); cx.drawImage(img, 0, 0);
        var d; try { d = cx.getImageData(0, 0, w, h).data; } catch (e) { reject(e); return; }
        var luma = new Uint8ClampedArray(w * h);
        for (var i = 0; i < w * h; i++) luma[i] = d[i * 4]; // ảnh xám: kênh R
        frameCache[name] = { luma: luma, w: w, h: h }; resolve(frameCache[name]);
      };
      img.onerror = function () { reject(new Error("không tải được " + name)); };
      img.src = "data/" + name + ".png";
    });
  }
  function synthFrame() {
    var w = 256, h = 256, luma = new Uint8ClampedArray(w * h);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var v = 128 + 60 * Math.sin(x / 18) * Math.cos(y / 22) + (x + y) / 6 - 30;
      if ((x - 90) * (x - 90) + (y - 90) * (y - 90) < 1600) v += 55;
      if (x > 150 && x < 210 && y > 140 && y < 210) v -= 50;
      v += (((x * 73 + y * 151) % 17) - 8) * 1.3; // texture
      luma[y * w + x] = v < 0 ? 0 : (v > 255 ? 255 : v);
    }
    return Promise.resolve({ luma: luma, w: w, h: h });
  }
  function getFrame() { return state.src === "synth" ? synthFrame() : loadImageLuma(state.src); }

  /* ---------- draw ---------- */
  function drawLuma(canvas, luma, w, h) {
    canvas.width = w; canvas.height = h;
    var cx = canvas.getContext("2d"), img = cx.createImageData(w, h), d = img.data;
    for (var i = 0; i < w * h; i++) { var v = luma[i]; d[i*4]=v; d[i*4+1]=v; d[i*4+2]=v; d[i*4+3]=255; }
    cx.putImageData(img, 0, 0);
  }
  function cssVar(v){ return getComputedStyle(root).getPropertyValue(v).trim(); }
  function drawHeat(canvas, model, carriers) {
    var bw = model.bw, bh = model.bh;
    var cnt = new Float64Array(bw * bh), mx = 1;
    for (var i = 0; i < carriers.length; i++) { cnt[carriers[i].b]++; }
    for (i = 0; i < cnt.length; i++) if (cnt[i] > mx) mx = cnt[i];
    var cell = Math.max(1, Math.floor(256 / Math.max(bw, bh)));
    canvas.width = bw * cell; canvas.height = bh * cell;
    var cx = canvas.getContext("2d");
    cx.fillStyle = cssVar("--surface-2"); cx.fillRect(0, 0, canvas.width, canvas.height);
    var ac = cssVar("--accent");
    for (var by = 0; by < bh; by++) for (var bx = 0; bx < bw; bx++) {
      var a = cnt[by * bw + bx] / mx;
      cx.globalAlpha = 0.12 + 0.88 * a; cx.fillStyle = ac;
      cx.fillRect(bx * cell, by * cell, cell - 1, cell - 1);
    }
    cx.globalAlpha = 1;
  }
  function drawDiff(canvas, a, b, w, h) {
    canvas.width = w; canvas.height = h;
    var cx = canvas.getContext("2d"), img = cx.createImageData(w, h), d = img.data;
    for (var i = 0; i < w * h; i++) { var v = Math.min(255, Math.abs(a[i] - b[i]) * 12); d[i*4]=v; d[i*4+1]=v; d[i*4+2]=v; d[i*4+3]=255; }
    cx.putImageData(img, 0, 0);
  }
  function redraw() {
    if (state.cover) { drawLuma($("#coverCanvas"), state.cover.luma, state.source.w, state.source.h); drawHeat($("#heatCanvas"), state.cover.model, state.cover.carriers); }
    if (state.stego) { drawLuma($("#stegoCanvas"), state.stego.luma, state.source.w, state.source.h); drawDiff($("#diffCanvas"), state.cover.luma, state.stego.luma, state.source.w, state.source.h); }
  }

  /* ---------- stage gating ---------- */
  function lock(id){ $(id).classList.add("locked"); $(id).classList.remove("done"); }
  function unlock(id, btn){ $(id).classList.remove("locked"); if(btn) $(btn).disabled=false; }
  function markDone(id){ $(id).classList.add("done"); }
  function resetFrom(stage) {
    ["cover","key","r","t1","t2","proof","proofBytes","stego","D","session"].forEach(function(k){ if(stage<=1||["proof","proofBytes","stego"].indexOf(k)>=0) {} });
    if (stage <= 1) { state.cover=null; state.key=null; state.proof=null; state.proofBytes=null; state.stego=null; }
    if (stage <= 2) { state.key=null; state.proof=null; state.proofBytes=null; state.stego=null; }
    if (stage <= 3) { state.proof=null; state.proofBytes=null; state.stego=null; }
    if (stage <= 4) { state.stego=null; }
    [["#st2","#s2run"],["#st3","#s3run"],["#st4","#s4run"]].forEach(function(p){ if(stage<= (p[0]==="#st2"?2:p[0]==="#st3"?3:4)) lock(p[0]); });
    ["#vHonest","#vTamperPic","#vTamperCar","#vReplay"].forEach(function(b){ $(b).disabled=true; });
    if (stage<=5) lock("#st5");
  }

  /* ---------- Stage 1 ---------- */
  $("#srcSel").addEventListener("click", function (e) { var b=e.target.closest("button"); if(!b)return; state.src=b.dataset.src; Array.prototype.forEach.call(this.children,function(x){x.classList.toggle("on",x===b);}); });
  $("#qpRange").addEventListener("input", function(){ state.qp=+this.value; $("#qpVal").textContent=this.value; });
  function runStage1() {
    log("Bước 1 — phân tích "+state.src+" (QP="+state.qp+")…");
    return getFrame().then(function (fr) {
      var info = ZK.pipeline.loadSource(state, fr.luma, fr.w, fr.h, state.src, state.qp);
      redraw();
      var cards = [["khối 8×8", num(info.blocks)], ["carrier", num(info.carriers)], ["dung lượng", num(info.capacityBytes)+" B"]];
      $("#s1stats").innerHTML = cards.map(function(c){return '<div class="stat"><div class="big tnum">'+c[1]+'</div><div class="lab">'+c[0]+'</div></div>';}).join("");
      log('→ '+num(info.blocks)+' khối, <span class="hi">'+num(info.carriers)+'</span> carrier (≈ '+num(info.capacityBytes)+' B/khung).', "ok");
      markDone("#st1"); unlock("#st2","#s2run");
      return info;
    }).catch(function(e){ log("Lỗi tải khung: "+e.message, "no"); throw e; });
  }
  $("#s1run").addEventListener("click", function(){ runStage1(); });

  /* ---------- Stage 2 ---------- */
  $("#modeSel").addEventListener("click", function(e){ var b=e.target.closest("button"); if(!b)return; state.mode=b.dataset.mode; Array.prototype.forEach.call(this.children,function(x){x.classList.toggle("on",x===b);}); $("#payloadWrap").style.display = state.mode==="in-band"?"block":"none"; });
  function runStage2() {
    log("Bước 2 — sinh khoá & commitment ("+state.mode+")…");
    var info = ZK.pipeline.setupKeys(state, state.mode, $("#payloadIn").value);
    var kv = [["chế độ", info.mode], ["width (k)", info.width], ["t₁ (số đa thức)", info.t1Polys], ["commitment", num(info.commitBytes)+" B"]];
    if (info.payloadBytes!=null) kv.push(["payload", info.payloadBytes+" B"]);
    $("#s2kv").innerHTML = kv.map(function(r){return "<dt>"+r[0]+"</dt><dd>"+r[1]+"</dd>";}).join("");
    $("#s2hex").textContent = "t₁[0] (xem trước): " + ZK.hex(state.ring.toBytes([state.t1[0]])).slice(0,64) + "…";
    log("→ khoá công khai + r ngắn (tam phân); t₁ = B₁·r. commitment "+num(info.commitBytes)+" B.", "ok");
    markDone("#st2"); unlock("#st3","#s3run");
    return info;
  }
  $("#s2run").addEventListener("click", function(){ runStage2(); });

  /* ---------- Stage 3 ---------- */
  function runStage3() {
    $("#s3run").disabled = true; $("#s3attempts").innerHTML=""; $("#s3status").textContent="đang chạy…";
    log("Bước 3 — statement + chứng minh (Fiat–Shamir có abort)…");
    var att = $("#s3attempts");
    return ZK.pipeline.makeProof(state, function (n, ok, norm) {
      var d=document.createElement("div"); d.className="att "+(ok?"ok":"no"); d.textContent=n; d.title="||z||="+norm; att.appendChild(d);
    }).then(function (pr) {
      if (!pr.accepted) { log("Chứng minh thất bại sau "+pr.attempts+" lần thử.", "no"); $("#s3status").textContent="thất bại"; $("#s3run").disabled=false; return pr; }
      var kv = [["chấp nhận sau", pr.attempts+" lần thử"], ["||z||∞", num(pr.maxNorm)+" ≤ "+num(state.P.zBound)], ["tự verify", pr.selfCheck?"ĐÚNG":"SAI"], ["proof", num(state.proofBytes.length)+" B"], ["thời gian", pr.ms.toFixed(0)+" ms"]];
      $("#s3kv").innerHTML = kv.map(function(r){return "<dt>"+r[0]+"</dt><dd>"+r[1]+"</dd>";}).join("");
      $("#proofHex").textContent = ZK.hex(state.proofBytes).slice(0, 220) + "…";
      $("#s3status").textContent="xong";
      log('→ chấp nhận sau <span class="hi">'+pr.attempts+'</span> lần thử, proof '+num(state.proofBytes.length)+' B, '+pr.ms.toFixed(0)+' ms, tự-verify: '+(pr.selfCheck?'<span class="ok">ĐÚNG</span>':'<span class="no">SAI</span>')+'.', "ok");
      markDone("#st3"); unlock("#st4","#s4run");
      return pr;
    });
  }
  $("#s3run").addEventListener("click", function(){ runStage3(); });

  /* ---------- Stage 4 ---------- */
  function runStage4() {
    log("Bước 4 — nhúng proof vào carrier…");
    var info = ZK.pipeline.embedProof(state);
    redraw();
    var cards = [["PSNR", info.psnr===Infinity?"∞":info.psnr.toFixed(1)+" dB"], ["SSIM", info.ssim.toFixed(4)], ["số khung", num(info.nframes)]];
    $("#s4stats").innerHTML = cards.map(function(c){return '<div class="stat"><div class="big tnum">'+c[1]+'</div><div class="lab">'+c[0]+'</div></div>';}).join("");
    var fr = info.nframes>1 ? ' (rải qua <span class="am">'+info.nframes+' khung</span> vì một khung chỉ chứa '+num(info.capacityPerFrame)+' bit)' : "";
    log('→ nhúng '+num(info.totalBits)+' bit, đổi '+num(info.changed)+' carrier, PSNR '+(info.psnr===Infinity?"∞":info.psnr.toFixed(1))+' dB, SSIM '+info.ssim.toFixed(4)+fr+'.', "ok");
    markDone("#st4"); unlock("#st5");
    ["#vHonest","#vTamperPic","#vTamperCar","#vReplay"].forEach(function(b){ $(b).disabled=false; });
    return info;
  }
  $("#s4run").addEventListener("click", function(){ runStage4(); });

  /* ---------- Stage 5 ---------- */
  function showVerdict(res) {
    var v = $("#verdict");
    v.className = "verdict " + (res.ok ? "ok" : "no");
    v.innerHTML = '<span class="ic">'+(res.ok?"✓":"✕")+'</span><span>'+res.reason+'</span>';
    var kv = [["digest video D", res.Dhex+"…"], ["D khớp lúc nhúng", res.Dmatch===undefined?"—":(res.Dmatch?"có":"KHÔNG")], ["byte proof nguyên vẹn", res.bytesMatch===undefined?"—":(res.bytesMatch?"có":"KHÔNG")]];
    $("#vkv").innerHTML = kv.map(function(r){return "<dt>"+r[0]+"</dt><dd>"+r[1]+"</dd>";}).join("");
    log((res.ok?'<span class="ok">HỢP LỆ</span>':'<span class="no">TỪ CHỐI</span>')+' — '+res.reason, res.ok?"ok":"no");
  }
  $("#vHonest").addEventListener("click", function(){ log("Bước 5 — kiểm tra mù từ video…"); showVerdict(ZK.pipeline.verifyStego(state, {})); });
  $("#vTamperPic").addEventListener("click", function(){ log("Tấn công: sửa nội dung một khung…", "am"); showVerdict(ZK.pipeline.verifyStego(state, {tamperPicture:true})); });
  $("#vTamperCar").addEventListener("click", function(){ log("Tấn công: lật 1 bit carrier…", "am"); showVerdict(ZK.pipeline.verifyStego(state, {tamperCarrier:true})); });
  $("#vReplay").addEventListener("click", function(){ log("Tấn công: phát lại phiên đã dùng…", "am"); showVerdict(ZK.pipeline.verifyStego(state, {replay:true})); });

  /* ---------- Run all ---------- */
  $("#runAll").addEventListener("click", function () {
    var btn = this; btn.disabled = true; $("#runAllNote").textContent = "đang chạy…";
    runStage1().then(function(){ return runStage2(); }).then(function(){ return runStage3(); }).then(function(pr){
      if (pr && pr.accepted) runStage4();
      $("#runAllNote").textContent = "xong — sang bước 5 để kiểm tra & tấn công.";
      btn.disabled = false;
    }).catch(function(e){ $("#runAllNote").textContent = "lỗi: "+(e&&e.message||e); btn.disabled = false; });
  });

  /* ---------- boot ---------- */
  setParam("demo");
  log('Sẵn sàng. Bấm <span class="hi">▶ Chạy toàn bộ</span>, hoặc làm từng bước. Chọn bộ "Sản xuất (N=256)" để chạy đúng tham số thật (chậm hơn, ~vài giây).', "");
})(window.ZK = window.ZK || {});
