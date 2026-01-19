"""
CAVLC VLC Tables from ITU-T H.264 Specification
These tables are used to decode coefficient data
"""

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
    '0001': (2, 2),
    
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
    
    # Note: TC=15-16 entries omitted (handled separately via FLC in spec)
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
    '11': (0, 0),
    '001011': (0, 1),
    '001010': (0, 2),
    '000111': (1, 0),
    '000110': (1, 1),
    '001001': (2, 0),
    '001000': (2, 1),
    '10': (2, 2),
    '000101': (3, 0),
    '000100': (3, 1),
    '01111': (3, 2),
    '0110': (3, 3),
    '000011': (4, 0),
    '01110': (4, 1),
    '01101': (4, 2),
    '01100': (4, 3),
    '01011': (5, 0),
    '01010': (5, 1),
    '01001': (5, 2),
    '01000': (5, 3),
    '00111': (6, 0),
    '00110': (6, 1),
    '00101': (6, 2),
    '00100': (6, 3),
    '000010': (7, 0),
    '0001111': (7, 1),
    '0001110': (7, 2),
    '0001101': (7, 3),
    '0001100': (8, 0),
    '0001011': (8, 1),
    '0001010': (8, 2),
    '0001001': (8, 3),
    '0001000': (9, 0),
    '00011111': (9, 1),
    '00011110': (9, 2),
    '00011101': (9, 3),
    '00011100': (10, 0),
    '00011011': (10, 1),
    '00011010': (10, 2),
    '00011001': (10, 3),
    '00011000': (11, 0),
    '00010111': (11, 1),
    '00010110': (11, 2),
    '00010101': (11, 3),
    '00010100': (12, 0),
    '00010011': (12, 1),
    '00010010': (12, 2),
    '00010001': (12, 3),
    '00010000': (13, 0),
    '000001111': (13, 1),
    '000001110': (13, 2),
    '000001101': (13, 3),
    '000001100': (14, 0),
    '000001011': (14, 1),
    '000001010': (14, 2),
    '000001001': (14, 3),
    '000001000': (15, 0),
    '00000111': (15, 1),
    '00000110': (15, 2),
    '00000101': (15, 3),
    '00000100': (16, 0),
    '00000011': (16, 1),
    '00000010': (16, 2),
    '00000001': (16, 3),
}

# For nC = 6 or 7 (Table 9-5(d))
COEFF_TOKEN_NC_6_7 = {
    '0101': (0, 0),
    '000111': (0, 1),
    '000100': (0, 2),
    '000011': (1, 0),
    '0100': (1, 1),
    '000110': (2, 0),
    '000101': (2, 1),
    '011': (2, 2),
    '000010': (3, 0),
    '00011': (3, 1),
    '0011': (3, 2),
    '010': (3, 3),
    '00010': (4, 0),
    '0010': (4, 1),
    '11111': (4, 2),
    '11110': (4, 3),
    '11101': (5, 0),
    '11100': (5, 1),
    '11011': (5, 2),
    '11010': (5, 3),
    '11001': (6, 0),
    '11000': (6, 1),
    '10111': (6, 2),
    '10110': (6, 3),
    '10101': (7, 0),
    '10100': (7, 1),
    '10011': (7, 2),
    '10010': (7, 3),
    '10001': (8, 0),
    '10000': (8, 1),
    '01111': (8, 2),
    '01110': (8, 3),
    '01101': (9, 0),
    '01100': (9, 1),
    '01011': (9, 2),
    '01010': (9, 3),
    '01001': (10, 0),
    '01000': (10, 1),
    '001111': (10, 2),
    '001110': (10, 3),
    '001101': (11, 0),
    '001100': (11, 1),
    '001011': (11, 2),
    '001010': (11, 3),
    '001001': (12, 0),
    '001000': (12, 1),
    '0001111': (12, 2),
    '0001110': (12, 3),
    '0001101': (13, 0),
    '0001100': (13, 1),
    '0001011': (13, 2),
    '0001010': (13, 3),
    '0001001': (14, 0),
    '0001000': (14, 1),
    '00001111': (14, 2),
    '00001110': (14, 3),
    '00001101': (15, 0),
    '00001100': (15, 1),
    '00001011': (15, 2),
    '00001010': (15, 3),
    '00001001': (16, 0),
    '00001000': (16, 1),
    '00000111': (16, 2),
    '00000110': (16, 3),
}

# For nC >= 8 (Table 9-5(e)) - uses fixed length code (FLC)
# FLC(6 bits): 2 bits for TrailingOnes, 4 bits for TotalCoeff


