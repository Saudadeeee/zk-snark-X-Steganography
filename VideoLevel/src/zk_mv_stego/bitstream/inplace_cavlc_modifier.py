"""
In-Place CAVLC Coefficient Modifier

Strategy: Instead of full slice reconstruction, perform surgical bitstream editing:
1. Parse and locate each residual block's position in bitstream
2. Decode only the coefficient values
3. Check if modification needed
4. If VLC code length unchanged: overwrite in-place
5. If VLC code length changed: mark for full slice rebuild

This minimizes bitstream corruption by only modifying what's necessary.

Reference: ITU-T H.264 Section 7.3.5 (Macroblock Layer Syntax)
"""

from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

from .h264_parser import BitstreamReader, NALUnit
from .cavlc_decoder import CAVLCDecoder
from .cavlc_encoder import CAVLCEncoder
from .bitstream_writer import BitstreamWriter


@dataclass
class BlockLocation:
    """Location of a residual block in bitstream"""
    mb_idx: int
    block_idx: int
    bit_offset: int  # Start bit position in RBSP
    bit_length: int  # Length in bits
    original_coeffs: List[int]
    nC: int  # Context for CAVLC


class InPlaceCAVLCModifier:
    """
    Modify CAVLC-encoded coefficients with minimal bitstream changes
    """
    
    def __init__(self):
        self.block_locations: List[BlockLocation] = []
    
    def can_modify_inplace(self,
                          original_coeffs: List[int],
                          modified_coeffs: List[int],
                          nC: int) -> Tuple[bool, int, int]:
        """
        Check if coefficients can be modified in-place
        
        Returns:
            (can_modify, original_bits, new_bits)
        """
        # Encode both to check bit length
        writer_orig = BitstreamWriter()
        writer_new = BitstreamWriter()
        
        encoder_orig = CAVLCEncoder(writer_orig)
        encoder_new = CAVLCEncoder(writer_new)
        
        try:
            encoder_orig.encode_block_cavlc(original_coeffs, nC, max_num_coeff=16)
            encoder_new.encode_block_cavlc(modified_coeffs, nC, max_num_coeff=16)
            
            orig_bits = writer_orig.bit_count
            new_bits = writer_new.bit_count
            
            # Can only modify in-place if same length
            return (orig_bits == new_bits), orig_bits, new_bits
            
        except Exception as e:
            print(f"⚠️ Encoding check failed: {e}")
            return False, 0, 0
    
    def analyze_modification_feasibility(self,
                                        coeff_map: Dict[Tuple[int, int], List[int]],
                                        block_locations: List[BlockLocation]) -> Dict:
        """
        Analyze which modifications can be done in-place vs require full rebuild
        
        Returns:
            Statistics about modification feasibility
        """
        stats = {
            'total_blocks': len(coeff_map),
            'can_inplace': 0,
            'need_rebuild': 0,
            'avg_bit_change': 0.0,
            'inplace_blocks': [],
            'rebuild_blocks': []
        }
        
        total_bit_change = 0
        
        for loc in block_locations:
            key = (loc.mb_idx, loc.block_idx)
            if key not in coeff_map:
                continue
            
            modified_coeffs = coeff_map[key]
            can_inplace, orig_bits, new_bits = self.can_modify_inplace(
                loc.original_coeffs,
                modified_coeffs,
                loc.nC
            )
            
            if can_inplace:
                stats['can_inplace'] += 1
                stats['inplace_blocks'].append(key)
            else:
                stats['need_rebuild'] += 1
                stats['rebuild_blocks'].append(key)
                total_bit_change += abs(new_bits - orig_bits)
        
        if stats['need_rebuild'] > 0:
            stats['avg_bit_change'] = total_bit_change / stats['need_rebuild']
        
        return stats
    
    def print_analysis(self, stats: Dict):
        """Print modification analysis"""
        print(f"\n{'='*70}")
        print("CAVLC MODIFICATION ANALYSIS")
        print(f"{'='*70}")
        print(f"Total blocks to modify: {stats['total_blocks']}")
        print(f"✅ Can modify in-place: {stats['can_inplace']} ({stats['can_inplace']/max(stats['total_blocks'],1)*100:.1f}%)")
        print(f"⚠️  Need full rebuild: {stats['need_rebuild']} ({stats['need_rebuild']/max(stats['total_blocks'],1)*100:.1f}%)")
        
        if stats['need_rebuild'] > 0:
            print(f"   Average bit length change: {stats['avg_bit_change']:.1f} bits")
            print(f"\n   Rebuild needed for blocks:")
            for key in stats['rebuild_blocks'][:10]:
                print(f"     MB {key[0]}, Block {key[1]}")
            if len(stats['rebuild_blocks']) > 10:
                print(f"     ... and {len(stats['rebuild_blocks'])-10} more")
        
        print(f"{'='*70}\n")
    
    def suggest_strategy(self, stats: Dict) -> str:
        """
        Suggest best modification strategy based on analysis
        
        Returns:
            'inplace', 'hybrid', or 'full_rebuild'
        """
        if stats['need_rebuild'] == 0:
            return 'inplace'
        elif stats['need_rebuild'] < stats['total_blocks'] * 0.1:  # <10% need rebuild
            return 'hybrid'
        else:
            return 'full_rebuild'
