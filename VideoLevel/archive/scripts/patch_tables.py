import sys
import os

with open('src/zk_mv_stego/bitstream/cavlc_tables.py', 'r') as f:
    text = f.read()

# I need to fix the known 13 clashes
text = text.replace("'0001': (2, 2),", "'000111': (2, 2),")
# Looking at NC_0_1, Total 15 T1=3. If (16,3) is 1100, then (15,3) is 1101.
text = text.replace("'000000000000110': (15, 3),", "'0000000000001101': (15, 3),")

# NC 4,5 fixes
text = text.replace("'0110': (3, 3),", "'011011': (3, 3),")
text = text.replace("'00101': (6, 2),", "'0010111': (6, 2),")
text = text.replace("'00100': (6, 3),", "'0010011': (6, 3),")
# '000111': (1,0) conflicts with '0001111' (7,1). The fix is prepending extra bits, or padding. 
# Looking at H.264 table 9-5 for NC_4_5, TotalCoeff=1, T1=0 is actualy 000111, meaning 7,1 is WRONG, not 1,0. 
# Re-analyzing... Wait, if I am guessing the mappings I might break it worse.
# Since my generated scripts produced 100% prefix-free tables, I should just map the generated ones safely, by copying them instead of using regex.

with open('patch_tables.py', 'w') as f:
    f.write('x')
