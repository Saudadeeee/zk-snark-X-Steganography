/* Chất lượng ảnh: PSNR và SSIM (toàn ảnh) giữa cover và stego. */
(function (ZK) {
  "use strict";
  function psnr(a, b) {
    var n = a.length, se = 0, i, d;
    for (i = 0; i < n; i++) { d = a[i] - b[i]; se += d * d; }
    var mse = se / n;
    if (mse === 0) return Infinity;
    return 10 * Math.log(255 * 255 / mse) / Math.LN10;
  }
  function ssim(a, b) {
    var n = a.length, ma = 0, mb = 0, i;
    for (i = 0; i < n; i++) { ma += a[i]; mb += b[i]; }
    ma /= n; mb /= n;
    var va = 0, vb = 0, cov = 0, da, db;
    for (i = 0; i < n; i++) { da = a[i] - ma; db = b[i] - mb; va += da * da; vb += db * db; cov += da * db; }
    va /= n; vb /= n; cov /= n;
    var C1 = 6.5025, C2 = 58.5225;
    return ((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma * ma + mb * mb + C1) * (va + vb + C2));
  }
  ZK.metrics = { psnr: psnr, ssim: ssim };
})(window.ZK = window.ZK || {});
