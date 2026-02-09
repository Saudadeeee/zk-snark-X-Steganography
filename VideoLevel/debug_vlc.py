"""Debug VLC decoding logic"""
import sys
sys.path.insert(0, '.')

from src.zk_mv_stego.bitstream.cavlc_tables import COEFF_TOKEN_NC_0_1, COEFF_TOKEN_NC_2_3

# Test multiple error codes from actual failures
test_codes = [
    ('0011001101100011', 0, COEFF_TOKEN_NC_0_1),  # nC=0
    ('0011001101110111', 1, COEFF_TOKEN_NC_0_1),  # nC=1
    ('0011000110010011', -2, COEFF_TOKEN_NC_0_1), # nC=-2
]

for code, nC, vlc_table in test_codes:
    print(f'\n{"="*60}')
    print(f'Testing code: {code} (nC={nC})')
    print(f'{"="*60}')
    
    code_str = ''
    longest_match = None
    longest_match_len = 0
    max_bits = min(len(code), 16)
    
    for i in range(max_bits):
        bit = code[i]
        code_str += bit  
        
        # Check if current code_str is in table
        if code_str in vlc_table:
            longest_match = vlc_table[code_str]
            longest_match_len = len(code_str)
            print(f'Bit {i+1}: code_str="{code_str}" MATCH: {longest_match}')
            
            # Check if any longer codes exist with this prefix
            has_longer = any(k.startswith(code_str) and len(k) > len(code_str) 
                            for k in vlc_table.keys())
            print(f'  has_longer={has_longer}')
            if not has_longer:
                print(f'  → Would stop here and return {longest_match}')
                break
        else:
            if i < 10:  # Only print first 10
                print(f'Bit {i+1}: code_str="{code_str}" no match')
    
    print(f'\nFinal: longest_match={longest_match}, len={longest_match_len}')
    if longest_match:
        print(f'✅ SUCCESS: Would return {longest_match} (consumed {longest_match_len} bits)')
    else:
        print(f'❌ FAILURE: No match found for code: {code_str}')

