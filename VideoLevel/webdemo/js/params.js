/* Hai bộ tham số. "production" khớp bộ thật bdlop-open-128-v3 của hệ thống
   (N=256, q=2^30-35, hạng M-SIS n=7, hạng M-LWE λ=7, κ=60). "demo" nhỏ hơn
   để chạy tức thì trong trình duyệt — cùng cấu trúc, cùng thuật toán. */
(function (ZK) {
  "use strict";
  ZK.PARAMS = {
    demo: {
      id: "demo-N64", label: "Demo (N=64) — nhanh, chạy tức thì",
      N: 64, q: 12289,
      msisRank: 2, mlweRank: 2,   // width = msis + mlwe + 1
      kappa: 16, eta: 1, gamma: 4096,
      note: "Vành nhỏ để minh hoạ tức thì."
    },
    production: {
      id: "bdlop-open-128-v3", label: "Sản xuất (N=256) — khớp hệ thống thật",
      N: 256, q: 1073741789,       // 2^30 - 35
      msisRank: 7, mlweRank: 7,    // width = 15
      kappa: 60, eta: 1, gamma: 131072, // 2^17
      note: "Đúng bộ tham số bdlop-open-128-v3 (binding 172/156 bit). Một lượt chứng minh mất ~vài giây."
    }
  };
  ZK.derive = function (p) {
    var width = p.msisRank + p.mlweRank + 1;
    return {
      N: p.N, q: p.q, width: width,
      msisRank: p.msisRank, mlweRank: p.mlweRank,
      kappa: p.kappa, eta: p.eta, gamma: p.gamma,
      beta: p.kappa * p.eta,          // chặn ||c·r||_inf với r tam phân
      zBound: p.gamma - p.kappa * p.eta,
      id: p.id, label: p.label, note: p.note
    };
  };
})(window.ZK = window.ZK || {});
