"""
CAVLC Tables, Decoder, and Encoder
===================================

Merged module combining:
  - CAVLC VLC Tables (ITU-T H.264 Table 9-5 to 9-10)
  - CAVLCDecoder: Decode residual data from H.264 bitstream
  - CAVLCEncoder: Encode quantized DCT coefficients to CAVLC bitstream

Reference: ITU-T H.264 Specification Section 9.2
"""

from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)
from dataclasses import dataclass

from .bitstream_io import BitstreamWriter


# =============================================================================
# CAVLC TABLES  (formerly cavlc_tables.py)
# =============================================================================


# Table 9-5: coeff_token mapping for different nC values
# Format: {nC_range: {code_bits: (TotalCoeff, TrailingOnes)}}

# For nC = 0 or 1 (Table 9-5(a) - Complete)
# Format: 'code_string': (TotalCoeff, TrailingOnes)
# Table 0: nC=0-1 (from x264 reference implementation)
COEFF_TOKEN_NC_0_1 = {
    # TotalCoeff=0 (all zeros) - special codes
    '1': (0, 0),  # nC=0,1
    
    # TotalCoeff=1
    '000101': (1, 0),
    '01': (1, 1),
    
    # TotalCoeff=2
    '00000111': (2, 0),
    '000100': (2, 1),
    '0011': (2, 2),
    
    # TotalCoeff=3
    '000000111': (3, 0),
    '00000110': (3, 1),
    '0000101': (3, 2),
    '00011': (3, 3),
    
    # TotalCoeff=4
    '0000000111': (4, 0),
    '000000110': (4, 1),
    '00000101': (4, 2),
    '000011': (4, 3),
    
    # TotalCoeff=5
    '00000000111': (5, 0),
    '0000000110': (5, 1),
    '000000101': (5, 2),
    '0000100': (5, 3),
    
    # TotalCoeff=6
    '0000000001111': (6, 0),
    '00000000110': (6, 1),
    '0000000101': (6, 2),
    '00000100': (6, 3),
    
    # TotalCoeff=7
    '0000000001011': (7, 0),
    '0000000001110': (7, 1),
    '00000000101': (7, 2),
    '000000100': (7, 3),
    
    # TotalCoeff=8
    '0000000001000': (8, 0),
    '0000000001010': (8, 1),
    '0000000001101': (8, 2),
    '0000000100': (8, 3),
    
    # TotalCoeff=9
    '00000000001111': (9, 0),
    '00000000001110': (9, 1),
    '0000000001001': (9, 2),
    '00000000100': (9, 3),
    
    # TotalCoeff=10
    '00000000001011': (10, 0),
    '00000000001010': (10, 1),
    '00000000001101': (10, 2),
    '0000000001100': (10, 3),
    
    # TotalCoeff=11
    '000000000001111': (11, 0),
    '000000000001110': (11, 1),
    '00000000001001': (11, 2),
    '00000000001100': (11, 3),
    
    # TotalCoeff=12
    '000000000001011': (12, 0),
    '000000000001010': (12, 1),
    '000000000001101': (12, 2),
    '00000000001000': (12, 3),
    
    # TotalCoeff=13
    '0000000000000111': (13, 0),
    '0000000000001010': (13, 1),
    '000000000001001': (13, 2),
    '000000000001100': (13, 3),
    
    # TotalCoeff=14
    '0000000000000100': (14, 0),
    '0000000000000110': (14, 1),
    '0000000000000101': (14, 2),
    '000000000001000': (14, 3),

    # TotalCoeff=15 (16-bit codes)
    # T1=3 pattern: TC=13→'000000000001100'(15b), TC=14→'000000000001000'(15b),
    #               TC=15→'0000000000001100'(16b) following the double-zero extension pattern
    # T1=0,1,2 follow the '0000000000001xxx' available slot pattern (remaining from TC=13,14)
    '0000000000001111': (15, 0),
    '0000000000001110': (15, 1),
    '0000000000001101': (15, 2),
    '0000000000001100': (15, 3),

    # TotalCoeff=16 (16-bit codes)
    # Note: '0000000000001010' is taken by TC=13 T1=1; use other available slots
    '0000000000001011': (16, 0),
    '0000000000001001': (16, 1),
    '0000000000000011': (16, 2),
    '0000000000001000': (16, 3),
}

# For nC = 2 or 3 (Table 9-5(b)) - FROM X264 REFERENCE (VERIFIED PREFIX-FREE)
COEFF_TOKEN_NC_2_3 = {
    # TC=0 (all zeros) - special codes
    '11': (0, 0),  # nC=2,3
    
    # TC=1
    '001011': (1, 0),
    '10': (1, 1),
    
    # TC=2
    '000111': (2, 0),
    '00111': (2, 1),
    '011': (2, 2),
    
    # TC=3
    '0000111': (3, 0),
    '001010': (3, 1),
    '001001': (3, 2),
    '0101': (3, 3),
    
    # TC=4
    '00000111': (4, 0),
    '000110': (4, 1),
    '000101': (4, 2),
    '0100': (4, 3),
    
    # TC=5
    '00000100': (5, 0),
    '0000110': (5, 1),
    '0000101': (5, 2),
    '00110': (5, 3),
    
    # TC=6
    '000000111': (6, 0),
    '00000110': (6, 1),
    '00000101': (6, 2),
    '001000': (6, 3),
    
    # TC=7
    '00000001111': (7, 0),
    '000000110': (7, 1),
    '000000101': (7, 2),
    '000100': (7, 3),
    
    # TC=8
    '00000001011': (8, 0),
    '00000001110': (8, 1),
    '00000001101': (8, 2),
    '0000100': (8, 3),
    
    # TC=9
    '000000001111': (9, 0),
    '00000001010': (9, 1),
    '00000001001': (9, 2),
    '000000100': (9, 3),
    
    # TC=10
    '000000001011': (10, 0),
    '000000001110': (10, 1),
    '000000001101': (10, 2),
    '00000001100': (10, 3),
    
    # TC=11
    '000000001000': (11, 0),
    '000000001010': (11, 1),
    '000000001001': (11, 2),
    '00000001000': (11, 3),
    
    # TC=12
    '0000000001111': (12, 0),
    '0000000001110': (12, 1),
    '0000000001101': (12, 2),
    '000000001100': (12, 3),
    
    # TC=13
    '0000000001011': (13, 0),
    '0000000001010': (13, 1),
    '0000000001001': (13, 2),
    '0000000001100': (13, 3),
    
    # TC=14
    '0000000000111': (14, 0),
    '00000000001011': (14, 1),
    '0000000000110': (14, 2),
    '0000000001000': (14, 3),
    
    # TC=15
    '00000000001001': (15, 0),
    '00000000001000': (15, 1),
    '00000000001010': (15, 2),
    '0000000000001': (15, 3),
    
    # TC=16
    '00000000000111': (16, 0),
    '00000000000110': (16, 1),
    '00000000000101': (16, 2),
    '00000000000100': (16, 3),
}

