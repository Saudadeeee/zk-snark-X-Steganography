import sys
sys.path.append('.')
from e2e_extraction_test import parse_video
print('Parsing modified video...')
try:
    b, o, m = parse_video('data/output/e2e_embed_output.h264', max_slices=15)
except Exception as e:
    print('Failed:', e)

print('MODIFIED VIDEO OFFSETS:')
for k in sorted(o.keys()):
    if k[0] == 4776:
        print('MODIFIED:', k, o[k]['bit_length'], 'bits')
