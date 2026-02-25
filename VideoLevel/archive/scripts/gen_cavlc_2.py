import sys
import os
sys.path.append('.')
sys.path.append('temp_h264_repo')
from temp_h264_repo.h264bits import H264Bits

tb = [(0,0),(0,1),(1,1),(0,2),(1,2),(2,2)]
def get_t1s_tc(idx):
    if idx < 6: return tb[idx]
    else: return ((idx-6)%4, (idx-6)//4+3)

with open('generated_cavlc_2.py', 'w') as f:
    f.write('COEFF_TOKEN_NC_2_3 = {\n')
    for idx, token in enumerate(H264Bits.T1s_TC_coeff_token[1]):
        t1s, tc = get_t1s_tc(idx)
        f.write(f"    '{token}': ({tc}, {t1s}),\n")
    f.write('}\n\n')

    # Chroma DC:
    # 0 -> 4 max coeff. The PyH264 lists 14 values for NC=-1
    # 0:1, 1:01, 2:001, 3:0001, 4:000001 (This is for 2x2. TC max is 4)
    # The get_t1s_tc function used the same indices logic for NC=-1? 
    # Yes, ce_coeff_token(self, nC) uses `tb = [(0,0),(0,1),(1,1),(0,2),(1,2),(2,2)]`.
    # And then `(idx-6)%4, (idx-6)//4+3`. 
    # Let's see if 14 items fit: 14 items means max index is 13.
    # tc = (13-6)//4 + 3 = 7//4 + 3 = 1+3 = 4. 
    # So max TC is 4, which perfectly matches Chroma DC 2x2 blocks (max 4 coeffs).
    f.write('COEFF_TOKEN_CHROMA_DC = {\n')
    for idx, token in enumerate(H264Bits.T1s_TC_coeff_token[4]):
        t1s, tc = get_t1s_tc(idx)
        f.write(f"    '{token}': ({tc}, {t1s}),\n")
    f.write('}\n\n')

    f.write('COEFF_TOKEN_CHROMA_DC_422 = {\n')
    for idx, token in enumerate(H264Bits.T1s_TC_coeff_token[5]):
        t1s, tc = get_t1s_tc(idx)
        f.write(f"    '{token}': ({tc}, {t1s}),\n")
    f.write('}\n\n')

print('Generated mapping dicts successfully!')
