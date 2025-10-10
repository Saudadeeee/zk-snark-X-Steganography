# ZK-SNARK Steganography: File Roles Clarification

## 🤔 **Câu hỏi: "Vì sao vẫn còn public.json, tôi tưởng không cần nữa?"**

### **Trả lời: public.json VẪN CẦN THIẾT trong verification!**

---

## 📋 **Giải thích từng file:**

### **1. input.json** 
- **Vai trò**: Input cho witness generation
- **Chứa**: ALL inputs (public + private)
- **Khi nào cần**: Chỉ ở bước generate witness
- **Gửi đi**: ❌ KHÔNG (chứa private data)

### **2. witness.wtns**
- **Vai trò**: Signal assignments cho circuit
- **Chứa**: All intermediate circuit values  
- **Khi nào cần**: Chỉ ở bước generate proof
- **Gửi đi**: ❌ KHÔNG (chứa private computations)

### **3. proof.json** ⭐ **NHÚNG VÀO ẢNH**
- **Vai trò**: ZK proof elements
- **Chứa**: π_a, π_b, π_c (Groth16 proof)
- **Khi nào cần**: Verification
- **Gửi đi**: ✅ CÓ - NHƯNG GIẤU TRONG ẢNH

### **4. public.json** ⭐ **VẪN CẦN GỬI CÔNG KHAI**
- **Vai trò**: Public inputs cho verification
- **Chứa**: slots[], message[] (public data)  
- **Khi nào cần**: Verification
- **Gửi đi**: ✅ CÓ - CÔNG KHAI (không cần giấu)

---

## 🔄 **Workflow chi tiết:**

### **PROVER SIDE (Alice):**
```bash
# Bước 1: Generate all ZK files
snarkjs groth16 prove circuit.zkey witness.wtns proof.json public.json

# Bước 2: Embed chỉ proof.json vào ảnh
python3 src/zk_stego/embed_proof.py cover.png stego.png proof.json

# Bước 3: Gửi cho verifier
# ✅ GỬI: stego.png (chứa proof)
# ✅ GỬI: public.json (công khai)
# ❌ KHÔNG GỬI: input.json, witness.wtns (private)
```

### **VERIFIER SIDE (Bob):**
```bash
# Bước 1: Nhận stego.png + public.json
# Bước 2: Extract proof từ ảnh
python3 src/zk_stego/extract_proof.py stego.png proof_extracted.json

# Bước 3: Verify với CẢ HAI file
snarkjs groth16 verify verification_key.json public.json proof_extracted.json
                                         ^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^
                                         PUBLIC       EXTRACTED FROM IMAGE
```

---

## ❓ **Tại sao KHÔNG thể bỏ public.json?**

### **Verification command yêu cầu:**
```bash
snarkjs groth16 verify <verification_key> <public_inputs> <proof>
```

- **verification_key.json**: Setup once, can be public
- **public.json**: Public inputs, MUST match circuit's public signals  
- **proof.json**: Proof elements, can be hidden in image

### **Nếu bỏ public.json:**
```bash
snarkjs groth16 verify verification_key.json ??? proof_extracted.json
                                           ^^^
                                           CẦN GÌ Ở ĐÂY?
```

**Verifier không biết:**
- Circuit expect public inputs nào?
- Slots values là gì?
- Message values để verify là gì?

---

## 🎯 **Kết luận:**

### **NHÚNG VÀO ẢNH:**
- ✅ **proof.json** - Mathematical proof (có thể muốn giấu)

### **GỬI CÔNG KHAI:**
- ✅ **public.json** - Public inputs (không cần giấu, verifier phải biết)
- ✅ **verification_key.json** - Verification key (public, setup once)

### **KHÔNG GỬI:**
- ❌ **input.json** - Chứa private inputs
- ❌ **witness.wtns** - Chứa private computations

---

## 💡 **Innovation của project:**

**Trước:**
```
Alice → [proof.json + public.json] → Bob
```

**Sau:**
```
Alice → [stego.png (contains proof.json) + public.json] → Bob
```

**Lợi ích:**
- Proof được giấu trong ảnh (covert transmission)
- Public inputs vẫn được gửi bình thường (không cần giấu)
- Verification process không thay đổi

---

## 🔍 **Tóm tắt:**

**public.json VẪN CẦN THIẾT** vì:
1. snarkjs verify command requires it
2. Verifier cần biết public inputs để verify
3. Không phải secret data nên không cần giấu
4. Chỉ có proof.json được nhúng vào ảnh (để covert transmission)

**Steganography chỉ giấu proof, KHÔNG thay đổi ZK verification logic!**