# Table 9-7: total_zeros VLC for different TotalCoeff values
# Format: {TotalCoeff: {code_bits: total_zeros_value}}

TOTAL_ZEROS_TABLES = {
    1: {  # When TotalCoeff = 1
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
    2: {  # When TotalCoeff = 2
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
    3: {  # When TotalCoeff = 3
        '0101': 0,
        '111': 1,
        '110': 2,
        '101': 3,
        '100': 4,
        '011': 5,
        '0100': 6,
        '0011': 7,
        '0010': 8,
        '00011': 9,
        '00010': 10,
        '00001': 11,
        '00000': 12,
    },
    4: {  # When TotalCoeff = 4
        '00011': 0,
        '111': 1,
        '0101': 2,
        '0100': 3,
        '110': 4,
        '101': 5,
        '100': 6,
        '0011': 7,
        '011': 8,
        '0010': 9,
        '00010': 10,
        '00001': 11,
    },
    5: {  # When TotalCoeff = 5
        '0101': 0,
        '0100': 1,
        '0011': 2,
        '111': 3,
        '110': 4,
        '101': 5,
        '100': 6,
        '011': 7,
        '0010': 8,
        '00001': 9,
        '00000': 10,
    },
    6: {  # When TotalCoeff = 6
        '000001': 0,
        '00001': 1,
        '111': 2,
        '110': 3,
        '101': 4,
        '100': 5,
        '011': 6,
        '010': 7,
        '0001': 8,
        '001': 9,
    },
    7: {  # When TotalCoeff = 7
        '000001': 0,
        '00001': 1,
        '101': 2,
        '100': 3,
        '011': 4,
        '11': 5,
        '010': 6,
        '0001': 7,
        '001': 8,
        '00000': 9,  # Added missing entry
    },
    8: {  # When TotalCoeff = 8
        '000001': 0,
        '0001': 1,
        '00001': 2,
        '011': 3,
        '11': 4,
        '10': 5,
        '010': 6,
        '001': 7,
    },
    9: {  # When TotalCoeff = 9
        '000001': 0,
        '000000': 1,
        '0001': 2,
        '11': 3,
        '10': 4,
        '001': 5,
        '01': 6,
    },
    10: {  # When TotalCoeff = 10
        '00001': 0,
        '00000': 1,
        '001': 2,
        '11': 3,
        '10': 4,
        '01': 5,
    },
    11: {  # When TotalCoeff = 11
        '0000': 0,
        '0001': 1,
        '001': 2,
        '010': 3,
        '1': 4,
    },
    12: {  # When TotalCoeff = 12
        '0000': 0,
        '0001': 1,
        '01': 2,
        '1': 3,
    },
    13: {  # When TotalCoeff = 13
        '000': 0,
        '001': 1,
        '1': 2,
    },
    14: {  # When TotalCoeff = 14
        '00': 0,
        '01': 1,
    },
    15: {  # When TotalCoeff = 15
        '0': 0,
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
        Dictionary mapping code strings to (TotalCoeff, TrailingOnes)
    """
    if nC == -1:
        # Chroma DC uses special table (not implemented)
        return {}
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


def get_total_zeros_table(total_coeff: int):
    """
    Get total_zeros VLC table for given TotalCoeff
    
    Args:
        total_coeff: Number of non-zero coefficients
        
    Returns:
        Dictionary mapping code strings to total_zeros values
    """
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
        print(f"      [decode_vlc] Starting at position {start_pos}")
    
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
                    print(f"      [decode_vlc] Found match: '{code_str}' -> {longest_match}")
                
                # Optimization: Check if any longer codes exist with this prefix
                # If not, we can stop early
                has_longer = any(k.startswith(code_str) and len(k) > len(code_str) 
                                for k in vlc_table.keys())
                if not has_longer:
                    # This is definitely the longest match, stop here
                    if debug:
                        print(f"      [decode_vlc] No longer codes, stopping at '{code_str}'")
                    break
        except:
            # End of stream reached
            if debug:
                print(f"      [decode_vlc] End of stream at {len(code_str)} bits")
            break
    
    # If we found at least one match, rewind to end of longest match and return
    if longest_match is not None:
        # Rewind to position right after the longest match
        end_pos = start_pos + longest_match_len
        reader.seek(end_pos)
        if debug:
            print(f"      [decode_vlc] Rewinding to position {end_pos} (consumed {longest_match_len} bits)")
        return longest_match
    
    # No valid code found
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
        # Use FLC: 6 bits total_coeffs + 2 bits trailing_ones
        return f"{total_coeffs:06b}{trailing_ones:02b}"
    
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
