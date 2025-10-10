# Tại sao ZK-SNARK vẫn cần Public Inputs?

## 🤔 **Câu hỏi của bạn:**
> "Tại sao không thể chỉ embed proof vào ảnh, sau đó verifier extract và verify → True/False?"

## 🔍 **Trả lời:**

### **ZK-SNARK không hoạt động như chữ ký số!**

**Chữ ký số:**
```
verify(message, signature, public_key) → True/False
```

**ZK-SNARK:**
```
verify(verification_key, public_inputs, proof) → True/False
```

### **Tại sao cần public_inputs?**

1. **ZK-SNARK chứng minh một statement:**
   - "Tôi biết x sao cho f(x, public_data) = true"
   - Verifier cần biết `public_data` để hiểu statement

2. **Ví dụ cụ thể:**
   ```
   Statement: "Tôi biết secret sao cho hash(secret) = 15129"
   ```
   - `secret` = private (prover biết, verifier không biết)
   - `15129` = public (verifier phải biết để verify)

## 📋 **Workflow comparison:**

### **Mong muốn của bạn (KHÔNG thể với ZK-SNARK):**
```
Alice: [secret] → generate_proof() → embed_in_image() → send_image()
Bob: extract_proof() → verify() → True/False
```

### **ZK-SNARK thực tế:**
```
Alice: [secret, public_target] → generate_proof() → embed_proof() → send_image() + send_public_target()
Bob: extract_proof() + receive_public_target() → verify() → True/False
```

## 💡 **Giải pháp cho mong muốn của bạn:**

### **Option 1: Fixed Public Input**
```circom
template AlwaysValid() {
    signal private input secret;
    signal output valid;
    
    // Any secret works, just prove you have one
    signal dummy;
    dummy <== secret * secret;
    valid <== 1;  // Always true
}
```

**Public input:** `[]` (empty)
**Verifier chỉ cần:** `verify(vkey, [], proof) → True/False`

### **Option 2: Predetermined Challenge**
```circom
template KnowsSecretFor42() {
    signal private input secret;
    signal output valid;
    
    // Hardcoded: prove you know secret where secret^2 = 42^2
    signal target;
    target <== 42 * 42;  // 1764
    
    secret * secret === target;
    valid <== 1;
}
```

**Public input:** `[]` (empty, target hardcoded)
**Statement:** "Prover knows square root of 1764"

## 🚀 **Let's implement Option 1:**

### **Ultra Simple Circuit:**