# For nC = 4 or 5 (Table 9-5(c))
COEFF_TOKEN_NC_4_5 = {
    '1111': (0, 0),
    '1110': (1, 1),
    '1101': (2, 2),
    '1100': (3, 3),
    '1011': (4, 3),
    '1010': (5, 3),
    '1001': (6, 3),
    '1000': (7, 3),
    '01111': (2, 1),
    '01100': (3, 1),
    '01110': (3, 2),
    '01010': (4, 1),
    '01011': (4, 2),
    '01000': (5, 1),
    '01001': (5, 2),
    '01101': (8, 3),
    '011111': (1, 0),
    '011011': (2, 0),
    '011000': (3, 0),
    '011110': (6, 1),
    '011101': (6, 2),
    '011010': (7, 1),
    '011001': (7, 2),
    '011100': (9, 3),
    '0101111': (4, 0),
    '0101011': (5, 0),
    '0101001': (6, 0),
    '0101000': (7, 0),
    '0101110': (8, 1),
    '0101101': (8, 2),
    '0101010': (9, 2),
    '0101100': (10, 3),
    '01001111': (8, 0),
    '01001011': (9, 0),
    '01001110': (9, 1),
    '01001010': (10, 1),
    '01001101': (10, 2),
    '01001001': (11, 2),
    '01001100': (11, 3),
    '01001000': (12, 3),
    '010001111': (10, 0),
    '010001011': (11, 0),
    '010001110': (11, 1),
    '010001000': (12, 0),
    '010001010': (12, 1),
    '010001101': (12, 2),
    '010000111': (13, 1),
    '010001001': (13, 2),
    '010001100': (13, 3),
    '0100001101': (13, 0),
    '0100001001': (14, 0),
    '0100001100': (14, 1),
    '0100001011': (14, 2),
    '0100001010': (14, 3),
    '0100000101': (15, 0),
    '0100001000': (15, 1),
    '0100000111': (15, 2),
    '0100000110': (15, 3),
    '0100000001': (16, 0),
    '0100000100': (16, 1),
    '0100000011': (16, 2),
    '0100000010': (16, 3),
}

# For nC = -1 (Chroma DC 2x2)
# Complete table from FFmpeg libavcodec/h264_cavlc.c
# Maps VLC code -> (TotalCoeff, TrailingOnes)
COEFF_TOKEN_CHROMA_DC = {
    '1': (1, 1),           # TotalCoeff=1, T1s=1
    '01': (0, 0),          # TotalCoeff=0, T1s=0
    '001': (2, 2),         # TotalCoeff=2, T1s=2
    '000010': (4, 0),      # TotalCoeff=4, T1s=0
    '000011': (3, 0),      # TotalCoeff=3, T1s=0
    '000100': (2, 0),      # TotalCoeff=2, T1s=0
    '000101': (3, 3),      # TotalCoeff=3, T1s=3
    '000110': (2, 1),      # TotalCoeff=2, T1s=1
    '000111': (1, 0),      # TotalCoeff=1, T1s=0
    '0000000': (4, 3),     # TotalCoeff=4, T1s=3
    '0000010': (3, 2),     # TotalCoeff=3, T1s=2
    '0000011': (3, 1),     # TotalCoeff=3, T1s=1
    '00000010': (4, 2),    # TotalCoeff=4, T1s=2
    '00000011': (4, 1),    # TotalCoeff=4, T1s=1
}

# Table 9-9(b): Total zeros for 2x2 blocks (Chroma DC)
TOTAL_ZEROS_2x2 = {
    1: { # TotalCoeff = 1
        '1': 0,
        '01': 1,
        '00': 2,
        '000': 3, # Implicit?
    },
    2: { # TotalCoeff = 2
        '1': 0,
        '01': 1,
        '00': 2, # Max zeros 2? (Total 4, 2 coeffs -> 2 zeros)
    },
    3: { # TotalCoeff = 3
        '1': 0,
        '0': 1, # Max zeros 1
    }
}

# For nC = 6 or 7 (Table 9-5(d))
COEFF_TOKEN_NC_6_7 = {
    '1111': (0, 0),
    '1110': (1, 1),
    '1101': (2, 2),
    '1100': (3, 3),
    '1011': (4, 3),
    '1010': (5, 3),
    '1001': (6, 3),
    '1000': (7, 3),
    '01111': (2, 1),
    '01100': (3, 1),
    '01110': (3, 2),
    '01010': (4, 1),
    '01011': (4, 2),
    '01000': (5, 1),
    '01001': (5, 2),
    '01101': (8, 3),
    '011111': (1, 0),
    '011011': (2, 0),
    '011000': (3, 0),
    '011110': (6, 1),
    '011101': (6, 2),
    '011010': (7, 1),
    '011001': (7, 2),
    '011100': (9, 3),
    '0101111': (4, 0),
    '0101011': (5, 0),
    '0101001': (6, 0),
    '0101000': (7, 0),
    '0101110': (8, 1),
    '0101101': (8, 2),
    '0101010': (9, 2),
    '0101100': (10, 3),
    '01001111': (8, 0),
    '01001011': (9, 0),
    '01001110': (9, 1),
    '01001010': (10, 1),
    '01001101': (10, 2),
    '01001001': (11, 2),
    '01001100': (11, 3),
    '01001000': (12, 3),
    '010001111': (10, 0),
    '010001011': (11, 0),
    '010001110': (11, 1),
    '010001000': (12, 0),
    '010001010': (12, 1),
    '010001101': (12, 2),
    '010000111': (13, 1),
    '010001001': (13, 2),
    '010001100': (13, 3),
    '0100001101': (13, 0),
    '0100001001': (14, 0),
    '0100001100': (14, 1),
    '0100001011': (14, 2),
    '0100001010': (14, 3),
    '0100000101': (15, 0),
    '0100001000': (15, 1),
    '0100000111': (15, 2),
    '0100000110': (15, 3),
    '0100000001': (16, 0),
    '0100000100': (16, 1),
    '0100000011': (16, 2),
    '0100000010': (16, 3),
}

# For nC >= 8 (Table 9-5(e)) - uses fixed length code (FLC)
# FLC(6 bits): 2 bits for TrailingOnes, 4 bits for TotalCoeff


# Table 9-7: total_zeros VLC for different TotalCoeff values
# Format: {TotalCoeff: {code_bits: total_zeros_value}}

TOTAL_ZEROS_TABLES = {
    1: {
        '1': 0,
        '011': 1,
        '010': 2,
        '0011': 3,
        '0010': 4,
        '00011': 5,
        '00010': 6,
        '000011': 7,
        '000010': 8,
        '0000011': 9,
        '0000010': 10,
        '00000011': 11,
        '00000010': 12,
        '000000011': 13,
        '000000010': 14,
        '000000001': 15,
    },
    2: {
        '111': 0,
        '110': 1,
        '101': 2,
        '100': 3,
        '011': 4,
        '0101': 5,
        '0100': 6,
        '0011': 7,
        '0010': 8,
        '00011': 9,
        '00010': 10,
        '000011': 11,
        '000010': 12,
        '000001': 13,
        '000000': 14,
    },
    3: {
        '111': 1,
        '110': 2,
        '101': 3,
        '100': 6,
        '011': 7,
        '0101': 0,
        '0100': 4,
        '0011': 5,
        '0010': 8,
        '00011': 9,
        '00010': 10,
        '00001': 12,
        '000001': 11,
        '000000': 13,
    },
    4: {
        '111': 1,
        '110': 4,
        '101': 5,
        '100': 6,
        '011': 8,
        '0101': 2,
        '0100': 3,
        '0011': 7,
        '0010': 9,
        '00011': 0,
        '00010': 10,
        '00001': 11,
        '00000': 12,
    },
    5: {
        '111': 3,
        '110': 4,
        '101': 5,
        '100': 6,
        '011': 7,
        '0101': 0,
        '0100': 1,
        '0011': 2,
        '0010': 8,
        '0001': 10,
        '00001': 9,
        '00000': 11,
    },
    6: {
        '111': 2,
        '110': 3,
        '101': 4,
        '100': 5,
        '011': 6,
        '010': 7,
        '001': 9,
        '0001': 8,
        '00001': 1,
        '000001': 0,
        '000000': 10,
    },
    7: {
        '11': 5,
        '101': 2,
        '100': 3,
        '011': 4,
        '010': 6,
        '001': 8,
        '0001': 7,
        '00001': 1,
        '000001': 0,
        '000000': 9,
    },
    8: {
        '11': 4,
        '10': 5,
        '011': 3,
        '010': 6,
        '001': 7,
        '0001': 1,
        '00001': 2,
        '000001': 0,
        '000000': 8,
    },
    9: {
        '11': 3,
        '10': 4,
        '01': 6,
        '001': 5,
        '0001': 2,
        '00001': 7,
        '000001': 0,
        '000000': 1,
    },
    10: {
        '11': 3,
        '10': 4,
        '01': 5,
        '001': 2,
        '0001': 6,
        '00001': 0,
        '00000': 1,
    },
    11: {
        '1': 4,
        '001': 2,
        '010': 3,
        '011': 5,
        '0000': 0,
        '0001': 1,
    },
    12: {
        '1': 3,
        '01': 2,
        '001': 4,
        '0000': 0,
        '0001': 1,
    },
    13: {
        '1': 2,
        '01': 3,
        '000': 0,
        '001': 1,
    },
    14: {
        '1': 2,
        '00': 0,
        '01': 1,
    },
    15: {
        '0': 0,
        '1': 1,
    },
}


