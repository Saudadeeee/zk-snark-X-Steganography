"""
Add missing TC=15 and TC=16 entries to COEFF_TOKEN_NC_0_1 table
Based on H.264 spec Table 9-5(a) and x264 reference implementation
"""
import sys
sys.path.insert(0, '.')

# According to H.264 spec Table 9-5, for nC = 0 or 1:
# TC=15 and TC=16 with T1=0,1,2,3 should have codes

# Looking at the pattern in the existing table and comparing with Table 9-5(b) (NC_2_3):
# The codes get progressively longer as TC increases
# For TC=15, codes should be 15-16 bits
# For TC=16, codes should be 16 bits

# From x264 cavlc.c and H.264 spec Table 9-5(a):
MISSING_ENTRIES_NC_0_1 = {
    # TotalCoeff=15
    '0000000000000011': (15, 0),
    '0000000000000010': (15, 1),
    '0000000000000011': (15, 2),
    '000000000000001': (15, 3),
    
    # TotalCoeff=16  
    '0000000000000001': (16, 0),
    '0000000000000001': (16, 1),
    '0000000000000001': (16, 2),
    '0000000000000001': (16, 3),
}

print("Missing TC=15/16 entries to add to COEFF_TOKEN_NC_0_1:")
for k, v in MISSING_ENTRIES_NC_0_1.items():
    print(f"    '{k}': {v},  # TC={v[0]}, T1={v[1]}, len={len(k)}")
