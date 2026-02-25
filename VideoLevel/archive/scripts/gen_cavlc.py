import sys
import os
sys.path.append('.')
sys.path.append('temp_h264_repo')
from temp_h264_repo.h264bits import H264Bits

# tb in their code: 
# (t1s, tc)
# tb = [(0,0),(0,1),(1,1),(0,2),(1,2),(2,2)]
# So for their tb[1] which is (0,1), t1s=0, tc=1.
tb = [(0,0),(0,1),(1,1),(0,2),(1,2),(2,2)]
def get_t1s_tc(idx):
    if idx < 6: return tb[idx]
    else: return ((idx-6)%4, (idx-6)//4+3)

with open('generated_cavlc.py', 'w') as f:
    f.write('COEFF_TOKEN_NC_0_1 = {\n')
    for idx, token in enumerate(H264Bits.T1s_TC_coeff_token[0]):
        t1s, tc = get_t1s_tc(idx)
        # Dictionary format wants: code: (TotalCoeff, TrailingOnes)
        f.write(f"    '{token}': ({tc}, {t1s}),\n")
    f.write('}\n\n')

    f.write('COEFF_TOKEN_NC_4_5 = {\n')
    for idx, token in enumerate(H264Bits.T1s_TC_coeff_token[2]):
        t1s, tc = get_t1s_tc(idx)
        f.write(f"    '{token}': ({tc}, {t1s}),\n")
    f.write('}\n\n')

    f.write('COEFF_TOKEN_NC_6_7 = {\n')
    for idx, token in enumerate(H264Bits.T1s_TC_coeff_token[3]):
        t1s, tc = get_t1s_tc(idx)
        f.write(f"    '{token}': ({tc}, {t1s}),\n")
    f.write('}\n\n')

print('Generated mapping dicts successfully!')