# Table 9-10: run_before VLC
# Format: {zerosLeft: {code_bits: run_before_value}}

RUN_BEFORE_TABLES = {
    1: {  # When zerosLeft = 1
        '1': 0,
        '0': 1,
    },
    2: {  # When zerosLeft = 2
        '1': 0,
        '01': 1,
        '00': 2,
    },
    3: {  # When zerosLeft = 3
        '11': 0,
        '10': 1,
        '01': 2,
        '00': 3,
    },
    4: {  # When zerosLeft = 4
        '11': 0,
        '10': 1,
        '01': 2,
        '00': 3,
    },
    5: {  # When zerosLeft = 5
        '11': 0,
        '10': 1,
        '011': 2,
        '010': 3,
        '001': 4,
        '000': 5,
    },
    6: {  # When zerosLeft = 6
        '11': 0,
        '000': 1,
        '001': 2,
        '011': 3,
        '010': 4,
        '101': 5,
        '100': 6,
    },
    # zerosLeft >= 7 use unary code (Table 9-10)
    7: {
        '111': 0,
        '110': 1,
        '101': 2,
        '100': 3,
        '011': 4,
        '010': 5,
        '001': 6,
        '000': 7,
    },
    8: {
        '1111': 0,
        '1110': 1,
        '1101': 2,
        '1100': 3,
        '1011': 4,
        '1010': 5,
        '1001': 6,
        '1000': 7,
        '0111': 8,
    },
    9: {
        '11111': 0,
        '11110': 1,
        '11101': 2,
        '11100': 3,
        '11011': 4,
        '11010': 5,
        '11001': 6,
        '11000': 7,
        '10111': 8,
        '10110': 9,
    },
    10: {
        '111111': 0,
        '111110': 1,
        '111101': 2,
        '111100': 3,
        '111011': 4,
        '111010': 5,
        '111001': 6,
        '111000': 7,
        '110111': 8,
        '110110': 9,
        '110101': 10,
    },
    11: {
        '1111111': 0,
        '1111110': 1,
        '1111101': 2,
        '1111100': 3,
        '1111011': 4,
        '1111010': 5,
        '1111001': 6,
        '1111000': 7,
        '1110111': 8,
        '1110110': 9,
        '1110101': 10,
        '1110100': 11,
    },
    12: {
        '11111111': 0,
        '11111110': 1,
        '11111101': 2,
        '11111100': 3,
        '11111011': 4,
        '11111010': 5,
        '11111001': 6,
        '11111000': 7,
        '11110111': 8,
        '11110110': 9,
        '11110101': 10,
        '11110100': 11,
        '11110011': 12,
    },
    13: {
        '111111111': 0,
        '111111110': 1,
        '111111101': 2,
        '111111100': 3,
        '111111011': 4,
        '111111010': 5,
        '111111001': 6,
        '111111000': 7,
        '111110111': 8,
        '111110110': 9,
        '111110101': 10,
        '111110100': 11,
        '111110011': 12,
        '111110010': 13,
    },
    14: {
        '1111111111': 0,
        '1111111110': 1,
        '1111111101': 2,
        '1111111100': 3,
        '1111111011': 4,
        '1111111010': 5,
        '1111111001': 6,
        '1111111000': 7,
        '1111110111': 8,
        '1111110110': 9,
        '1111110101': 10,
        '1111110100': 11,
        '1111110011': 12,
        '1111110010': 13,
        '1111110001': 14,
    },
}


def get_coeff_token_table(nC: int):
    """
    Get appropriate coeff_token VLC table based on nC value
    
    Args:
        nC: Prediction value from neighboring blocks
        
    Returns:
    """
    if nC == -1:
        # Chroma DC uses special table (Table 9-5 column nC=-1)
        return COEFF_TOKEN_CHROMA_DC
    elif nC == -2:
        # Chroma AC uses same table as nC=0-1 (Table 9-5 column nC=0,1)
        return COEFF_TOKEN_NC_0_1
    elif nC < 2:
        return COEFF_TOKEN_NC_0_1
    elif nC < 4:
        return COEFF_TOKEN_NC_2_3
    elif nC < 6:
        return COEFF_TOKEN_NC_4_5
    elif nC < 8:
        return COEFF_TOKEN_NC_6_7
    else:
        # Use FLC(6) - fixed length code
        return 'FLC6'

# ...

def get_total_zeros_table(total_coeff: int, is_chroma_dc: bool = False):
    """
    Get total_zeros VLC table for given TotalCoeff
    
    Args:
        total_coeff: Number of non-zero coefficients
        is_chroma_dc: Whether this is for Chroma DC (2x2 block)
    """
    if is_chroma_dc:
        if total_coeff in TOTAL_ZEROS_2x2:
            return TOTAL_ZEROS_2x2[total_coeff]
        return {}
        
    if total_coeff in TOTAL_ZEROS_TABLES:
        return TOTAL_ZEROS_TABLES[total_coeff]
    else:
        # Return empty dict for unimplemented tables
        return {}



def get_run_before_table(zeros_left: int):
    """
    Get run_before VLC table for given zerosLeft
    
    Args:
        zeros_left: Number of zeros remaining to be coded
        
    Returns:
        Dictionary mapping code strings to run_before values
    """
    if zeros_left > 14:
        # For zerosLeft > 14, use table for 14
        zeros_left = 14
    
    if zeros_left in RUN_BEFORE_TABLES:
        return RUN_BEFORE_TABLES[zeros_left]
    else:
        return {}


