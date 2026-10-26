/* "Đề bài" (statement) ràng buộc bằng chứng vào đúng video này + đúng phiên này.
   digest D = SHA-256( hệ-số-chuẩn-hoá-carrier || số-carrier || thử-thách-phiên ).
   D được đưa vào hàm băm thử thách của chứng minh. Sửa video → D đổi → verify trượt.
   Thử thách phiên dùng một lần → chống phát lại (replay). */
(function (ZK) {
  "use strict";

  function sessionChallenge(seedStr) {
    return ZK.sha256(ZK.strBytes("session/" + seedStr + "/" + (seedStr ? "" : Math.random())));
  }

  function digest(normBytes, carrierCount, sessionBytes) {
    var cc = new Uint8Array(4);
    cc[0] = carrierCount & 255; cc[1] = (carrierCount >>> 8) & 255;
    cc[2] = (carrierCount >>> 16) & 255; cc[3] = (carrierCount >>> 24) & 255;
    return ZK.sha256(ZK.concatBytes([ZK.strBytes("video-statement/v1\0"), normBytes, cc, sessionBytes]));
  }

  ZK.statement = { sessionChallenge: sessionChallenge, digest: digest };
})(window.ZK = window.ZK || {});
