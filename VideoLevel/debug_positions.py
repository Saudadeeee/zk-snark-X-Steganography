"""
Debug: Compare safe positions between embedding and extraction
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.zk_mv_stego.decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
from src.zk_mv_stego.embedder.payload_embedder import PayloadEmbedder

# Extract coefficients
extractor = SimpleCAVLCExtractor()
frames = extractor.extract_from_video('benchmark_luma_only/benchmark_stego.h264', max_frames=1)

# Collect coefficients (luma only, skip chroma)
coefficients = []
for frame in frames:
    for mb in frame['macroblocks']:
        if mb.get('is_skip_mb', False) or mb.get('cbp', 1) == 0:
            continue
        
        coeffs = mb['coefficients']
        for block_idx in range(16):  # Luma only
            start = block_idx * 16
            block_coeffs = coeffs[start:start+16]
            coefficients.append((mb['mb_idx'], block_idx, block_coeffs))

# Get safe positions
embedder = PayloadEmbedder()
safe_positions = embedder.safety_filter.get_safe_positions(coefficients, skip_dc=True)

print(f"Total coefficients: {len(coefficients)}")
print(f"Total safe positions: {len(safe_positions)}")
print(f"\nFirst 20 safe positions (MB, Block, CoeffIdx):")
for i, (mb, blk, coeff_idx) in enumerate(safe_positions[:20]):
    # Get coefficient value
    key = (mb, blk)
    for mb_idx, block_idx, coeffs in coefficients:
        if mb_idx == mb and block_idx == blk:
            coeff_val = coeffs[coeff_idx]
            lsb = abs(coeff_val) & 1
            print(f"  {i:3d}: MB={mb:4d}, Block={blk:2d}, Coeff={coeff_idx:2d}, Val={coeff_val:4d}, LSB={lsb}")
            break