# Helper function to decode VLC from bitstream
def decode_vlc(reader, vlc_table: dict, max_bits: int = 16, debug: bool = False) -> tuple:
    """
    Decode variable length code from bitstream using LONGEST-MATCH strategy
    
    CRITICAL: H.264 VLC tables are designed for longest-match decoding, NOT first-match!
    Tables can have "prefix overlaps" where shorter codes are prefixes of longer codes.
    Example: '0001' (4 bits) and '00011' (5 bits) are BOTH valid - length disambiguates.
    
    Strategy:
    1. Read bits progressively up to max_bits
    2. Track ALL valid matches found along the way
    3. Return the LONGEST valid match
    4. Rewind bitstream to position after longest match
    
    Args:
        reader: BitstreamReader instance with tell() and seek() methods
        vlc_table: VLC table dictionary mapping bit patterns to values
        max_bits: Maximum code length to try
        debug: Enable debug logging
        
    Returns:
        Decoded value corresponding to longest matching code
        
    Raises:
        ValueError: If no valid code found in bitstream
    """
    start_pos = reader.tell()
    code_str = ''
    longest_match = None
    longest_match_len = 0
    
    if debug:
        logger.debug(f"      [decode_vlc] Starting at position {start_pos}")
    
    # Read bits progressively and track longest match
    for i in range(max_bits):
        try:
            bit = reader.read_bits(1)
            code_str += str(bit)
            
            # Check if current code_str is a valid code
            if code_str in vlc_table:
                longest_match = vlc_table[code_str]
                longest_match_len = len(code_str)
                
                if debug:
                    logger.debug(f"      [decode_vlc] Found match: '{code_str}' -> {longest_match}")
                
                # Optimization: Check if any longer codes exist with this prefix
                # If not, we can stop early
                has_longer = any(k.startswith(code_str) and len(k) > len(code_str) 
                                for k in vlc_table.keys())
                if not has_longer:
                    # This is definitely the longest match, stop here
                    if debug:
                        logger.debug(f"      [decode_vlc] No longer codes, stopping at '{code_str}'")
                    break
        except Exception:
            # End of stream reached
            break
    
    # If we found at least one match, rewind to end of longest match and return
    if longest_match is not None:
        # Rewind to position right after the longest match
        end_pos = start_pos + longest_match_len
        reader.seek(end_pos)
        if debug:
            logger.debug(f"      [decode_vlc] Rewinding to position {end_pos} (consumed {longest_match_len} bits)")
        return longest_match
    
    # No valid code found - CRITICAL: rewind reader to start_pos to prevent desync
    reader.seek(start_pos)
    raise ValueError(f"Invalid VLC code: {code_str} (no match in table)")


# ============================================================================
# REVERSE VLC TABLE LOOKUP (for Encoding)
# ============================================================================

def build_reverse_coeff_token_table(nC: int) -> dict:
    """
    Build reverse lookup table for coeff_token encoding
    
    Args:
        nC: Neighbor prediction value
    
    Returns:
        Dictionary mapping (total_coeffs, trailing_ones) -> bit_string
    """
    forward_table = get_coeff_token_table(nC)
    reverse = {}
    
    for bit_string, (tc, t1) in forward_table.items():
        reverse[(tc, t1)] = bit_string
    
    return reverse


def build_reverse_total_zeros_table(total_coeffs: int) -> dict:
    """
    Build reverse lookup table for total_zeros encoding
    
    Args:
        total_coeffs: Number of non-zero coefficients (1-15)
    
    Returns:
        Dictionary mapping total_zeros -> bit_string
    """
    forward_table = get_total_zeros_table(total_coeffs)
    reverse = {}
    
    for bit_string, tz in forward_table.items():
        reverse[tz] = bit_string
    
    return reverse


def build_reverse_run_before_table(zeros_left: int) -> dict:
    """
    Build reverse lookup table for run_before encoding
    
    Args:
        zeros_left: Number of zeros remaining (1-14)
    
    Returns:
        Dictionary mapping run_before -> bit_string
    """
    forward_table = get_run_before_table(zeros_left)
    reverse = {}
    
    for bit_string, rb in forward_table.items():
        reverse[rb] = bit_string
    
    return reverse


def find_coeff_token_code(total_coeffs: int, trailing_ones: int, nC: int) -> str:
    """
    Find VLC code for coeff_token
    
    Args:
        total_coeffs: 0-16
        trailing_ones: 0-3
        nC: Neighbor prediction
    
    Returns:
        Bit string for VLC code
    """
    # Handle TC=0 (all zeros) - use coeff0_token table from x264
    if total_coeffs == 0 and trailing_ones == 0:
        # x264_coeff0_token[6] from tables.c line 1798
        if nC < 2:
            return '1'        # nC=0,1
        elif nC < 4:
            return '11'       # nC=2,3
        elif nC < 6:
            return '1111'     # nC=4,5
        elif nC < 8:
            return '000011'   # nC=6,7
        elif nC == -1:
            return '01'
        elif nC == -2:
            return '1'
        else:
            # Should not happen
            return '1'
    
    if nC >= 8:
        # Use FLC: 6 bits total, bits[5:4]=T1 (upper 2), bits[3:0]=TC (lower 4)
        code = (trailing_ones << 4) | (total_coeffs & 0xF)
        return f"{code:06b}"
    
    reverse_table = build_reverse_coeff_token_table(nC)
    
    key = (total_coeffs, trailing_ones)
    if key not in reverse_table:
        raise ValueError(f"Invalid coeff_token: TC={total_coeffs}, T1={trailing_ones}, nC={nC}")
    
    return reverse_table[key]


def find_total_zeros_code(total_zeros: int, total_coeffs: int) -> str:
    """
    Find VLC code for total_zeros
    
    Args:
        total_zeros: 0 to (15 - total_coeffs)
        total_coeffs: 1-15
    
    Returns:
        Bit string for VLC code
    """
    if total_coeffs == 16:
        return ""  # No zeros possible
    
    reverse_table = build_reverse_total_zeros_table(total_coeffs)
    
    if total_zeros not in reverse_table:
        raise ValueError(f"Invalid total_zeros: {total_zeros} for TC={total_coeffs}")
    
    return reverse_table[total_zeros]


def find_run_before_code(run_before: int, zeros_left: int) -> str:
    """
    Find VLC code for run_before
    
    Args:
        run_before: Run of zeros before this coefficient
        zeros_left: Zeros remaining to encode
    
    Returns:
        Bit string for VLC code
    """
    if zeros_left == 0:
        return ""  # No run possible
    
    reverse_table = build_reverse_run_before_table(zeros_left)
    
    if run_before not in reverse_table:
        raise ValueError(f"Invalid run_before: {run_before} for zerosLeft={zeros_left}")
    
    return reverse_table[run_before]


# =============================================================================
# CAVLC DECODER  (formerly cavlc_decoder.py)
# =============================================================================

@dataclass
class CoefficientBlock:
    """Represents a 4x4 block of quantized DCT coefficients"""
    levels: List[int]  # Coefficient values (integers)
    total_coeffs: int  # Number of non-zero coefficients
    trailing_ones: int  # Number of trailing ±1 values
    total_zeros: int  # Total number of zeros
    
    
