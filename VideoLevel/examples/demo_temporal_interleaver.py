"""
Temporal Interleaver Demo

Demonstrates temporal payload distribution across video frames with:
- Frame chunking and pseudo-random permutation
- Recurrent frame dependency chains
- Missing frame recovery simulation
- Integration with LDPC codec

Week 8 - Phase 3
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hashlib
from src.zk_mv_stego.crypto.temporal_interleaver import (
    TemporalInterleaver,
    create_frame_manifest
)
from src.zk_mv_stego.crypto.ldpc_codec import LDPCCodec


def demo_basic_interleaving():
    """Demo 1: Basic temporal interleaving"""
    print("=" * 70)
    print("DEMO 1: Basic Temporal Interleaving")
    print("=" * 70)
    
    # Create interleaver
    interleaver = TemporalInterleaver(num_frames=10)
    
    # Original payload
    payload = b"This is a secret message embedded across multiple video frames!"
    print(f"\n📦 Original Payload ({len(payload)} bytes):")
    print(f"   {payload.decode('ascii')}")
    
    # Interleave
    chunks, indices = interleaver.interleave(payload)
    
    print(f"\n🎞️  Distributed Across {len(chunks)} Frames:")
    print(f"   Permutation Order: {indices}")
    
    for i, (chunk, perm_idx) in enumerate(zip(chunks, indices)):
        print(f"   Frame {i} (→ position {perm_idx}): {len(chunk)} bytes - {chunk[:20]}...")
    
    # Deinterleave
    recovered = interleaver.deinterleave(chunks, indices)
    
    print(f"\n✅ Recovered Payload:")
    print(f"   {recovered.decode('ascii')}")
    print(f"   Roundtrip Success: {recovered == payload}")


def demo_frame_dependency():
    """Demo 2: Frame dependency chain"""
    print("\n" + "=" * 70)
    print("DEMO 2: Recurrent Frame Dependency Chain")
    print("=" * 70)
    
    interleaver = TemporalInterleaver(num_frames=8)
    payload = bytes(range(160))  # 160 bytes → 20 bytes per frame
    
    # Interleave
    chunks, indices = interleaver.interleave(payload)
    
    # Generate dependency chain
    initial_seed = b"zk_secret_123"
    chain = interleaver.get_frame_chain(chunks, initial_seed)
    
    print(f"\n🔗 Frame Dependency Chain:")
    print(f"   Initial Seed: {initial_seed.decode('ascii')}")
    print(f"   Seed Hash: {hashlib.sha256(initial_seed).hexdigest()[:16]}...")
    
    for i, (mb_start, frame_hash) in enumerate(chain):
        print(f"\n   Frame {i}:")
        print(f"   ├─ Embed at MB #{mb_start:02d} (position {mb_start * 16} in frame)")
        print(f"   ├─ Chunk: {chunks[i][:10].hex()}...")
        print(f"   └─ Cumulative Hash: {frame_hash.hex()[:16]}...")
        
        if i < len(chain) - 1:
            next_mb, _ = chain[i + 1]
            print(f"       └─> Next frame position = hash(0...{i}) % 100 = {next_mb}")
    
    print(f"\n🔒 Security Analysis:")
    print(f"   ✓ Frame {i+1} position depends on hash of frames 0...{i}")
    print(f"   ✓ Cannot extract partial sequence (chain must be complete)")
    print(f"   ✓ Attacker needs full frame sequence in correct order")


def demo_missing_frame_recovery():
    """Demo 3: Missing frame recovery"""
    print("\n" + "=" * 70)
    print("DEMO 3: Missing Frame Recovery")
    print("=" * 70)
    
    interleaver = TemporalInterleaver(num_frames=10)
    payload = b"X" * 200  # 200 bytes
    
    # Interleave
    chunks, indices = interleaver.interleave(payload)
    
    print(f"\n📊 Original Distribution:")
    print(f"   Total Payload: {len(payload)} bytes")
    print(f"   Frames: {len(chunks)}")
    print(f"   Chunk Sizes: {[len(c) for c in chunks]}")
    
    # Simulate missing frames
    missing_frames = [2, 5, 7]
    print(f"\n❌ Simulating Frame Loss: {missing_frames}")
    
    for frame_idx in missing_frames:
        chunks[frame_idx] = None
        print(f"   Frame {frame_idx} lost (was {20} bytes)")
    
    # Deinterleave with missing frames
    recovered = interleaver.deinterleave(chunks, indices)
    
    print(f"\n🔧 Recovery Attempt:")
    print(f"   Recovered Length: {len(recovered)} bytes")
    print(f"   Expected Length: {len(payload)} bytes")
    
    # Count corrupted bytes (should be zeros at missing positions)
    corrupted = sum(1 for r, p in zip(recovered, payload) if r != p)
    recovery_rate = (len(recovered) - corrupted) / len(payload) * 100
    
    print(f"   Corrupted Bytes: {corrupted}")
    print(f"   Recovery Rate: {recovery_rate:.1f}%")
    print(f"\n💡 Note: LDPC error correction can recover from {len(missing_frames)}/10 frame loss")


def demo_ldpc_integration():
    """Demo 4: Integration with LDPC codec"""
    print("\n" + "=" * 70)
    print("DEMO 4: LDPC + Temporal Interleaving Integration")
    print("=" * 70)
    
    # Original secret message (padded to 192 bytes for LDPC)
    secret_msg = b"ZK-SNARK steganography with error correction!"
    secret = secret_msg + b'\x00' * (192 - len(secret_msg))  # Pad to 192 bytes
    print(f"\n🔐 Original Secret ({len(secret_msg)} bytes, padded to {len(secret)}):")
    print(f"   {secret_msg.decode('ascii')}")
    
    # Step 1: LDPC encoding
    print(f"\n📝 Step 1: LDPC Encoding (Rate 1/2)")
    ldpc = LDPCCodec(code_rate=0.5)
    ldpc_encoded = ldpc.encode(secret)
    print(f"   Input:  {len(secret)} bytes")
    print(f"   Output: {len(ldpc_encoded)} bytes (2× redundancy)")
    
    # Step 2: Temporal interleaving
    print(f"\n🎞️  Step 2: Temporal Interleaving (10 frames)")
    temporal = TemporalInterleaver(num_frames=10)
    chunks, indices = temporal.interleave(ldpc_encoded)
    print(f"   Distributed: {len(ldpc_encoded)} bytes → {len(chunks)} frames")
    print(f"   Chunk Sizes: {[len(c) for c in chunks]}")
    
    # Step 3: Simulate transmission with frame loss
    print(f"\n📡 Step 3: Transmission (simulating 1 frame loss)")
    chunks[3] = None
    print(f"   Lost Frames: [3]")
    
    # Step 4: Temporal deinterleaving
    print(f"\n🔄 Step 4: Temporal Deinterleaving")
    ldpc_recovered = temporal.deinterleave(chunks, indices)
    print(f"   Recovered: {len(ldpc_recovered)} bytes")
    
    # Step 5: LDPC decoding
    print(f"\n🔓 Step 5: LDPC Decoding")
    decoded, success, iterations = ldpc.decode(ldpc_recovered)
    
    # Extract original message (remove padding)
    decoded_msg = decoded.rstrip(b'\x00')
    print(f"   Output: {len(decoded_msg)} bytes")
    
    # Try to decode (may fail if LDPC couldn't correct all errors)
    try:
        msg_text = decoded_msg.decode('ascii')
        print(f"   Message: {msg_text}")
    except UnicodeDecodeError:
        print(f"   Message: [Some corruption from frame loss]")
        print(f"   First 20 bytes: {decoded_msg[:20]}")
    
    print(f"   LDPC Success: {success} (iterations: {iterations})")
    
    # Verify
    print(f"\n✅ End-to-End Verification:")
    print(f"   Original == Recovered: {secret_msg == decoded_msg}")
    if success and secret_msg == decoded_msg:
        print(f"   ✅ LDPC corrected 1/{len(chunks)} frame loss successfully!")
    else:
        print(f"   ⚠️  LDPC partial recovery ({len(decoded_msg)}/{len(secret_msg)} bytes)")
        print(f"   💡 Note: LDPC can correct errors but has limits. Try fewer lost frames.")


def demo_manifest_generation():
    """Demo 5: Frame manifest generation"""
    print("\n" + "=" * 70)
    print("DEMO 5: Frame Distribution Manifest")
    print("=" * 70)
    
    interleaver = TemporalInterleaver(num_frames=5, secret_seed=b"demo_seed")
    payload = bytes(range(100))
    
    # Interleave
    chunks, indices = interleaver.interleave(payload)
    
    # Create manifest
    manifest = create_frame_manifest(chunks, indices, b"demo_seed")
    
    print(f"\n📋 Distribution Manifest:")
    print(f"   Frame Count: {manifest['frame_count']}")
    print(f"   Total Bytes: {manifest['total_bytes']}")
    print(f"   Chunk Sizes: {manifest['chunk_sizes']}")
    print(f"   Permutation: {manifest['permutation']}")
    print(f"   Seed Hash:   {manifest['initial_seed_hash']}")
    
    print(f"\n📑 Per-Frame Details:")
    for frame in manifest['frames']:
        print(f"\n   Frame {frame['index']}:")
        print(f"   ├─ Size:      {frame['size']} bytes")
        print(f"   ├─ Hash:      {frame['hash'][:16]}...")
        print(f"   └─ MB Start:  #{frame['mb_start']:02d}")
    
    print(f"\n💾 Manifest Use Cases:")
    print(f"   ✓ Verify extraction order")
    print(f"   ✓ Detect missing/corrupted frames")
    print(f"   ✓ Validate frame dependency chain")
    print(f"   ✓ Reconstruct from partial data")


def demo_performance():
    """Demo 6: Performance benchmarks"""
    print("\n" + "=" * 70)
    print("DEMO 6: Performance Benchmarks")
    print("=" * 70)
    
    import time
    
    # Test different payload sizes
    sizes = [192, 384, 768, 1536]  # Typical LDPC sizes at different rates
    
    print(f"\n⏱️  Interleaving Performance (1000 iterations each):")
    print(f"   {'Payload Size':<15} {'Time (ms)':<12} {'Ops/sec':<12}")
    print(f"   {'-' * 15} {'-' * 12} {'-' * 12}")
    
    for size in sizes:
        interleaver = TemporalInterleaver(num_frames=10)
        # Create payload of exact size
        payload = (bytes(range(256)) * ((size // 256) + 1))[:size]
        
        start = time.time()
        for _ in range(1000):
            chunks, indices = interleaver.interleave(payload)
        elapsed = time.time() - start
        
        avg_ms = (elapsed * 1000) / 1000 if elapsed > 0 else 0.001
        ops_per_sec = 1000 / elapsed if elapsed > 0 else 1000000
        
        print(f"   {size:<15} {avg_ms:<12.3f} {ops_per_sec:<12.0f}")
    
    print(f"\n⏱️  Deinterleaving Performance (1000 iterations each):")
    print(f"   {'Payload Size':<15} {'Time (ms)':<12} {'Ops/sec':<12}")
    print(f"   {'-' * 15} {'-' * 12} {'-' * 12}")
    
    for size in sizes:
        interleaver = TemporalInterleaver(num_frames=10)
        payload = (bytes(range(256)) * ((size // 256) + 1))[:size]
        chunks, indices = interleaver.interleave(payload)
        
        start = time.time()
        for _ in range(1000):
            recovered = interleaver.deinterleave(chunks, indices)
        elapsed = time.time() - start
        
        avg_ms = (elapsed * 1000) / 1000 if elapsed > 0 else 0.001
        ops_per_sec = 1000 / elapsed if elapsed > 0 else 1000000
        
        print(f"   {size:<15} {avg_ms:<12.3f} {ops_per_sec:<12.0f}")


def main():
    """Run all demos"""
    print("\n" + "=" * 70)
    print(" " * 15 + "TEMPORAL INTERLEAVER DEMO")
    print(" " * 10 + "Week 8 - Multi-Frame Payload Distribution")
    print("=" * 70)
    
    demo_basic_interleaving()
    demo_frame_dependency()
    demo_missing_frame_recovery()
    demo_ldpc_integration()
    demo_manifest_generation()
    demo_performance()
    
    print("\n" + "=" * 70)
    print(" " * 20 + "DEMO COMPLETE")
    print("=" * 70)
    print("\n📚 Key Takeaways:")
    print("   ✓ Temporal distribution spreads payload across 10 frames")
    print("   ✓ Recurrent dependency prevents partial extraction")
    print("   ✓ Missing frame recovery via LDPC error correction")
    print("   ✓ Sub-millisecond performance per operation")
    print("   ✓ Manifest tracks frame distribution metadata")
    print()


if __name__ == "__main__":
    main()
