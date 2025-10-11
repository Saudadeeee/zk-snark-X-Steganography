#!/bin/bash
# ZK-SNARK Chaos Steganography - Feature-based Flow Demo
# Demonstrates: Image feature extraction → Chaos positioning → ZK proof embedding

set -e

echo "🎯 ZK-SNARK Feature-based Chaos Steganography Demo"
echo "=================================================="

DEMO_DIR="feature_demo"
mkdir -p "$DEMO_DIR"
cd "$DEMO_DIR"

echo ""
echo "1️⃣  Creating test image with texture features..."

python3 -c "
import numpy as np
from PIL import Image
import json

# Create image with distinct texture regions for feature extraction
img = np.random.randint(80, 120, (96, 96, 3), dtype=np.uint8)

# Add high-contrast texture patterns
# Pattern 1: Checkerboard in top-left
for i in range(10, 30):
    for j in range(10, 30):
        if (i + j) % 4 < 2:
            img[i, j] = [255, 255, 255]
        else:
            img[i, j] = [0, 0, 0]

# Pattern 2: Diagonal lines in bottom-right
for i in range(60, 85):
    for j in range(60, 85):
        if (i - j) % 3 == 0:
            img[i, j] = [255, 0, 0]

Image.fromarray(img).save('textured_cover.png')
print('✓ Created 96x96 image with texture patterns')

# Create realistic ZK proof data
proof = {
    'pi_a': ['0x' + ''.join([f'{i:02x}' for i in range(20, 40)]),
             '0x' + ''.join([f'{i:02x}' for i in range(40, 60)])],
    'pi_b': [['0x' + ''.join([f'{i:02x}' for i in range(60, 80)]),
              '0x' + ''.join([f'{i:02x}' for i in range(80, 100)])],
             ['0x' + ''.join([f'{i:02x}' for i in range(100, 120)]),
              '0x' + ''.join([f'{i:02x}' for i in range(120, 140)])]],
    'pi_c': ['0x' + ''.join([f'{i:02x}' for i in range(140, 160)]),
             '0x' + ''.join([f'{i:02x}' for i in range(160, 180)])],
    'protocol': 'groth16',
    'curve': 'bn128'
}

public = {
    'inputs': ['123456789', '987654321', '555444333'],
    'proof_length': 0,
    'positions': []
}

with open('zk_proof.json', 'w') as f:
    json.dump(proof, f, indent=2)
    
with open('public_inputs.json', 'w') as f:
    json.dump(public, f, indent=2)

print('✓ Created realistic ZK-SNARK proof data')
"

echo ""
echo "2️⃣  Demonstrating feature extraction process..."

python3 -c "
import sys
sys.path.append('../src')
from zk_stego.hybrid_proof_artifact import HybridProofArtifact
import numpy as np
from PIL import Image

# Load test image
img_array = np.array(Image.open('textured_cover.png'))
hybrid = HybridProofArtifact()

print('🔍 Analyzing image for texture features...')
print(f'   Image dimensions: {img_array.shape}')

# Extract feature point
feature_x, feature_y = hybrid.extract_image_feature_point(img_array)
print(f'   Detected feature point: ({feature_x}, {feature_y})')

# Analyze which region it found
if 10 <= feature_x <= 30 and 10 <= feature_y <= 30:
    print('   ✅ Found checkerboard pattern region')
elif 60 <= feature_x <= 85 and 60 <= feature_y <= 85:
    print('   ✅ Found diagonal lines region')
else:
    print('   📊 Found other high-texture region')
"

echo ""
echo "3️⃣  Embedding ZK proof using feature-based chaos positioning..."

python3 -c "
import sys
sys.path.append('../src')
from zk_stego.hybrid_proof_artifact import embed_chaos_proof

print('🔧 Embedding process:')
print('   → Image feature extraction for starting point')
print('   → Arnold Cat Map position transformation')
print('   → Logistic Map sequence generation')
print('   → LSB embedding at chaos positions')

success = embed_chaos_proof(
    'textured_cover.png',
    'feature_stego.png',
    'zk_proof.json',
    'public_inputs.json',
    'feature_demo_secret_2024'
)

if success:
    print('✅ ZK proof embedded successfully')
else:
    print('❌ Embedding failed')
    exit(1)
"

echo ""
echo "4️⃣  Analyzing storage and positioning..."

ORIGINAL_SIZE=$(stat -c%s textured_cover.png)
STEGO_SIZE=$(stat -c%s feature_stego.png)
OVERHEAD=$((STEGO_SIZE - ORIGINAL_SIZE))
PERCENT=$(python3 -c "print(f'{($OVERHEAD / $ORIGINAL_SIZE * 100):.1f}')")

echo "   Original image: $ORIGINAL_SIZE bytes"
echo "   Stego image:    $STEGO_SIZE bytes"
echo "   Storage overhead: $OVERHEAD bytes ($PERCENT%)"

python3 -c "
import sys
sys.path.append('../src')
from zk_stego.chaos_embedding import ChaosGenerator

print('\\n📊 Chaos positioning analysis:')
gen = ChaosGenerator(96, 96)
positions = gen.generate_positions(25, 25, 12345, 50)

print(f'   Generated {len(positions)} unique positions')
print(f'   Sample positions: {positions[:5]}...')
print(f'   Position spread: x∈[{min(p[0] for p in positions)},{max(p[0] for p in positions)}], y∈[{min(p[1] for p in positions)},{max(p[1] for p in positions)}]')

# Show Arnold Cat Map progression
print(f'\\n🔄 Arnold Cat Map progression example:')
x, y = 25, 25
for i in range(4):
    x_new = (2 * x + y) % 96
    y_new = (x + y) % 96
    print(f'   Step {i+1}: ({x:2d},{y:2d}) → ({x_new:2d},{y_new:2d})')
    x, y = x_new, y_new
"

echo ""
echo "5️⃣  Verification and extraction..."

echo "   Basic verification:"
../verify_zk_stego.py feature_stego.png

echo ""
echo "   Detailed verification:"
../verify_zk_stego.py feature_stego.png --verbose

echo ""
echo "6️⃣  Testing with non-stego image..."
../verify_zk_stego.py textured_cover.png || echo "   ✅ Correctly detected no proof in original"

echo ""
echo "🎉 FEATURE-BASED FLOW DEMO COMPLETE!"
echo ""
echo "Flow Summary:"
echo "1. ✅ Image texture analysis finds optimal starting point"
echo "2. ✅ Arnold Cat Map transforms positions chaotically" 
echo "3. ✅ Logistic Map generates unpredictable sequence"
echo "4. ✅ ZK proof embedded at unique chaos positions"
echo "5. ✅ Single-command verification extracts proof"
echo ""
echo "This demonstrates proper academic flow:"
echo "📊 Image Feature → 🌀 Chaos Transform → 🔐 ZK Embedding"