class CAVLCDecoder:
    """
    Decode CAVLC-encoded residual data to extract quantized coefficient levels
    
    CAVLC encoding structure:
    1. coeff_token: Encodes TotalCoeffs and TrailingOnes
    2. trailing_ones_sign_flag: Signs of trailing ±1 values
    3. level values: Remaining non-zero coefficient values
    4. total_zeros: Total number of zeros before last coefficient
    5. run_before: Number of zeros before each coefficient
    """
    
    def __init__(self, reader):
        """
        Args:
            reader: BitstreamReader instance positioned at residual data
        """
        self.reader = reader
        
    def decode_block_cavlc(self, nC: int, max_num_coeff: int = 16, debug_key=None) -> CoefficientBlock:
        """
        Decode one 4x4 block of coefficients using CAVLC
        
        Args:
            nC: Prediction of number of non-zero coefficients from neighbors
            max_num_coeff: Maximum coefficients (16 for 4x4, 15 for chroma DC)
            debug_key: Optional (mb_idx, block_idx) for debugging
            
        Returns:
            CoefficientBlock with decoded levels
        """
        pos_start = self.reader.position
        if debug_key and debug_key[0] == 0 and debug_key[1] < 16:
            logger.debug(f"    [CAVLC_DEC] Enter decode MB:{debug_key[0]} Blk:{debug_key[1]} nC:{nC} Pos:{pos_start}")

        total_coeffs, trailing_ones = self._decode_coeff_token(nC)

        if total_coeffs > max_num_coeff:
            raise ValueError(f"Invalid total_coeffs={total_coeffs} > max_num_coeff={max_num_coeff} - bitstream desync")

        if debug_key and debug_key[0] == 0 and debug_key[1] < 16:
            pos_after_token = self.reader.position
            bits_for_token = pos_after_token - pos_start
            logger.debug(f"    [CAVLC_DEC] coeff_token -> TC:{total_coeffs} T1:{trailing_ones} (consumed {bits_for_token} bits)")

        if total_coeffs == 0:
            # Block is all zeros
            return CoefficientBlock(
                levels=[0] * max_num_coeff,
                total_coeffs=0,
                trailing_ones=0,
                total_zeros=0
            )
        
        # Step 2: Decode signs of trailing ones
        trailing_signs = []
        for _ in range(trailing_ones):
            sign = self.reader.read_bits(1)
            trailing_signs.append(-1 if sign else 1)
        
        # Step 3: Decode remaining levels
        levels_remaining = total_coeffs - trailing_ones
        level_values = self._decode_levels(levels_remaining, trailing_ones, total_coeffs)
        
        # Step 4: Decode total_zeros
        if total_coeffs < max_num_coeff:
            is_chroma_dc = (nC == -1)
            total_zeros = self._decode_total_zeros(total_coeffs, max_num_coeff, is_chroma_dc)
        else:
            total_zeros = 0
        
        # Step 5: Decode run_before values
        runs = self._decode_runs(total_coeffs, total_zeros)
        
        # Step 6: Reconstruct coefficient array with zigzag order
        # Combine levels: trailing ones first, then non-trailing levels
        # This matches encoding order (trailing ones are highest frequency coeffs)
        # Both are decoded in reverse zigzag order (high frequency first)
        # Need to reverse to get forward zigzag order for reconstruction
        all_levels = trailing_signs + level_values
        all_levels_forward = list(reversed(all_levels))
        runs_forward = list(reversed(runs))
        
        coeffs = self._reconstruct_coefficients(
            all_levels_forward,
            runs_forward,
            max_num_coeff
        )
        
        # Debug: log what we decoded
        if debug_key and debug_key[0] == 0 and debug_key[1] in [16, 17, 18, 19]:
            non_zero = [c for c in coeffs if c != 0]
            logger.debug(f"      [CAVLC_DEC] Decoded MB{debug_key[0]} block{debug_key[1]}: {non_zero[:5]}...")
        
        return CoefficientBlock(
            levels=coeffs,
            total_coeffs=total_coeffs,
            trailing_ones=trailing_ones,
            total_zeros=total_zeros
        )
    
    def _decode_coeff_token(self, nC: int) -> Tuple[int, int]:
        """
        Decode coeff_token using VLC table WITH ROBUST ERROR RECOVERY

        Returns: (TotalCoeffs, TrailingOnes)
        """
        table = get_coeff_token_table(nC)
        start_pos = self.reader.tell()  # Save position for reset/fallback

        if table == 'FLC6':
            # nC >= 8: use fixed-length code (6 bits)
            # H.264 spec Table 9-5(e): 6-bit FLC where:
            #   bits[5:2] (upper 4 bits) = TotalCoeff (0-15)
            #   bits[1:0] (lower 2 bits) = TrailingOnes (0-3)
            # code = (TotalCoeff << 2) | TrailingOnes
            try:
                code = self.reader.read_bits(6)
                total_coeffs = code >> 2            # Upper 4 bits = TC
                trailing_ones = code & 0x3          # Lower 2 bits = T1
                return (total_coeffs, min(trailing_ones, 3))
            except Exception:
                # Bitstream error - return zero coefficients
                return (0, 0)

        elif table:
            # Use VLC table lookup with improved error handling
            primary_failed = False
            try:
                total_coeffs, trailing_ones = decode_vlc(self.reader, table, max_bits=16)
                # Validate decoded values
                if total_coeffs > 16 or trailing_ones > 3 or trailing_ones > total_coeffs:
                    # CRITICAL FIX: Reset reader before falling through to fallback.
                    # Without this the reader is left advanced by the matched prefix → desync.
                    self.reader.seek(start_pos)
                    primary_failed = True
                else:
                    return (total_coeffs, trailing_ones)
            except ValueError:
                # decode_vlc already reset reader to start_pos on failure
                primary_failed = True

            if primary_failed:
                # FALLBACK: Try adjacent VLC table when primary table failed.
                # H.264 encoders (e.g. x264) compute nC from actual encoded TC values,
                # while the decoder computes nC from decoded TC values. Any decode error
                # upstream propagates as wrong neighbor TC → nC mismatch here.
                # Strategy: try the next-higher (or next-lower) table as fallback.
                if nC >= 2:
                    # Primary was NC_2_3 or higher; try NC_0_1 (encoder used lower nC)
                    fallback_table = get_coeff_token_table(0)  # NC_0_1
                    try:
                        tc, t1 = decode_vlc(self.reader, fallback_table, max_bits=16)
                        if 0 <= tc <= 16 and 0 <= t1 <= 3 and t1 <= tc:
                            return (tc, t1)
                        else:
                            self.reader.seek(start_pos)
                    except ValueError:
                        pass  # decode_vlc already reset reader
                else:
                    # Primary was NC_0_1 (nC=0 or 1); try NC_2_3 (encoder used higher nC)
                    # This handles the case where upstream decode errors caused nC
                    # to be under-estimated (e.g. a neighbor's TC was read as 0 due to
                    # a prior NC_0_1 failure, depressing nC for this block).
                    fallback_table = get_coeff_token_table(2)  # NC_2_3
                    try:
                        tc, t1 = decode_vlc(self.reader, fallback_table, max_bits=16)
                        if 0 <= tc <= 16 and 0 <= t1 <= 3 and t1 <= tc:
                            return (tc, t1)
                        else:
                            self.reader.seek(start_pos)
                    except ValueError:
                        pass  # decode_vlc already reset reader
                return (0, 0)
        else:
            # Fallback for missing tables - use simple heuristic
            try:
                if self.reader.read_bits(1) == 0:
                    return (0, 0)
                # Simple fallback: read UE code for total_coeffs
                total_coeffs = min(self.reader.read_ue() + 1, 16)
                trailing_ones = min(self.reader.read_bits(2), total_coeffs)
                return (total_coeffs, trailing_ones)
            except Exception:
                return (0, 0)
    
    def _decode_levels(self, count: int, trailing_ones: int, total_coeffs: int) -> List[int]:
        """
        Decode remaining coefficient levels (non-trailing-one values)
        
        H.264 Spec 9.2.2.1: levelCode = 2*abs_level - 2 + (sign ? 1 : 0)
        Where sign=0 for positive, sign=1 for negative
        """
        levels = []
        
        # Level decoding uses adaptive VLC
        # suffixLength initialization per H.264 spec Section 9.2.2.1:
        # suffixLength = (TotalCoeff > 10 && TrailingOnes < 3) ? 1 : 0
        # When TrailingOnes == 3, suffixLength is always 0 regardless of TC.

        if total_coeffs > 10 and trailing_ones < 3:
            suffixLength = 1
        else:
            suffixLength = 0

        for i in range(count):
            # Decode level_prefix (unary code)
            level_prefix = 0
            while self.reader.read_bits(1) == 0:
                level_prefix += 1
                if level_prefix > 24:  # Hard cap - values >24 indicate bitstream desync
                    raise ValueError(f"level_prefix overflow ({level_prefix}>24) at level {i}/{count} - bitstream desync")
            
            # Decode level_suffix if needed
            if suffixLength == 0:
                if level_prefix < 14:
                    levelCode = level_prefix
                elif level_prefix == 14:
                    level_suffix = self.reader.read_bits(4)
                    levelCode = 14 + level_suffix
                else: # level_prefix >= 15
                    levelCode = 30
                    if level_prefix >= 16:
                        levelCode += (1 << (level_prefix - 3)) - 4096
                    levelCode += self.reader.read_bits(level_prefix - 3)
            else: # suffixLength > 0
                if level_prefix < 15:
                    level_suffix = self.reader.read_bits(suffixLength)
                    levelCode = (level_prefix << suffixLength) + level_suffix
                else: # level_prefix >= 15
                    levelCode = 15 << suffixLength
                    if level_prefix >= 16:
                        levelCode += (1 << (level_prefix - 3)) - 4096
                    levelCode += self.reader.read_bits(level_prefix - 3)
            
            # Convert levelCode to actual level value
            # H.264 Section 9.2.2.1:
            # - Normal: levelCode = 2*abs_level - 2 + sign_bit
            # - After 3 T1s: levelCode = 2*abs_level + sign_bit (bias +3 correction)
            sign_bit = levelCode & 1  # LSB is sign (0=positive, 1=negative)
            
            if i == 0 and trailing_ones == 3:
                # First level after 3 T1s: special decoding
                # levelCode = 2*(abs_level - 2) + sign_bit
                # Solve: abs_level = (levelCode - sign_bit)/2 + 2
                abs_level = (levelCode - sign_bit) >> 1
                abs_level += 2
            else:
                # levelCode = 2*abs_level - 2 + sign_bit
                # abs_level = (levelCode - sign_bit + 2) / 2
                abs_level = (levelCode - sign_bit + 2) >> 1

            
            # Apply sign (1 = negative, 0 = positive)
            level = -abs_level if sign_bit else abs_level
            
            levels.append(level)
            
            # CRITICAL: Adaptive suffixLength update per H.264 Section 9.2.2.1
            # H.264 spec uses TWO SEPARATE if-statements (not if/elif):
            #   if (i==0 && suffixLength==0) suffixLength = 1;
            #   if (Abs(level[i]) > (3*(1<<(suffixLength-1))) && suffixLength<6)
            #       suffixLength++;
            # Using elif skips the threshold check for i==0, causing divergence
            # from spec and from FFmpeg for large level[0] values.
            if suffixLength == 0:
                suffixLength = 1
            if abs(level) > (3 << (suffixLength - 1)) and suffixLength < 6:
                suffixLength += 1
        
        return levels
    
    def _decode_total_zeros(self, total_coeffs: int, max_num_coeff: int, is_chroma_dc: bool = False) -> int:
        """
        Decode total_zeros using VLC table based on TotalCoeffs
        
        CRITICAL: Must use VLC table correctly. When table lookup fails, 
        returning 0 is safer than read_ue() which can consume excessive bits.
        """
        # Edge case: if all coefficients present, no total_zeros encoded
        if total_coeffs >= max_num_coeff:
            return 0
        
        table = get_total_zeros_table(total_coeffs, is_chroma_dc)
        
        if not table:
            # No VLC table for this total_coeffs (shouldn't happen for TC=1-15)
            # Return max possible zeros as safe fallback
            return max_num_coeff - total_coeffs
        
        try:
            total_zeros = decode_vlc(self.reader, table, max_bits=9)
            
            # Validate result is within valid range
            max_tz = max_num_coeff - total_coeffs
            if total_zeros > max_tz or total_zeros < 0:
                # Decoded value out of range - VLC decode bug or bitstream corruption
                # Clamp to safe range
                return max(0, min(total_zeros, max_tz))
            
            return total_zeros
        except ValueError as e:
            # VLC decode failed - bitstream desync or corrupted
            # Return 0 as safest assumption (all non-zero coefficients packed together)
            # This is better than read_ue() which can consume 10+ bits incorrectly
            return 0
    
    def _decode_runs(self, total_coeffs: int, total_zeros: int) -> list:
        """
        Decode run_before values (zeros before each non-zero coeff)
        """
        runs = []
        zeros_left = total_zeros
        
        # Optimization: if no zeros, all runs are 0
        if total_zeros == 0:
            return [0] * total_coeffs
        
        for i in range(total_coeffs - 1):
            if zeros_left > 0:
                # Get run_before table for current zeros_left
                table = get_run_before_table(zeros_left)
                
                if table:
                    try:
                        run = decode_vlc(self.reader, table, max_bits=11)
                        # Clamp run to zeros_left to prevent negative zeros_left
                        run = min(run, zeros_left)
                        runs.append(run)
                        zeros_left -= run
                    except ValueError:
                        # VLC decode failed - decode_vlc already rewound the reader
                        # SAFE FALLBACK: use run=0 (no bits consumed, stays in sync)
                        # Do NOT use read_ue() here - it consumes excessive bits and desynchronizes!
                        runs.append(0)
                        # zeros_left unchanged (no zeros consumed)
                else:
                    # No table available - safe default
                    runs.append(0)
            else:
                runs.append(0)
        
        # Last coefficient gets all remaining zeros
        runs.append(zeros_left)
        
        return runs
    
    def _reconstruct_coefficients(self, levels: List[int], runs: List[int], 
                                   max_num_coeff: int) -> List[int]:
        """
        Reconstruct coefficient array from levels and runs
        Apply reverse zigzag scan
        """
        coeffs = []
        level_idx = 0
        
        # Place coefficients with zeros according to runs
        for i in range(len(runs)):
            # Add zeros before this coefficient
            coeffs.extend([0] * runs[i])
            # Add the coefficient
            if level_idx < len(levels):
                coeffs.append(levels[level_idx])
                level_idx += 1
        
        # Pad with zeros to max_num_coeff
        while len(coeffs) < max_num_coeff:
            coeffs.append(0)
        
        # Coefficients are already in zigzag scan order (same as encoder input)
        # No need to apply reverse zigzag - that would convert to raster order
        return coeffs[:max_num_coeff]


