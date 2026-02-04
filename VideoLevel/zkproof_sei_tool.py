"""
AUTOMATION SCRIPT: ZK Proof SEI Embedding Workflow
====================================================

Giai đoạn 4: Script tự động hóa hoàn chỉnh cho Production
"""

import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from zk_mv_stego.bitstream.zkproof_sei_handler import ZKProofSEIHandler


def embed_proof(args):
    """
    Prover workflow: Embed ZK proof into video
    
    Usage:
        python zkproof_sei_tool.py embed -i video.h264 -p proof.bin -o output.h264
    """
    print("\n" + "="*80)
    print("PROVER: EMBEDDING ZK PROOF")
    print("="*80 + "\n")
    
    # Validate inputs
    if not os.path.exists(args.input):
        print(f"❌ ERROR: Input video not found: {args.input}")
        return 1
    
    if not os.path.exists(args.proof):
        print(f"❌ ERROR: Proof file not found: {args.proof}")
        return 1
    
    # Read proof
    with open(args.proof, 'rb') as f:
        proof_bytes = f.read()
    
    if len(proof_bytes) == 0:
        print("❌ ERROR: Proof file is empty")
        return 1
    
    print(f"Input video: {args.input}")
    print(f"Proof file:  {args.proof} ({len(proof_bytes)} bytes)")
    print(f"Output:      {args.output}")
    print()
    
    # Embed
    handler = ZKProofSEIHandler()
    stats = handler.embed_proof_in_video(
        input_video=args.input,
        zkproof_bytes=proof_bytes,
        output_video=args.output
    )
    
    if stats['success']:
        print(f"\n✅ SUCCESS: Proof embedded in {args.output}")
        print(f"   Size: {stats['input_size']:,} → {stats['output_size']:,} bytes")
        print(f"   Overhead: +{stats['output_size'] - stats['input_size']:,} bytes")
        return 0
    else:
        print("\n❌ FAILED: Could not embed proof")
        return 1


def extract_proof(args):
    """
    Verifier workflow: Extract ZK proof from video
    
    Usage:
        python zkproof_sei_tool.py extract -i video.h264 -o proof.bin
    """
    print("\n" + "="*80)
    print("VERIFIER: EXTRACTING ZK PROOF")
    print("="*80 + "\n")
    
    # Validate input
    if not os.path.exists(args.input):
        print(f"❌ ERROR: Input video not found: {args.input}")
        return 1
    
    print(f"Input video: {args.input}")
    print(f"Output:      {args.output}")
    print()
    
    # Extract
    handler = ZKProofSEIHandler()
    proof_bytes, stats = handler.extract_proof_from_video(args.input)
    
    if proof_bytes is None:
        print("\n❌ FAILED: Could not extract proof")
        print(f"   Error: {stats.get('error', 'Unknown')}")
        return 1
    
    # Write proof
    with open(args.output, 'wb') as f:
        f.write(proof_bytes)
    
    print(f"\n✅ SUCCESS: Proof extracted to {args.output}")
    print(f"   Size: {len(proof_bytes)} bytes")
    
    return 0


def verify_proof(args):
    """
    Verify extracted proof against original
    
    Usage:
        python zkproof_sei_tool.py verify -o original.bin -e extracted.bin
    """
    print("\n" + "="*80)
    print("VERIFICATION: COMPARE PROOFS")
    print("="*80 + "\n")
    
    # Read original
    if not os.path.exists(args.original):
        print(f"❌ ERROR: Original proof not found: {args.original}")
        return 1
    
    with open(args.original, 'rb') as f:
        original = f.read()
    
    # Read extracted
    if not os.path.exists(args.extracted):
        print(f"❌ ERROR: Extracted proof not found: {args.extracted}")
        return 1
    
    with open(args.extracted, 'rb') as f:
        extracted = f.read()
    
    print(f"Original:  {args.original} ({len(original)} bytes)")
    print(f"Extracted: {args.extracted} ({len(extracted)} bytes)")
    print()
    
    # Compare
    if original == extracted:
        print("✅ SUCCESS: Proofs match perfectly!")
        print(f"   Accuracy: 100% ({len(extracted)}/{len(original)} bytes)")
        return 0
    else:
        print("❌ FAILURE: Proofs do not match")
        
        # Find first difference
        min_len = min(len(original), len(extracted))
        for i in range(min_len):
            if original[i] != extracted[i]:
                print(f"   First diff at byte {i}:")
                print(f"   Original:  0x{original[i]:02x}")
                print(f"   Extracted: 0x{extracted[i]:02x}")
                break
        
        if len(original) != len(extracted):
            print(f"   Size mismatch: {len(original)} vs {len(extracted)} bytes")
        
        return 1


