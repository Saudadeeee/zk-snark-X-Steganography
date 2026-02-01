"""
Validate all improvements to the ZK-SNARK video steganography system

Tests:
1. LSB extraction consistency (sign bit vs LSB)
2. High-capacity mode (allow_small_values)
3. End-to-end workflow with embed_complete.py

Author: ZK Video Stego Team
Date: February 2, 2026
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_lsb_consistency():
    """Test that embedding and extraction use consistent LSB method"""
    print("="*80)
    print("TEST 1: LSB Extraction Consistency")
    print("="*80)
    
    from zk_mv_stego.embedder.payload_embedder import PayloadEmbedder
    
    # Test coefficients
    test_coeffs = [
        (0, 0, [0, 4, -5, 2, -3, 0, 6, -7, 0, 0, 0, 0, 0, 0, 0, 0])
    ]
    
    # Embed payload
    embedder = PayloadEmbedder(skip_dc=True, skip_zeros=True)
    payload = b'\xAA'  # Binary: 10101010
    
    print(f"\n1. Original coefficients: {test_coeffs[0][2]}")
    print(f"2. Payload to embed: {payload.hex()} (binary: {bin(payload[0])[2:].zfill(8)})")
    
    # Embed
    modified_coeffs, bits_embedded = embedder.embed_payload(test_coeffs, payload)
    print(f"3. Bits embedded: {bits_embedded}")
    print(f"4. Modified coefficients: {modified_coeffs[0][2]}")
    
    # Extract using embedder
    extracted_embedder = embedder.extract_payload(modified_coeffs, bits_embedded)
    print(f"\n5. Extracted by PayloadEmbedder: {extracted_embedder.hex()}")
    
    # Extract using manual LSB method (same as extract.py)
    bits = []
    for mb_idx, block_idx, coeffs in modified_coeffs:
        for i, coeff in enumerate(coeffs):
            if i == 0:  # Skip DC
                continue
            if coeff == 0:  # Skip zeros
                continue
            if abs(coeff) < 2:  # Skip ±1 (standard mode)
                continue
            
            # Extract LSB of absolute value
            lsb = abs(coeff) & 1
            bits.append(lsb)
            
            if len(bits) >= bits_embedded:
                break
        if len(bits) >= bits_embedded:
            break
    
    # Convert bits to bytes
    extracted_manual = bytearray()
    for i in range(0, len(bits), 8):
        byte_bits = bits[i:i+8]
        if len(byte_bits) < 8:
            byte_bits.extend([0] * (8 - len(byte_bits)))
        byte_val = sum(bit << (7 - j) for j, bit in enumerate(byte_bits))
        extracted_manual.append(byte_val)
    
    print(f"6. Extracted by manual LSB: {bytes(extracted_manual).hex()}")
    
    # Verify consistency
    if extracted_embedder == extracted_manual == payload:
        print(f"\n✅ TEST PASSED: LSB extraction is consistent!")
        print(f"   - PayloadEmbedder: {extracted_embedder.hex()}")
        print(f"   - Manual LSB:      {bytes(extracted_manual).hex()}")
        print(f"   - Original:        {payload.hex()}")
        return True
    else:
        print(f"\n❌ TEST FAILED: LSB extraction inconsistent!")
        print(f"   - PayloadEmbedder: {extracted_embedder.hex()}")
        print(f"   - Manual LSB:      {bytes(extracted_manual).hex()}")
        print(f"   - Original:        {payload.hex()}")
        return False


def test_high_capacity_mode():
    """Test high-capacity mode with allow_small_values"""
    print("\n" + "="*80)
    print("TEST 2: High-Capacity Mode")
    print("="*80)
    
    from zk_mv_stego.embedder.payload_embedder import PayloadEmbedder
    
    # Coefficients with ±1 values
    test_coeffs = [
        (0, 0, [0, 4, -5, 2, -3, 1, 6, -7, -1, 1, 0, 0, 0, 0, 0, 0]),
        (0, 1, [0, 2, -1, 1, -3, 4, -2, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    ]
    
    print(f"\nCoefficients block 0: {test_coeffs[0][2]}")
    print(f"Coefficients block 1: {test_coeffs[1][2]}")
    
    # Standard mode
    embedder_std = PayloadEmbedder(skip_dc=True, skip_zeros=True, allow_small_values=False)
    capacity_std = embedder_std.calculate_capacity(test_coeffs)
    
    # High-capacity mode
    embedder_hc = PayloadEmbedder(skip_dc=True, skip_zeros=True, allow_small_values=True)
    capacity_hc = embedder_hc.calculate_capacity(test_coeffs)
    
    print(f"\n1. Standard mode capacity: {capacity_std} bits")
    print(f"2. High-capacity mode capacity: {capacity_hc} bits")
    print(f"3. Capacity increase: {capacity_hc - capacity_std} bits ({(capacity_hc/capacity_std - 1)*100:.1f}%)")
    
    if capacity_hc > capacity_std:
        print(f"\n✅ TEST PASSED: High-capacity mode increases capacity!")
        print(f"   Standard: {capacity_std} bits")
        print(f"   High-cap: {capacity_hc} bits")
        return True
    else:
        print(f"\n❌ TEST FAILED: High-capacity mode did not increase capacity")
        return False


def test_coefficient_modification():
    """Test coefficient LSB modification preserves sign"""
    print("\n" + "="*80)
    print("TEST 3: Coefficient LSB Modification")
    print("="*80)
    
    from zk_mv_stego.embedder.payload_embedder import PayloadEmbedder
    
    embedder = PayloadEmbedder()
    
    test_cases = [
        (4, 0, 4),    # Positive, embed 0, stay positive
        (4, 1, 5),    # Positive, embed 1, stay positive
        (-5, 0, -4),  # Negative, embed 0, stay negative
        (-5, 1, -5),  # Negative, embed 1, stay negative
        (2, 0, 2),    # Small positive, embed 0
        (2, 1, 3),    # Small positive, embed 1
        (-3, 0, -2),  # Small negative, embed 0
        (-3, 1, -3),  # Small negative, embed 1
    ]
    
    print("\nCoefficient LSB modification tests:")
    print(f"{'Original':<10} {'Bit':<5} {'Expected':<10} {'Result':<10} {'Status'}")
    print("-" * 60)
    
    all_passed = True
    for orig, bit, expected in test_cases:
        result = embedder._modify_lsb(orig, bit)
        status = "✅" if result == expected else "❌"
        print(f"{orig:<10} {bit:<5} {expected:<10} {result:<10} {status}")
        
        # Check sign preservation
        if (orig > 0 and result <= 0) or (orig < 0 and result >= 0):
            print(f"  ⚠️  Sign changed! {orig} → {result}")
            all_passed = False
        
        # Check LSB
        if (abs(result) & 1) != bit:
            print(f"  ⚠️  LSB incorrect! Expected {bit}, got {abs(result) & 1}")
            all_passed = False
        
        if result != expected:
            all_passed = False
    
    if all_passed:
        print(f"\n✅ TEST PASSED: All coefficient modifications correct!")
        return True
    else:
        print(f"\n❌ TEST FAILED: Some coefficient modifications incorrect")
        return False


def test_embedding_extraction_roundtrip():
    """Test complete embedding → extraction roundtrip"""
    print("\n" + "="*80)
    print("TEST 4: Embedding → Extraction Roundtrip")
    print("="*80)
    
    from zk_mv_stego.embedder.payload_embedder import PayloadEmbedder
    
    # Create test coefficients (larger dataset)
    test_coeffs = []
    for mb_idx in range(5):
        for block_idx in range(6):
            coeffs = [0]  # DC
            # Add mix of coefficients
            for i in range(15):
                if i % 3 == 0:
                    coeffs.append(0)  # Zeros
                elif i % 3 == 1:
                    coeffs.append((i + mb_idx * 16 + block_idx) % 10 + 2)  # Positive
                else:
                    coeffs.append(-((i + mb_idx * 16 + block_idx) % 10 + 2))  # Negative
            test_coeffs.append((mb_idx, block_idx, coeffs))
    
    print(f"\n1. Created {len(test_coeffs)} test blocks")
    
    # Test payloads
    test_payloads = [
        b"Hello",
        b"Testing 123",
        b"\x00\xFF\xAA\x55",
        bytes(range(32))
    ]
    
    results = []
    for payload in test_payloads:
        # Standard mode
        embedder_std = PayloadEmbedder(skip_dc=True, skip_zeros=True, allow_small_values=False)
        capacity_std = embedder_std.calculate_capacity(test_coeffs)
        
        if len(payload) * 8 > capacity_std:
            print(f"\n⚠️  Skipping payload (too large): {len(payload)} bytes > {capacity_std//8} bytes capacity")
            continue
        
        # Embed
        modified_coeffs, bits_embedded = embedder_std.embed_payload(test_coeffs, payload)
        
        # Extract
        extracted = embedder_std.extract_payload(modified_coeffs, bits_embedded)
        
        # Verify
        match = extracted == payload
        results.append(match)
        
        status = "✅" if match else "❌"
        print(f"\n{status} Payload: {payload.hex()[:40]}{'...' if len(payload) > 20 else ''}")
        print(f"   Embedded: {bits_embedded} bits")
        print(f"   Extracted: {extracted.hex()[:40]}{'...' if len(extracted) > 20 else ''}")
        print(f"   Match: {match}")
    
    if all(results):
        print(f"\n✅ TEST PASSED: All roundtrips successful! ({len(results)}/{len(results)})")
        return True
    else:
        print(f"\n❌ TEST FAILED: Some roundtrips failed ({sum(results)}/{len(results)})")
        return False


def main():
    """Run all validation tests"""
    print("\n" + "="*80)
    print("VALIDATING IMPROVEMENTS TO ZK-SNARK VIDEO STEGANOGRAPHY")
    print("="*80)
    print("\nTesting:")
    print("  1. LSB extraction consistency (sign bit vs LSB fix)")
    print("  2. High-capacity mode (allow_small_values)")
    print("  3. Coefficient LSB modification (sign preservation)")
    print("  4. Embedding → Extraction roundtrip")
    print("\n" + "="*80)
    
    results = {
        "LSB Consistency": test_lsb_consistency(),
        "High-Capacity Mode": test_high_capacity_mode(),
        "LSB Modification": test_coefficient_modification(),
        "Roundtrip": test_embedding_extraction_roundtrip()
    }
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:<30} {status}")
    
    print("="*80)
    
    if all(results.values()):
        print("\n🎉 ALL TESTS PASSED! Improvements validated successfully.")
        print("\nNext steps:")
        print("  1. Test with actual video: python embed_complete.py -i <video.h264> -m 'Test'")
        print("  2. Extract payload: python scripts/extract.py <stego_video.h264>")
        print("  3. Verify extraction matches original message")
        return 0
    else:
        failed = [name for name, passed in results.items() if not passed]
        print(f"\n⚠️  SOME TESTS FAILED: {', '.join(failed)}")
        print("\nPlease review the code changes and try again.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