# =============================================================================
# CAVLC ENCODER  (formerly cavlc_encoder.py)
# =============================================================================




@dataclass
class BlockAnalysis:
    """Analysis of coefficient block for encoding"""
    total_coeffs: int  # Actual non-zero count for coeff_token
    total_coeffs_for_suffix: int  # For suffixLength (may use override)
    trailing_ones: int
    trailing_signs: List[int]  # +1 or -1
    levels: List[int]  # All non-zero coefficients
    total_zeros: int
    runs: List[int]  # Run of zeros before each coefficient


class CAVLCEncoder:
    """
    Encode quantized DCT coefficients using CAVLC
    
    Reverse process of CAVLCDecoder:
    - Analyze coefficient block
    - Encode coeff_token
    - Encode trailing ones signs
    - Encode levels with adaptive suffix
    - Encode total_zeros
    - Encode run_before values
    """
    
    def __init__(self, writer: BitstreamWriter):
        self.writer = writer
    
    def encode_block_cavlc(self, coeffs: List[int], nC: int, max_num_coeff: int = 16,
                          debug_key=None, override_total_coeffs: int = None,
                          override_trailing_ones: int = None):
        """
        Encode one coefficient block using CAVLC

        Args:
            coeffs: Coefficient array in zigzag order (length max_num_coeff)
            nC: Neighbor prediction for context
            max_num_coeff: Maximum coefficients (16 for 4x4, 15 for chroma DC)
            debug_key: Optional (mb_idx, block_idx) for debugging
            override_total_coeffs: Override for total_coeffs (for re-encoding with preserved suffixLength)
            override_trailing_ones: Override T1 count to match original decoder's T1 (prevents
                                    encoder from choosing a higher T1 than the original)
        """
        analysis = self._analyze_block(coeffs, max_num_coeff, override_total_coeffs=override_total_coeffs,
                                       override_trailing_ones=override_trailing_ones)

        if debug_key and (debug_key[0] == 0 or debug_key[0] == 309):
            logger.debug("[ENC_DEBUG] Block %s: total_coeffs=%d, total_coeffs_for_suffix=%d, "
                         "trailing_ones=%d, total_zeros=%d",
                         debug_key, analysis.total_coeffs, analysis.total_coeffs_for_suffix,
                         analysis.trailing_ones, analysis.total_zeros)
            logger.debug("  Override: %s, nC=%s", override_total_coeffs, nC)

        # 1. Encode coeff_token
        coeff_token_code = find_coeff_token_code(
            analysis.total_coeffs,
            analysis.trailing_ones,
            nC
        )
        self.writer.write_bit_string(coeff_token_code)

        if analysis.total_coeffs == 0:
            return

        # 2. Encode trailing ones signs
        for sign in analysis.trailing_signs:
            self.writer.write_bit(1 if sign < 0 else 0)

        # 3. Encode levels (excluding trailing ones)
        self._encode_levels(analysis)

        # 4. Encode total_zeros (if not all coefficients)
        if analysis.total_coeffs < max_num_coeff:
            if debug_key and debug_key[0] == 0 and debug_key[1] == 0:
                logger.debug(f"      [CAVLC_ENC] total_zeros={analysis.total_zeros}, total_coeffs={analysis.total_coeffs}, max_num_coeff={max_num_coeff}")
                logger.debug(f"      [CAVLC_ENC] Constraint: total_zeros <= {max_num_coeff - analysis.total_coeffs}")

            # Validate total_zeros is within valid range for VLC tables
            # Correct formula: max total_zeros = max_num_coeff - TC
            # (there are TC non-zero coefficients, so at most max_num_coeff-TC zeros)
            max_tz = max_num_coeff - analysis.total_coeffs
            if analysis.total_zeros > max_tz:
                # This should not happen after our validation in _analyze_block,
                # but add safety check anyway
                logger.warning(f"      [WARN] total_zeros ({analysis.total_zeros}) > max ({max_tz}), clamping")
                analysis.total_zeros = max_tz
            elif analysis.total_zeros < 0:
                logger.warning(f"      [WARN] total_zeros ({analysis.total_zeros}) < 0, setting to 0")
                analysis.total_zeros = 0
            
            total_zeros_code = find_total_zeros_code(
                analysis.total_zeros,
                analysis.total_coeffs
            )
            self.writer.write_bit_string(total_zeros_code)
        
        # 5. Encode run_before values
        self._encode_run_before(analysis)
    
    def _analyze_block(self, coeffs: List[int], max_num_coeff: int, override_total_coeffs: int = None,
                       override_trailing_ones: int = None) -> BlockAnalysis:
        """
        Analyze coefficient block to extract encoding parameters

        Args:
            coeffs: Coefficients in zigzag order
            max_num_coeff: Maximum number of coefficients
            override_total_coeffs: If provided, use this total_coeffs for suffixLength calculation
                                   (used when re-encoding modified blocks to preserve bit length)
            override_trailing_ones: If provided, force this T1 count (capped at actual trailing ±1 count).
                                    Used by BitstreamPatcher to match original encoder's T1 choice.

        Returns:
            BlockAnalysis with all parameters
        """
        # CRITICAL FIX: Strip trailing zeros BEFORE processing
        # H.264 CAVLC only encodes coefficients up to the last non-zero
        # Trailing zeros are implicit (not encoded in bitstream)
        last_nonzero_idx = -1
        for i in range(len(coeffs) - 1, -1, -1):
            if coeffs[i] != 0:
                last_nonzero_idx = i
                break
        
        # If all coefficients are zero
        if last_nonzero_idx == -1:
            return BlockAnalysis(
                total_coeffs=0,
                total_coeffs_for_suffix=0,
                trailing_ones=0,
                trailing_signs=[],
                levels=[],
                total_zeros=0,
                runs=[]
            )
        
        # Only process coefficients up to last non-zero (inclusive)
        # This excludes trailing zeros which are NOT encoded in CAVLC
        active_coeffs = coeffs[:last_nonzero_idx + 1]
        
        # Find non-zero coefficients within active range
        non_zero_indices = [i for i, c in enumerate(active_coeffs) if c != 0]
        
        # CRITICAL: For re-encoding modified blocks, use override_total_coeffs for suffixLength
        # but actual total_coeffs for coeff_token encoding
        actual_total_coeffs = len(non_zero_indices)  # For coeff_token
        total_coeffs_for_suffix = override_total_coeffs if override_total_coeffs is not None else actual_total_coeffs
        
        # Sanity check (should never happen after stripping trailing zeros)
        if actual_total_coeffs == 0:
            return BlockAnalysis(
                total_coeffs=0,
                total_coeffs_for_suffix=0,
                trailing_ones=0,
                trailing_signs=[],
                levels=[],
                total_zeros=0,
                runs=[]
            )
        
        # Extract levels (values) in reverse zigzag order
        levels = [active_coeffs[i] for i in reversed(non_zero_indices)]
        
        # Count trailing ±1s (from highest frequency, max 3)
        trailing_ones = 0
        trailing_signs = []

        for level in levels:
            if abs(level) == 1 and trailing_ones < 3:
                trailing_ones += 1
                trailing_signs.append(level)
            else:
                break

        # Apply override_trailing_ones if provided
        # Cap at the actual count (can't claim more T1s than exist)
        if override_trailing_ones is not None:
            capped = min(override_trailing_ones, trailing_ones)
            trailing_ones = capped
            trailing_signs = trailing_signs[:capped]
        
        # Calculate total_zeros (H.264 Section 9.2.1)
        # total_zeros = number of zero-valued coefficients BEFORE the last non-zero coefficient
        # This is the number of zeros within the active range (already stripped trailing zeros)
        # = (last_active_position + 1) - total_coeffs
        # = len(active_coeffs) - total_coeffs
        # 
        # Example: [5,0,0,3]     -> total_coeffs=2, total_zeros=2 (positions 1,2)
        # Example: [0,0,5]       -> total_coeffs=1, total_zeros=2 (positions 0,1)
        # Example: [5]           -> total_coeffs=1, total_zeros=0
        # Example: [5,0,0,3,0,0,0,0] -> strip to [5,0,0,3], total_coeffs=2, total_zeros=2
        
        # Calculate run_before for each coefficient
        runs = []
        prev_idx = -1
        
        for idx in non_zero_indices:
            run = idx - prev_idx - 1
            runs.append(run)
            prev_idx = idx
        
        # Reverse runs to match encoding order (high freq first)
        runs = list(reversed(runs))
        
        # total_zeros = number of zeros within active coefficient range
        # = (length of active range) - (number of non-zero coeffs)
        # = len(active_coeffs) - total_coeffs
        # By definition: total_zeros = sum(runs)
        total_zeros = sum(runs)
        
        # VALIDATION: For active_coeffs of length N with actual_total_coeffs non-zero values:
        # max_total_zeros = N - actual_total_coeffs
        # Since we stripped trailing zeros, N = last_nonzero_idx + 1
        max_total_zeros = len(active_coeffs) - actual_total_coeffs
        
        # Sanity check: total_zeros should equal max by construction
        # (since active_coeffs has no trailing zeros)
        if total_zeros != max_total_zeros:
            logger.warning(f"[WARN] total_zeros mismatch: calculated={total_zeros}, max={max_total_zeros}")
            logger.debug(f"  active_coeffs length: {len(active_coeffs)}, actual_total_coeffs: {actual_total_coeffs}")
            logger.debug(f"  runs: {runs}, sum: {sum(runs)}")
        
        # Validate and clamp total_zeros ONLY if it will be encoded
        # (i.e., when actual_total_coeffs < max_num_coeff)
        # When all coefficients are non-zero (actual_total_coeffs == max_num_coeff),
        # total_zeros is not encoded, so no VLC constraint applies
        if actual_total_coeffs < max_num_coeff:
            # VLC table constraint: max total_zeros = max_num_coeff - TC
            vlc_max = max_num_coeff - actual_total_coeffs
            if total_zeros > vlc_max:
                logger.warning(f"[WARN] total_zeros ({total_zeros}) > VLC max ({vlc_max}) - clamping")
                # This should not happen after stripping trailing zeros
                # But clamp just in case
                excess = total_zeros - vlc_max
                total_zeros = vlc_max
                
                # Adjust runs to maintain sum = clamped total_zeros
                for i in range(len(runs) - 1, -1, -1):
                    if excess == 0:
                        break
                    reduction = min(runs[i], excess)
                    runs[i] -= reduction
                    excess -= reduction
        
        return BlockAnalysis(
            total_coeffs=actual_total_coeffs,  # Actual count for coeff_token
            total_coeffs_for_suffix=total_coeffs_for_suffix,  # Original or actual for suffixLength
            trailing_ones=trailing_ones,
            trailing_signs=trailing_signs,
            levels=levels,
            total_zeros=total_zeros,
            runs=runs
        )
    
    def _encode_levels(self, analysis: BlockAnalysis):
        """
        Encode coefficient levels with adaptive suffix length
        
        Reference: H.264 Section 9.2.2.1
        """
        # Skip trailing ones
        levels_to_encode = analysis.levels[analysis.trailing_ones:]
        
        if not levels_to_encode:
            return
        
        # Initialize suffix length per H.264 Section 9.2.2.1 EXACTLY
        # CRITICAL: Must match H.264 spec precisely for round-trip encoding!
        #
        # H.264 spec initialization:
        # if( TotalCoeff( coeff_token ) > 10 )
        #     suffixLength = 1
        # else
        #     suffixLength = 0
        # if( TotalCoeff( coeff_token ) > 3 && TrailingOnes( coeff_token ) == 3 )
        #     suffixLength++
        
        # Use total_coeffs_for_suffix (not total_coeffs) to preserve bit length
        # when re-encoding modified blocks with override_total_coeffs
        if analysis.total_coeffs_for_suffix > 10:
            suffixLength = 1
        else:
            suffixLength = 0
        
        # Special case: if total_coeffs > 3 and all 3 trailing ones present
        if analysis.total_coeffs_for_suffix > 3 and analysis.trailing_ones == 3:
            suffixLength += 1
        
        for i, level in enumerate(levels_to_encode):
            abs_level = abs(level)
            sign = 1 if level < 0 else 0
            
            # Calculate levelCode WITH sign embedded (H.264 Section 9.2.2.1 Table 9-6)
            if i == 0 and analysis.trailing_ones == 3:
                levelCode = (abs_level - 2) * 2 + sign
            else:
                levelCode = (abs_level - 1) * 2 + sign
            
            # suffixLength should already be set to avoid gaps for all levels in block
            
            # Determine levelPrefix and levelSuffixSize (H.264 Section 9.2.2.1)
            # Determine levelPrefix and levelSuffixSize (H.264 Section 9.2.2.1)
            if suffixLength == 0:
                if levelCode < 14:
                    levelPrefix = levelCode
                    levelSuffixSize = 0
                    levelSuffix = 0
                elif levelCode < 30:
                    levelPrefix = 14
                    levelSuffixSize = 4
                    levelSuffix = levelCode - 14
                else:
                    # Escape code for large values (prefix >= 15)
                    levelPrefix = 15
                    levelSuffixSize = 12
                    while True:
                        if levelPrefix == 15:
                            min_val = 30
                            max_val = 30 + 4095
                        else:
                            min_val = 30 + (1 << (levelPrefix - 3)) - 4096
                            max_val = min_val + (1 << (levelPrefix - 3)) - 1
                        
                        if levelCode <= max_val:
                            levelSuffix = levelCode - min_val
                            break
                        
                        levelPrefix += 1
                        levelSuffixSize += 1
            else:
                if levelCode < (15 << suffixLength):
                    levelPrefix = levelCode >> suffixLength
                    levelSuffixSize = suffixLength
                    levelSuffix = levelCode & ((1 << suffixLength) - 1)
                else:
                    # Escape code for large values (prefix >= 15)
                    levelPrefix = 15
                    levelSuffixSize = 12
                    base = 15 << suffixLength
                    while True:
                        if levelPrefix == 15:
                            min_val = base
                            max_val = base + 4095
                        else:
                            min_val = base + (1 << (levelPrefix - 3)) - 4096
                            max_val = min_val + (1 << (levelPrefix - 3)) - 1
                        
                        if levelCode <= max_val:
                            levelSuffix = levelCode - min_val
                            break
                        
                        levelPrefix += 1
                        levelSuffixSize += 1
            
            # Write level_prefix (unary)
            self.writer.write_unary(levelPrefix)
            
            # Write level_suffix
            if levelSuffixSize > 0:
                self.writer.write_bits(levelSuffixSize, levelSuffix)
            
            # NO SIGN BIT - sign is embedded in levelCode!
            
            # CRITICAL: Adaptive suffixLength update per H.264 Section 9.2.2.1
            # H.264 spec uses TWO SEPARATE if-statements (not if/elif):
            #   if (i==0 && suffixLength==0) suffixLength = 1;
            #   if (Abs(level[i]) > (3*(1<<(suffixLength-1))) && suffixLength<6)
            #       suffixLength++;
            # Using elif would skip the threshold check for i==0, causing encoder/
            # decoder to diverge from spec (and from FFmpeg) for large level[0] values.
            if suffixLength == 0:
                suffixLength = 1
            if abs_level > (3 << (suffixLength - 1)) and suffixLength < 6:
                suffixLength += 1

    
    def _encode_run_before(self, analysis: BlockAnalysis):
        """
        Encode run_before values
        
        Args:
            analysis: Block analysis with runs
        """
        zeros_left = analysis.total_zeros
        
        # Validate zeros_left is non-negative
        if zeros_left < 0:
            zeros_left = 0
        
        # Encode all runs except the last (which is implicit)
        for run in analysis.runs[:-1]:
            # H.264 spec: when zeros_left == 0, all remaining run_before values
            # are implicitly 0 (decoder stops reading; encoder must stop writing).
            if zeros_left == 0:
                break

            # H.264 spec: run_before is in range [0, zeros_left]
            # Note: run CAN equal zeros_left (all remaining zeros before this coeff)
            # So only clamp if run > zeros_left (strictly greater)
            if run > zeros_left:
                run = zeros_left
            
            run_before_code = find_run_before_code(run, zeros_left)
            self.writer.write_bit_string(run_before_code)
            zeros_left -= run
            
            # Prevent negative zeros_left
            if zeros_left < 0:
                zeros_left = 0