def full_workflow(args):
    """
    Complete workflow: Embed → Extract → Verify
    
    Usage:
        python zkproof_sei_tool.py workflow -i video.h264 -p proof.bin
    """
    print("\n" + "🎯"*40)
    print("COMPLETE WORKFLOW: EMBED → EXTRACT → VERIFY")
    print("🎯"*40 + "\n")
    
    # Setup paths
    output_video = args.output or "data/output/video_with_proof.h264"
    extracted_proof = "data/output/proof_extracted.bin"
    
    # Step 1: Embed
    print("STEP 1: EMBED")
    print("-"*80)
    
    embed_args = argparse.Namespace(
        input=args.input,
        proof=args.proof,
        output=output_video
    )
    
    result = embed_proof(embed_args)
    if result != 0:
        return result
    
    print()
    
    # Step 2: Extract
    print("STEP 2: EXTRACT")
    print("-"*80)
    
    extract_args = argparse.Namespace(
        input=output_video,
        output=extracted_proof
    )
    
    result = extract_proof(extract_args)
    if result != 0:
        return result
    
    print()
    
    # Step 3: Verify
    print("STEP 3: VERIFY")
    print("-"*80)
    
    verify_args = argparse.Namespace(
        original=args.proof,
        extracted=extracted_proof
    )
    
    result = verify_proof(verify_args)
    
    print()
    print("="*80)
    if result == 0:
        print("🎉 COMPLETE WORKFLOW: SUCCESS!")
    else:
        print("❌ COMPLETE WORKFLOW: FAILED")
    print("="*80)
    print()
    
    return result


def create_mock_proof(args):
    """
    Create mock ZK proof for testing
    
    Usage:
        python zkproof_sei_tool.py mock -o proof.bin -s 192
    """
    print(f"\nCreating mock proof: {args.output} ({args.size} bytes)")
    
    # Generate mock data
    mock_proof = (
        b"GROTH16_PI_A_POINT_" * 10 +
        b"GROTH16_PI_B_POINT_" * 10 +
        b"GROTH16_PI_C_POINT_" * 10 +
        b"PUBLIC_INPUTS_DATA_" * 10
    )
    
    mock_proof = mock_proof[:args.size]
    
    # Pad if needed
    if len(mock_proof) < args.size:
        mock_proof += b'\x00' * (args.size - len(mock_proof))
    
    # Write
    with open(args.output, 'wb') as f:
        f.write(mock_proof)
    
    print(f"✅ Created: {args.output}")
    print(f"   Size: {len(mock_proof)} bytes")
    print(f"   First 40 bytes: {mock_proof[:40]}")
    print()
    
    return 0


def main():
    """Main CLI entry point"""
    
    parser = argparse.ArgumentParser(
        description="ZK Proof SEI Embedding Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create mock proof for testing
  python zkproof_sei_tool.py mock -o proof.bin
  
  # Embed proof into video
  python zkproof_sei_tool.py embed -i video.h264 -p proof.bin -o output.h264
  
  # Extract proof from video
  python zkproof_sei_tool.py extract -i output.h264 -o extracted.bin
  
  # Verify extraction
  python zkproof_sei_tool.py verify -o proof.bin -e extracted.bin
  
  # Run complete workflow
  python zkproof_sei_tool.py workflow -i video.h264 -p proof.bin
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Embed command
    embed_parser = subparsers.add_parser('embed', help='Embed ZK proof into video')
    embed_parser.add_argument('-i', '--input', required=True, help='Input video file')
    embed_parser.add_argument('-p', '--proof', required=True, help='Proof file to embed')
    embed_parser.add_argument('-o', '--output', required=True, help='Output video file')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract ZK proof from video')
    extract_parser.add_argument('-i', '--input', required=True, help='Input video file')
    extract_parser.add_argument('-o', '--output', required=True, help='Output proof file')
    
    # Verify command
    verify_parser = subparsers.add_parser('verify', help='Verify extracted proof')
    verify_parser.add_argument('-o', '--original', required=True, help='Original proof file')
    verify_parser.add_argument('-e', '--extracted', required=True, help='Extracted proof file')
    
    # Workflow command
    workflow_parser = subparsers.add_parser('workflow', help='Run complete workflow')
    workflow_parser.add_argument('-i', '--input', required=True, help='Input video file')
    workflow_parser.add_argument('-p', '--proof', required=True, help='Proof file')
    workflow_parser.add_argument('-o', '--output', help='Output video file (optional)')
    
    # Mock command
    mock_parser = subparsers.add_parser('mock', help='Create mock proof for testing')
    mock_parser.add_argument('-o', '--output', default='data/output/mock_proof.bin', help='Output file')
    mock_parser.add_argument('-s', '--size', type=int, default=192, help='Proof size in bytes')
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 1
    
    # Route to appropriate handler
    if args.command == 'embed':
        return embed_proof(args)
    elif args.command == 'extract':
        return extract_proof(args)
    elif args.command == 'verify':
        return verify_proof(args)
    elif args.command == 'workflow':
        return full_workflow(args)
    elif args.command == 'mock':
        return create_mock_proof(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    exit(main())
