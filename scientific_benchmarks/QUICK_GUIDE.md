# 🎯 HƯỚNG DẪN NHANH - Multi-Variable Benchmark

## Bạn Cần Xem Gì?

### 📊 Xem Biểu Đồ Ngay
```bash
cd scientific_benchmarks
xdg-open multi_var_results/figures/multi_variable_analysis.png
```

**File này có 16 panels** cho 4 biến:
- **Row 1 (A-D)**: IMAGE SIZE effects
- **Row 2 (E-H)**: MESSAGE LENGTH effects  
- **Row 3 (I-L)**: MESSAGE TYPE effects
- **Row 4 (M-P)**: PROOF SIZE effects

---

## 📖 Đọc Báo Cáo

### Tiếng Việt (đầy đủ)
```bash
cat multi_var_results/KET_QUA_DA_BIEN.md
# hoặc
code multi_var_results/KET_QUA_DA_BIEN.md
```

### Tiếng Anh (chi tiết hơn)
```bash
cat multi_var_results/MULTI_VARIABLE_REPORT.md
```

### Tóm tắt nhanh
```bash
cat multi_var_results/README.md
```

---

## 🔍 Tìm Thông Tin Cụ Thể

### "Image size có ảnh hưởng gì?"
→ Xem **Panels A-D** hoặc đọc phần "1️⃣ Test IMAGE SIZE" trong báo cáo

**TL;DR**: Ảnh lớn hơn → PSNR cao hơn (72 dB → 97 dB)

---

### "Message length ảnh hưởng ra sao?"
→ Xem **Panels E-H** hoặc đọc phần "2️⃣ Test MESSAGE LENGTH"

**TL;DR**: O(n) linear, throughput đỉnh 275 Kbps, an toàn ≤ 2000 chars

---

### "Loại message có quan trọng không?"
→ Xem **Panels I-L** hoặc đọc phần "3️⃣ Test MESSAGE TYPE"

**TL;DR**: Không, tất cả các loại đều giống nhau (~84 dB, an toàn)

---

### "Proof size lớn thế nào?"
→ Xem **Panels M-P** hoặc đọc phần "4️⃣ Test PROOF SIZE"

**TL;DR**: Rất nhỏ (< 5 KB), tăng ~2 bytes/char

---

## 📊 Xem Raw Data

### JSON format
```bash
cat multi_var_results/data/multi_var_results_*.json | jq
```

### Specific variable
```bash
# Image size tests
cat multi_var_results/data/*.json | jq '.results.image_size'

# Message length tests
cat multi_var_results/data/*.json | jq '.results.message_length'

# Message type tests
cat multi_var_results/data/*.json | jq '.results.message_type'

# Proof size tests
cat multi_var_results/data/*.json | jq '.results.proof_size'
```

---

## 🔄 Chạy Lại Benchmark

### Chạy toàn bộ (22 tests)
```bash
cd scientific_benchmarks
python multi_variable_benchmark.py
```

**Thời gian**: ~2-3 phút

### Kết quả sẽ xuất hiện trong:
- `multi_var_results/figures/multi_variable_analysis.png`
- `multi_var_results/data/multi_var_results_*.json`

---

## 📈 So Sánh với Version Cũ

```bash
cat VERSION_COMPARISON.md
```

**Highlights**:
- v2.0: 1 biến, 9 tests, 14 panels
- v3.0: **4 biến, 22 tests, 16 panels** ✅

---

## ❓ FAQs

**Q: Tại sao có 2 thư mục results/ và multi_var_results/?**  
A: 
- `results/` = v2.0 (chỉ message length)
- `multi_var_results/` = v3.0 (4 biến đầy đủ) ✅

**Q: Tôi nên dùng version nào cho paper?**  
A: Dùng v3.0 (`multi_var_results/`) - đầy đủ hơn

**Q: File .tex ở đâu?**  
A: Không có! Đã loại bỏ theo yêu cầu. Chỉ có PNG và Markdown.

**Q: Tôi muốn test thêm kích thước ảnh khác?**  
A: Edit `multi_variable_benchmark.py`, thêm vào list `image_sizes`

**Q: 16 panels quá nhiều, tôi chỉ cần vài cái?**  
A: Crop PNG hoặc tham khảo code để tạo subset plots

---

## 🎯 Quick Reference

### Best Settings (từ benchmark)
- **Image size**: 1024×1024 hoặc 2048×2048
- **Message length**: < 2000 chars
- **Message type**: Bất kỳ (text, binary, etc.)
- **Expected PSNR**: 80-90 dB
- **Expected throughput**: 200-275 Kbps
- **Proof overhead**: ~2 bytes/char

### Performance
- Embedding: 2-120 ms (tùy message length)
- Extraction: 0.3-120 ms (tùy message length)
- Proof generation: Skipped (cần ZK circuits)
- Memory: < 100 MB

### Security
- 95.5% undetectable (21/22 tests)
- Chi-square p > 0.05 for safe messages
- Risk threshold: > 2000 chars for 1M pixels

---

## 📞 Cần Hỗ Trợ?

1. **Đọc báo cáo chi tiết**: `KET_QUA_DA_BIEN.md`
2. **Xem raw data**: `multi_var_results/data/*.json`
3. **So sánh versions**: `VERSION_COMPARISON.md`
4. **Check code**: `multi_variable_benchmark.py`

---

## ✅ Checklist Sử Dụng

- [ ] Đã xem `multi_variable_analysis.png`
- [ ] Đã đọc `KET_QUA_DA_BIEN.md` hoặc `MULTI_VARIABLE_REPORT.md`
- [ ] Hiểu rõ 4 biến: image size, message length, message type, proof size
- [ ] Biết cách trích dẫn kết quả cho paper
- [ ] Đã check raw data nếu cần chi tiết

---

*Quick Guide - Multi-Variable Benchmark v3.0*  
*October 15, 2025*
