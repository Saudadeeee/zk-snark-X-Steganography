# Carrier comparison: magnitude-LSB vs trailing-one sign (generated)

Paired clips: city_cif_q22_reg, coastguard_cif_q22_reg, container_cif_q22_reg, hall_cif_q22_reg

| Case | Carrier | Verified | Capacity (kbit/100 fr.) | Segments | Frames mod. | PSNR mod. | Worst | SSIM | Embed (s) | Verify (s) | T1-sign p | Pos.-sign p | PoV stego | Mag. hist p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| city_cif_q22_reg | magnitude | yes | 21.7 | 3 | 300 | 45.35 | 38.81 | 0.99969 | 903 | 286 | 1.000 | 1.000 | 0.000 | 1.000 |
| city_cif_q22_reg | t1 | yes | 537.0 | 1 | 100 | 44.09 | 40.65 | 0.99937 | 1338 | 816 | 0.119 | 0.998 | 0.000 | 1.000 |
| city_cif_q22_reg | t1-spread | yes | 537.0 | 3 | 300 | 48.79 | 44.57 | 0.99937 | 2197 | 2395 | 0.475 | 1.000 | 0.000 | 1.000 |
| coastguard_cif_q22_reg | magnitude | yes | 31.4 | 2 | 200 | 39.97 | 33.48 | 0.99958 | 702 | 271 | 1.000 | 1.000 | 0.000 | 1.000 |
| coastguard_cif_q22_reg | t1 | yes | 549.7 | 1 | 100 | 41.01 | 36.80 | 0.99877 | 857 | 520 | 0.176 | 0.997 | 0.000 | 1.000 |
| coastguard_cif_q22_reg | t1-spread | yes | 549.7 | 2 | 200 | 43.28 | 38.49 | 0.99805 | 1570 | 1057 | 0.805 | 1.000 | 0.000 | 1.000 |
| container_cif_q22_reg | magnitude | yes | 47.9 | 2 | 200 | 42.07 | 34.02 | 0.99975 | 580 | 182 | 1.000 | 1.000 | 0.000 | 1.000 |
| container_cif_q22_reg | t1 | yes | 467.6 | 1 | 100 | 42.34 | 39.15 | 0.99855 | 892 | 558 | 0.061 | 0.457 | 0.000 | 1.000 |
| container_cif_q22_reg | t1-spread | yes | 467.6 | 2 | 200 | 45.69 | 41.48 | 0.99848 | 1275 | 788 | 0.283 | 0.981 | 0.000 | 1.000 |
| hall_cif_q22_reg | magnitude | yes | 27.1 | 3 | 300 | 41.48 | 32.72 | 0.99911 | 613 | 238 | 1.000 | 1.000 | 0.000 | 1.000 |
| hall_cif_q22_reg | t1 | yes | 468.5 | 1 | 100 | 42.25 | 37.74 | 0.99784 | 887 | 519 | 0.173 | 0.001 | 0.000 | 1.000 |
| hall_cif_q22_reg | t1-spread | yes | 468.5 | 3 | 300 | 47.25 | 41.01 | 0.99749 | 2329 | 1398 | 0.419 | 0.997 | 0.000 | 1.000 |

## Learned steganalysis (P_E; 0.5 = chance)

| Carrier | Frame pairs | Coefficient LOCO | Combined LOCO | Pixel LOCO | Combined paired |
|---|---|---|---|---|---|
| magnitude | 1000 | 0.386 | 0.416 | 0.456 | 0.339 |
| t1 | 400 | 0.446 | 0.314 | 0.310 | 0.193 |
| t1-spread | 1000 | 0.471 | 0.401 | 0.404 | 0.317 |
