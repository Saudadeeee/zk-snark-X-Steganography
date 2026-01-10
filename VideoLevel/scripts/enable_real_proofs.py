#!/usr/bin/env python3
"""
Quick script to enable and test real ZK proofs

Run this to verify that real Groth16 proofs work correctly.
"""

import sys
import subprocess
import json
from pathlib import Path

def check_dependencies():
    """Check if Node.js and snarkjs are installed"""
    print("=" * 60)
    print("DEPENDENCY CHECK")
    print("=" * 60)
    
    # Check Node.js
    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True)
        node_version = result.stdout.strip()
        print(f"✅ Node.js: {node_version}")
        
        # Parse version
        major = int(node_version.replace('v', '').split('.')[0])
        if major < 14:
            print(f"⚠️  Warning: Node.js {node_version} is old. Recommend v14+")
    except FileNotFoundError:
        print("❌ Node.js NOT FOUND")
        print("   Install from: https://nodejs.org/")
        return False
    
    # Check snarkjs
    try:
        result = subprocess.run(['snarkjs', '--version'], capture_output=True, text=True)
        snarkjs_version = result.stdout.strip()
        print(f"✅ snarkjs: {snarkjs_version}")
    except FileNotFoundError:
        print("❌ snarkjs NOT FOUND")
        print("   Install: npm install -g snarkjs")
        return False
    
    return True


def check_circuits():
    """Verify ZK circuit files exist"""
    print("\n" + "=" * 60)
    print("CIRCUIT FILE CHECK")
    print("=" * 60)
    
    # Find circuit directory
    script_dir = Path(__file__).parent
    circuit_dir = script_dir.parent.parent / 'ImageLevel' / 'circuits' / 'compiled' / 'build'
    
    if not circuit_dir.exists():
        print(f"❌ Circuit directory not found: {circuit_dir}")
        return None
    
    print(f"📁 Circuit directory: {circuit_dir}")
    
    # Check required files
    required_files = {
        'WASM': 'chaos_zk_stego_js/chaos_zk_stego.wasm',
        'Proving Key': 'chaos_zk_stego.zkey',
        'Verification Key': 'verification_key.json',
        'Witness Generator': 'chaos_zk_stego_js/generate_witness.js'
    }
    
    all_found = True
    for name, filepath in required_files.items():
        full_path = circuit_dir / filepath
        if full_path.exists():
            size = full_path.stat().st_size
            print(f"✅ {name:20s}: {filepath} ({size:,} bytes)")
        else:
            print(f"❌ {name:20s}: NOT FOUND")
            all_found = False
    
    return circuit_dir if all_found else None


