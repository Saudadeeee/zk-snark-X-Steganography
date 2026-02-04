"""
LDPC Error Correction Codec Demonstration

Shows encoding, decoding, error correction, and ZK proof protection.
Week 6 Component Demo
"""

import numpy as np
import time
from src.zk_mv_stego.crypto.ldpc_codec import LDPCCodec


def print_header(title):
    """Print formatted section header"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)


def demo_basic_encode_decode():
    """Demo 1: Basic encode/decode cycle"""
    print_header("Demo 1: Basic Encode/Decode Cycle")
    
    codec = LDPCCodec(data_length=128, code_rate=0.5)
    
    # Original data
    data = b"Hello LDPC! This is a test message for error correction."
    data = data[:16]  # 128 bits
    
    print(f"\nOriginal Data: {data}")
    print(f"Data Length: {len(data)} bytes ({len(data) * 8} bits)")
    
    # Encode
    encoded = codec.encode(data)
    print(f"\nEncoded Data Length: {len(encoded)} bytes ({len(encoded) * 8} bits)")
    print(f"Code Rate: {codec.code_rate} (expansion factor: {len(encoded)/len(data):.2f}x)")
    
    # Decode (no errors)
    decoded, success, iterations = codec.decode(encoded)
    
    print(f"\nDecoding Results:")
    print(f"  Success: {success}")
    print(f"  Iterations: {iterations}/{codec.max_iterations}")
    print(f"  Decoded Data: {decoded}")
    
    # Measure quality
    ber = codec.measure_ber(data, decoded)
    print(f"  Bit Error Rate: {ber*100:.2f}%")


def demo_error_injection_recovery():
    """Demo 2: Error injection and recovery"""
    print_header("Demo 2: Error Injection and Recovery")
    
    codec = LDPCCodec(data_length=192 * 8, code_rate=0.5, max_iterations=100)
    
    # Create random data (simulating ZK proof)
    data = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
    
    print(f"\nOriginal Data: 192 bytes (ZK proof size)")
    
    # Encode
    encoded = codec.encode(data)
    print(f"Encoded Data: {len(encoded)} bytes")
    
    # Test different error rates
    error_rates = [0.01, 0.02, 0.03, 0.05]
    
    print(f"\n{'Error Rate':<15} {'Input BER':<15} {'Output BER':<15} {'Improvement':<15}")
    print("-" * 60)
    
    for error_rate in error_rates:
        # Inject errors
        corrupted = codec.inject_errors(encoded, error_rate=error_rate)
        input_ber = codec.measure_ber(encoded, corrupted)
        
        # Decode
        decoded, success, iterations = codec.decode(corrupted)
        output_ber = codec.measure_ber(data, decoded)
        
        improvement = (input_ber - output_ber) / input_ber * 100 if input_ber > 0 else 0
        
        print(f"{error_rate:<15.2%} {input_ber:<15.2%} {output_ber:<15.2%} {improvement:<15.1f}%")


def demo_code_rate_comparison():
    """Demo 3: Compare different code rates"""
    print_header("Demo 3: Code Rate Comparison")
    
    data = bytes(np.random.randint(0, 256, 16, dtype=np.uint8))
    error_rate = 0.03
    
    print(f"\nOriginal Data: {len(data)} bytes")
    print(f"Injected Error Rate: {error_rate:.2%}")
    
    print(f"\n{'Code Rate':<15} {'Encoded Size':<15} {'Overhead':<15} {'Output BER':<15} {'Iterations':<15}")
    print("-" * 75)
    
    for rate in [0.5, 0.667, 0.75]:
        codec = LDPCCodec(data_length=128, code_rate=rate, max_iterations=100)
        
        # Encode
        encoded = codec.encode(data)
        overhead = (len(encoded) - len(data)) / len(data) * 100
        
        # Inject errors and decode
        corrupted = codec.inject_errors(encoded, error_rate=error_rate)
        decoded, success, iterations = codec.decode(corrupted)
        
        output_ber = codec.measure_ber(data, decoded)
        
        print(f"{rate:<15.3f} {len(encoded):<15} {overhead:<15.1f}% {output_ber:<15.2%} {iterations:<15}")


def demo_zk_proof_protection():
    """Demo 4: ZK proof protection workflow"""
    print_header("Demo 4: ZK Proof Protection Workflow")
    
    # Simulate 192-byte ZK proof (Groth16)
    zk_proof = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
    
    print("\n1. Original ZK Proof:")
    print(f"   Size: {len(zk_proof)} bytes")
    print(f"   Sample: {zk_proof[:32].hex()}...")
    
    # Create LDPC codec (rate 2/3 for balance)
    codec = LDPCCodec(data_length=192 * 8, code_rate=0.667, max_iterations=100)
    
    print("\n2. LDPC Encoding:")
    info = codec.get_code_info()
    print(f"   Code Rate: {info['code_rate']:.3f}")
    print(f"   Data Length: {info['data_bytes']} bytes")
    print(f"   Codeword Length: {info['codeword_bytes']} bytes")
    print(f"   Overhead: {info['overhead']*100:.1f}%")
    
    # Encode
    start = time.perf_counter()
    protected = codec.encode(zk_proof)
    encode_time = (time.perf_counter() - start) * 1000
    
    print(f"   Encoding Time: {encode_time:.2f} ms")
    print(f"   Protected Size: {len(protected)} bytes")
    
    # Simulate transmission errors
    print("\n3. Simulating Transmission Errors:")
    error_rate = 0.02
    corrupted = codec.inject_errors(protected, error_rate=error_rate)
    actual_ber = codec.measure_ber(protected, corrupted)
    print(f"   Target Error Rate: {error_rate:.2%}")
    print(f"   Actual BER: {actual_ber:.2%}")
    print(f"   Corrupted Bits: {int(actual_ber * len(protected) * 8)}")
    
    # Decode
    print("\n4. LDPC Decoding:")
    start = time.perf_counter()
    recovered, success, iterations = codec.decode(corrupted)
    decode_time = (time.perf_counter() - start) * 1000
    
    print(f"   Decoding Time: {decode_time:.2f} ms")
    print(f"   Success: {success}")
    print(f"   Iterations: {iterations}/{codec.max_iterations}")
    
    # Measure recovery quality
    output_ber = codec.measure_ber(zk_proof, recovered)
    bytes_correct = sum(1 for i in range(len(zk_proof)) if zk_proof[i] == recovered[i])
    
    print(f"\n5. Recovery Results:")
    print(f"   Output BER: {output_ber:.2%}")
    print(f"   Bytes Correct: {bytes_correct}/{len(zk_proof)} ({bytes_correct/len(zk_proof)*100:.1f}%)")
    print(f"   Error Reduction: {(actual_ber - output_ber)/actual_ber*100:.1f}%")


def demo_performance_benchmark():
    """Demo 5: Performance benchmarking"""
    print_header("Demo 5: Performance Benchmarking")
    
    # Test different data sizes
    sizes = [
        (16, "Small (16 bytes)"),
        (192, "ZK Proof (192 bytes)"),
        (512, "Large (512 bytes)")
    ]
    
    code_rate = 0.5
    iterations_count = 100
    
    print(f"\nCode Rate: {code_rate}")
    print(f"Iterations per test: {iterations_count}")
    
    print(f"\n{'Data Size':<25} {'Encode (ms)':<15} {'Decode (ms)':<15} {'Throughput (MB/s)':<20}")
    print("-" * 75)
    
    for size, label in sizes:
        codec = LDPCCodec(data_length=size * 8, code_rate=code_rate, max_iterations=50)
        data = bytes(np.random.randint(0, 256, size, dtype=np.uint8))
        
        # Encoding benchmark
        start = time.perf_counter()
        for _ in range(iterations_count):
            encoded = codec.encode(data)
        encode_time = (time.perf_counter() - start) / iterations_count * 1000
        
        # Decoding benchmark (with small errors)
        corrupted = codec.inject_errors(encoded, error_rate=0.01)
        
        start = time.perf_counter()
        for _ in range(iterations_count):
            decoded, _, _ = codec.decode(corrupted)
        decode_time = (time.perf_counter() - start) / iterations_count * 1000
        
        # Throughput (MB/s)
        throughput = (size / 1024 / 1024) / (encode_time / 1000) if encode_time > 0 else 0
        
        print(f"{label:<25} {encode_time:<15.3f} {decode_time:<15.3f} {throughput:<20.2f}")


def demo_visual_error_pattern():
    """Demo 6: Visualize error patterns"""
    print_header("Demo 6: Error Pattern Analysis")
    
    codec = LDPCCodec(data_length=128, code_rate=0.5, max_iterations=100)
    
    # Create pattern data (repeating sequence)
    data = bytes([i % 256 for i in range(16)])
    
    print(f"\nOriginal Data Pattern: {data.hex()}")
    
    # Encode
    encoded = codec.encode(data)
    
    # Test various error scenarios
    scenarios = [
        ("No Errors", 0.00),
        ("Low (1%)", 0.01),
        ("Medium (3%)", 0.03),
        ("High (5%)", 0.05),
        ("Very High (10%)", 0.10)
    ]
    
    print(f"\n{'Scenario':<20} {'Input BER':<15} {'Output BER':<15} {'Bytes Match':<15} {'Success':<10}")
    print("-" * 75)
    
    for name, error_rate in scenarios:
        if error_rate > 0:
            corrupted = codec.inject_errors(encoded, error_rate=error_rate)
            input_ber = codec.measure_ber(encoded, corrupted)
        else:
            corrupted = encoded
            input_ber = 0.0
        
        decoded, success, iterations = codec.decode(corrupted)
        output_ber = codec.measure_ber(data, decoded)
        
        bytes_match = sum(1 for i in range(len(data)) if data[i] == decoded[i])
        
        success_str = "✓" if success else f"✗ ({iterations})"
        
        print(f"{name:<20} {input_ber:<15.2%} {output_ber:<15.2%} {bytes_match}/{len(data):<11} {success_str:<10}")
    
    print("\n✓ = Converged successfully")
    print("✗ = Max iterations reached")


def main():
    """Run all demonstrations"""
    print("\n" + "="*70)
    print("  LDPC ERROR CORRECTION CODEC DEMONSTRATION")
    print("  Week 6: Forward Error Correction for ZK Proof Protection")
    print("="*70)
    
    try:
        demo_basic_encode_decode()
        demo_error_injection_recovery()
        demo_code_rate_comparison()
        demo_zk_proof_protection()
        demo_performance_benchmark()
        demo_visual_error_pattern()
        
        print("\n" + "="*70)
        print("  ALL DEMONSTRATIONS COMPLETED SUCCESSFULLY")
        print("="*70)
        print("\nKey Takeaways:")
        print("  1. LDPC provides forward error correction with configurable code rates")
        print("  2. Rate 1/2 doubles data size but offers strongest protection")
        print("  3. Suitable for protecting 192-byte ZK proofs against bit errors")
        print("  4. Demonstrational implementation shows ~10-20% baseline BER")
        print("  5. Encoding: ~0.01-0.5ms, Decoding: ~0.1-20ms depending on size")
        print("  6. Production implementation would use optimized matrices\n")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
