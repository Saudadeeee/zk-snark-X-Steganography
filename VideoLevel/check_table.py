"""Check COEFF_TOKEN_NC_0_1 table for codes starting with '001'"""
import sys
sys.path.insert(0, '.')

from src.zk_mv_stego.bitstream.cavlc_tables import COEFF_TOKEN_NC_0_1

print(f"Total codes in COEFF_TOKEN_NC_0_1: {len(COEFF_TOKEN_NC_0_1)}")
print("\nCodes starting with '001':")
codes = [k for k in COEFF_TOKEN_NC_0_1.keys() if k.startswith('001')]
for k in sorted(codes, key=len):
    print(f"  '{k}': {COEFF_TOKEN_NC_0_1[k]}")

print("\nCodes starting with '00':")
codes = [k for k in COEFF_TOKEN_NC_0_1.keys() if k.startswith('00') and not k.startswith('001')]
for k in sorted(codes, key=len)[:10]:  # First 10
    print(f"  '{k}': {COEFF_TOKEN_NC_0_1[k]}")
