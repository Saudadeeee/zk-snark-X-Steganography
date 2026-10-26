/* JS dùng chung cho mọi trang: chủ đề sáng/tối, menu mobile, đánh dấu mục đang
   xem, và vài demo nhỏ (kích hoạt nếu phần tử tương ứng có trên trang). */
(function () {
  "use strict";
  var root = document.documentElement;
  function curTheme() { var a = root.getAttribute("data-theme"); if (a) return a; return (window.matchMedia && matchMedia("(prefers-color-scheme:dark)").matches) ? "dark" : "light"; }
  try { var sv = localStorage.getItem("zkv-site-theme"); if (sv) root.setAttribute("data-theme", sv); } catch (e) {}
  function paint() { document.querySelectorAll("[data-theme-btn]").forEach(function (b) { b.textContent = curTheme() === "dark" ? "☀ Sáng" : "☾ Tối"; }); }

  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-theme-btn]");
    if (t) { var n = curTheme() === "dark" ? "light" : "dark"; root.setAttribute("data-theme", n); try { localStorage.setItem("zkv-site-theme", n); } catch (x) {} paint(); return; }
    var m = e.target.closest("[data-menu-btn]");
    if (m) { var sb = document.querySelector(".sidebar"); if (sb) sb.classList.toggle("open"); return; }
    if (!e.target.closest(".sidebar") && !e.target.closest("[data-menu-btn]")) {
      var open = document.querySelector(".sidebar.open"); if (open) open.classList.remove("open");
    }
  });

  function boot() {
    paint();
    // đánh dấu mục đang xem
    var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
    document.querySelectorAll(".sidebar nav a").forEach(function (a) {
      var href = (a.getAttribute("href") || "").toLowerCase();
      if (href === here || (here === "" && href === "index.html")) a.classList.add("active");
    });

    // Demo LSB (nếu có #lsbDemo)
    var lsb = document.getElementById("lsbDemo");
    if (lsb) {
      var cover = [12, -7, 40, 5], secret = [1, 0, 1, 1];
      function render(run) {
        var html = '<div class="coefs">';
        cover.forEach(function (v) { html += '<div class="coef on">' + v + '<small>bit ' + (Math.abs(v) & 1) + '</small></div>'; });
        html += '</div><div style="text-align:center;color:var(--faint)">⬇ giấu chuỗi bí mật <b class="mono">' + secret.join(" ") + '</b> vào bit cuối ⬇</div><div class="coefs">';
        var changed = 0;
        cover.forEach(function (v, i) {
          var a = Math.abs(v), want = secret[i], nv = v;
          if (run) { a = (a & ~1) | want; nv = (v < 0 ? -a : a); if (nv !== v) changed++; }
          html += '<div class="coef on">' + nv + '<small>bit ' + (Math.abs(nv) & 1) + '</small></div>';
        });
        html += '</div>';
        if (run) html += '<p class="muted" style="margin:.4em 0 0">Chỉ <b>' + changed + '/4</b> con số đổi, mỗi cái ±1 — hình gần như không khác, nhưng đã mang 4 bit.</p>';
        lsb.querySelector("[data-out]").innerHTML = html;
      }
      render(false);
      lsb.querySelector("[data-run]").addEventListener("click", function () { render(true); });
    }

    // Demo ZKP rounds (nếu có #zkDemo)
    var zk = document.getElementById("zkDemo");
    if (zk) {
      var honest = true, rounds = [];
      var toggle = zk.querySelector("[data-toggle]"), stepB = zk.querySelector("[data-step]"), resetB = zk.querySelector("[data-reset]"), out = zk.querySelector("[data-out]"), verdict = zk.querySelector("[data-verdict]");
      function draw() {
        out.innerHTML = rounds.map(function (r) { return '<span class="pill" style="border-color:' + (r.ok ? "var(--good)" : "var(--bad)") + ';color:' + (r.ok ? "var(--good)" : "var(--bad)") + '">V hô “' + r.side + '” · ' + (r.ok ? "đúng" : "sai") + '</span>'; }).join("");
        if (!rounds.length) { verdict.className = "callout"; verdict.innerHTML = "Chưa có vòng nào."; return; }
        var fail = rounds.filter(function (r) { return !r.ok; }).length;
        if (fail) { verdict.className = "callout bad"; verdict.innerHTML = "<b>TỪ CHỐI</b> — có " + fail + " vòng sai → không biết mật khẩu."; }
        else { verdict.className = "callout good"; verdict.innerHTML = "<b>CHẤP NHẬN</b> sau " + rounds.length + " vòng. Xác suất ăn may nếu không biết: 1/" + Math.pow(2, rounds.length) + ". Người kiểm tra vẫn không học được mật khẩu."; }
      }
      toggle.addEventListener("click", function () { honest = !honest; toggle.textContent = honest ? "Người chứng minh: BIẾT mật khẩu" : "Người chứng minh: KHÔNG biết (giả mạo)"; rounds = []; draw(); });
      stepB.addEventListener("click", function () { var side = Math.random() < .5 ? "trái" : "phải"; rounds.push({ side: side, ok: honest ? true : Math.random() < .5 }); draw(); });
      resetB.addEventListener("click", function () { rounds = []; draw(); });
      draw();
    }

    // Step player (nếu có [data-stepplayer])
    document.querySelectorAll("[data-stepplayer]").forEach(function (sp) {
      var items = sp.querySelectorAll(".step");
      // chỉ hiệu ứng nhẹ: không ẩn gì (đảm bảo đọc được khi tĩnh)
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
