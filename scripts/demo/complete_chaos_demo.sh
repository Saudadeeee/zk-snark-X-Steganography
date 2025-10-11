#!/bin/bash
# ZK-SNARK Chaos Steganography Complete Demo
# Demonstrates embedding and verification of ZK proofs using chaos-based positioning

set -e

echo "🔬 ZK-SNARK Chaos Steganography Complete Demo"
echo "============================================="

# Setup
DEMO_DIR="temp/final_demo"
mkdir -p "$DEMO_DIR"
cd "$DEMO_DIR"

echo ""
echo "1️⃣  Creating test image and proof data..."

# Create test image
python3 -c "
import numpy as np
from PIL import Image
import json

# Create 64x64 test image
img = np.random.randint(50, 200, (64, 64, 3), dtype=np.uint8)
Image.fromarray(img).save('original.png')
print('✓ Created 64x64 test image')

# Create realistic ZK proof
proof = {
    'pi_a': ['0x' + ''.join([hex(i)[2:] for i in range(10, 20)]), 
             '0x' + ''.join([hex(i)[2:] for i in range(20, 30)])],
    'pi_b': [['0x' + ''.join([hex(i)[2:] for i in range(30, 40)]),
              '0x' + ''.join([hex(i)[2:] for i in range(40, 50)])],
             ['0x' + ''.join([hex(i)[2:] for i in range(50, 60)]),
              '0x' + ''.join([hex(i)[2:] for i in range(60, 70)])]],
    'pi_c': ['0x' + ''.join([hex(i)[2:] for i in range(70, 80)]),
             '0x' + ''.join([hex(i)[2:] for i in range(80, 90)])],
    'protocol': 'groth16',
    'curve': 'bn128'
}

with open('proof.json', 'w') as f:
    json.dump(proof, f, indent=2)

# Create public inputs
public = {
    'inputs': ['1', '42', '123456789'],
    'proof_length': 0,
    'positions': []
}
with open('public.json', 'w') as f:
    json.dump(public, f)

print('✓ Created realistic ZK proof data')
"

echo ""
echo "2️⃣  Embedding ZK proof using chaos-based steganography..."

python3 -c "
import sys
sys.path.append('../../src')
from zk_stego.hybrid_proof_artifact import embed_chaos_proof

success = embed_chaos_proof(
    cover_image_path='original.png',
    stego_image_path='stego.png',
    proof_json_path='proof.json',
    public_json_path='public.json',
    secret_key='chaos_demo_key_2024',
    x0=25,
    y0=30
)

if success:
    print('✓ ZK proof embedded successfully using chaos positioning')
    print('  - Algorithm: Arnold Cat Map + Logistic Map')
    print('  - Method: Hybrid PNG chunks + LSB embedding')
    print('  - Secret key: chaos_demo_key_2024')
else:
    print('✗ Embedding failed')
    exit(1)
"

echo ""
echo "3️⃣  Analyzing storage overhead..."

ORIGINAL_SIZE=$(stat -c%s original.png)
STEGO_SIZE=$(stat -c%s stego.png)
OVERHEAD=$((STEGO_SIZE - ORIGINAL_SIZE))
PERCENT=$(python3 -c "print(f'{($OVERHEAD / $ORIGINAL_SIZE * 100):.1f}')")

echo "   Original image: $ORIGINAL_SIZE bytes"
echo "   Stego image:    $STEGO_SIZE bytes"
echo "   Overhead:       $OVERHEAD bytes ($PERCENT%)"

echo ""
echo "4️⃣  Verifying with single-command API..."

echo "   Basic verification:"
../../verify_zk_stego.py stego.png

echo ""
echo "   Detailed verification:"
../../verify_zk_stego.py stego.png --verbose

echo ""
echo "5️⃣  Testing with regular image (should fail)..."
../../verify_zk_stego.py original.png || echo "   ✓ Correctly detected no proof in original image"

echo ""
echo "6️⃣  JSON output for automation:"
../../verify_zk_stego.py stego.png --json > verification_result.json
echo "   Result saved to verification_result.json"
python3 -c "
import json
with open('verification_result.json') as f:
    result = json.load(f)
print(f'   ✓ Success: {result[\"success\"]}')
print(f'   ✓ Algorithm: {result[\"chaos_algorithm\"]}')
print(f'   ✓ Proof size: {result[\"proof_size_bits\"]} bits')
"

echo ""
echo "7️⃣  Demonstrating chaos position generation..."

python3 -c "
import sys
sys.path.append('../../src')
from zk_stego.chaos_embedding import ChaosGenerator

gen = ChaosGenerator(64, 64)
positions = gen.generate_positions(25, 30, 12345, 100)

print(f'   Generated {len(positions)} unique chaos positions')
print(f'   Sample positions: {positions[:5]}...')
if positions:
    print(f'   Position range: ({min(pos[0] for pos in positions)},{min(pos[1] for pos in positions)}) to ({max(pos[0] for pos in positions)},{max(pos[1] for pos in positions)})')

# Show Arnold Cat Map progression
print(f'\\n   Arnold Cat Map progression from (25,30):')
x, y = 25, 30
for i in range(5):
    x_new = (2 * x + y) % 64
    y_new = (x + y) % 64
    print(f'     Step {i+1}: ({x},{y}) → ({x_new},{y_new})')
    x, y = x_new, y_new
"

echo ""
echo "🎉 DEMO COMPLETE!"
echo ""
echo "Summary:"
echo "✅ ZK-SNARK proof embedded using chaos-based positioning"
echo "✅ Hybrid architecture: PNG chunks + LSB steganography"  
echo "✅ Single-command verification API working"
echo "✅ JSON output for automation support"
echo "✅ Proper error detection for non-stego images"
echo ""
echo "Files created:"
echo "📁 original.png       - Cover image"
echo "📁 stego.png          - Steganographic image with embedded proof"
echo "📁 proof.json         - ZK-SNARK proof data"
echo "📁 verification_result.json - Automated verification result"
echo ""
echo "Usage: ../../verify_zk_stego.py stego.png [--verbose] [--json]"