def test_real_proof():
    """Test generating a real Groth16 proof"""
    print("\n" + "=" * 60)
    print("TESTING REAL PROOF GENERATION")
    print("=" * 60)
    
    # Import prover
    sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
    from zk_mv_stego.prover import VideoProver
    
    # Find test video
    test_video = Path(__file__).parent.parent / 'tests' / 'data' / 'test_video.mp4'
    if not test_video.exists():
        # Try to find any MP4 in the project
        for video in Path(__file__).parent.parent.rglob('*.mp4'):
            test_video = video
            break
    
    if not test_video.exists():
        print("❌ No test video found")
        print("   Please provide a test H.264 video in tests/data/")
        return False
    
    print(f"📹 Test video: {test_video}")
    
    # Create output directory
    output_dir = Path(__file__).parent.parent / 'output'
    output_dir.mkdir(exist_ok=True)
    output_json = output_dir / 'real_proof_test.json'
    
    # Initialize prover with circuit directory
    circuit_dir = Path(__file__).parent.parent.parent / 'ImageLevel' / 'circuits' / 'compiled' / 'build'
    
    print(f"\n[1] Initializing VideoProver...")
    try:
        prover = VideoProver(circuit_dir=str(circuit_dir))
        print(f"    ✅ Prover initialized")
    except Exception as e:
        print(f"    ❌ Failed: {e}")
        return False
    
    # Generate proof
    print(f"\n[2] Generating real Groth16 proof...")
    print(f"    This may take 5-10 seconds...")
    
    try:
        result = prover.embed_with_proof(
            video_path=str(test_video),
            message="Test message for real proof verification",
            chaos_key="test_key_real_proof_123",
            output_json=str(output_json),
            generate_real_proof=True  # ← ENABLE REAL PROOFS
        )
        
        print(f"\n    ✅ Proof generated successfully!")
        print(f"\n    Proof details:")
        print(f"       Type: {result['proof_type']}")
        print(f"       Size: {result['proof_size']} bytes")
        print(f"       MVs modified: {result['modified_mv_count']:,}")
        print(f"       Capacity used: {result['capacity_used']:.1f}%")
        
        # Load and inspect proof
        with open(output_json, 'r') as f:
            metadata = json.load(f)
        
        proof_info = metadata['stego_metadata']['proof']
        print(f"\n    Groth16 Proof Structure:")
        print(f"       Pi_a: {len(proof_info['pi_a'])} elements")
        print(f"       Pi_b: {len(proof_info['pi_b'])} elements")
        print(f"       Pi_c: {len(proof_info['pi_c'])} elements")
        print(f"       Protocol: {proof_info['protocol']}")
        print(f"       Curve: {proof_info['curve']}")
        
        return True
        
    except Exception as e:
        print(f"    ❌ Proof generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_proof_verification():
    """Test verifying the real proof"""
    print("\n" + "=" * 60)
    print("TESTING PROOF VERIFICATION")
    print("=" * 60)
    
    sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
    from zk_mv_stego.verifier import VideoVerifier
    
    output_json = Path(__file__).parent.parent / 'output' / 'real_proof_test.json'
    
    if not output_json.exists():
        print("❌ No proof file found. Run test_real_proof() first.")
        return False
    
    # Initialize verifier
    circuit_dir = Path(__file__).parent.parent.parent / 'ImageLevel' / 'circuits' / 'compiled' / 'build'
    
    print(f"[1] Initializing VideoVerifier...")
    try:
        verifier = VideoVerifier(circuit_dir=str(circuit_dir))
        print(f"    ✅ Verifier initialized")
    except Exception as e:
        print(f"    ❌ Failed: {e}")
        return False
    
    # Verify proof
    print(f"\n[2] Verifying Groth16 proof...")
    try:
        is_valid, extracted = verifier.verify_and_extract(
            stego_metadata=str(output_json)
        )
        
        if is_valid:
            print(f"\n    ✅ PROOF VERIFIED SUCCESSFULLY!")
            print(f"\n    Extracted data:")
            print(f"       Message: {extracted['message']}")
            print(f"       Chaos key: {extracted['chaos_key']}")
            print(f"       Video hash: {extracted['video_hash'][:16]}...")
            print(f"       Proof type: {extracted['proof_type']}")
        else:
            print(f"\n    ❌ Proof verification FAILED")
            print(f"       Reason: {extracted.get('error', 'Unknown')}")
            return False
        
        return True
        
    except Exception as e:
        print(f"    ❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all checks and tests"""
    print("\n" + "=" * 60)
    print("ENABLE REAL ZK PROOFS - QUICK START")
    print("=" * 60)
    print()
    
    # Step 1: Check dependencies
    if not check_dependencies():
        print("\n❌ Missing dependencies. Please install and try again.")
        return 1
    
    # Step 2: Check circuits
    circuit_dir = check_circuits()
    if not circuit_dir:
        print("\n❌ Circuit files missing. Please compile circuits first.")
        return 1
    
    # Step 3: Test proof generation
    if not test_real_proof():
        print("\n❌ Real proof generation failed.")
        return 1
    
    # Step 4: Test verification
    if not test_proof_verification():
        print("\n❌ Proof verification failed.")
        return 1
    
    # Success!
    print("\n" + "=" * 60)
    print("✅ ALL CHECKS PASSED!")
    print("=" * 60)
    print()
    print("Real ZK proofs are working correctly! 🎉")
    print()
    print("Next steps:")
    print("1. Update tests to use generate_real_proof=True")
    print("2. Update CLI default to real proofs")
    print("3. Run full test suite: pytest tests/ -v")
    print()
    print("See IMPLEMENTATION_ROADMAP.md for detailed guide.")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
