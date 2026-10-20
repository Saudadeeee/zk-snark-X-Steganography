# Lattice-ZK evaluation summary (generated)

## End-to-end runs

| Case | Mode | Envelope (B) | Carriers | Verified | Replay rej. | Tamper rej. | PSNR mod. (dB) | Worst (dB) | Frames mod. | SSIM | Embed (s) | Verify (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| city4cif_q22_reg | registered | 7589 | 61008 | yes | yes | yes | 43.66 | 39.31 | 100/600 | 0.99995 | 881 | 584 |
| city_cif_q22_reg | registered | 7589 | 61600 | yes | -- | -- | 45.35 | 38.81 | 300/300 | 0.99969 | 903 | 286 |
| city_cif_q22_reg_t1 | registered | 7589 | 61008 | yes | -- | -- | 44.09 | 40.65 | 100/300 | 0.99937 | 1338 | 816 |
| city_cif_q22_reg_t1_spread | registered | 7589 | 61600 | yes | -- | -- | 48.79 | 44.57 | 300/300 | 0.99937 | 2197 | 2395 |
| coastguard3000f_q22_inband_link | in-band | 14309 | 118024 | yes | yes | yes | 45.10 | 36.02 | 1200/3000 | 0.99992 | 5409 | 1707 |
| coastguard3000f_q22_reg | registered | 7589 | 62784 | yes | yes | yes | 45.26 | 35.66 | 694/3000 | 0.99996 | 2164 | 740 |
| coastguard_cif_q22_reg | registered | 7589 | 61304 | yes | -- | -- | 39.97 | 33.48 | 200/300 | 0.99958 | 702 | 271 |
| coastguard_cif_q22_reg_t1 | registered | 7589 | 61008 | yes | -- | -- | 41.01 | 36.80 | 100/300 | 0.99877 | 857 | 520 |
| coastguard_cif_q22_reg_t1_spread | registered | 7589 | 61304 | yes | -- | -- | 43.28 | 38.49 | 200/300 | 0.99805 | 1570 | 1057 |
| container_cif_q18_inband | in-band | 14309 | 115064 | yes | -- | -- | 44.12 | 38.42 | 200/300 | 0.99980 | 678 | 465 |
| container_cif_q18_reg | registered | 7589 | 61008 | yes | -- | -- | 43.94 | 36.41 | 100/300 | 0.99989 | 334 | 127 |
| container_cif_q22_inband | in-band | 14309 | 115360 | yes | yes | yes | 40.26 | 32.13 | 300/300 | 0.99949 | 719 | 466 |
| container_cif_q22_reg | registered | 7589 | 61304 | yes | yes | yes | 42.07 | 34.02 | 200/300 | 0.99975 | 580 | 182 |
| container_cif_q22_reg_t1 | registered | 7589 | 61008 | yes | -- | -- | 42.34 | 39.15 | 100/300 | 0.99855 | 892 | 558 |
| container_cif_q22_reg_t1_spread | registered | 7589 | 61304 | yes | -- | -- | 45.69 | 41.48 | 200/300 | 0.99848 | 1275 | 788 |
| container_cif_q22_reg_t1v2_spread | registered | 7589 | 61304 | yes | -- | -- | 45.20 | 40.21 | 200/300 | 0.99844 | 1015 | 953 |
| deadline_cif_q22_reg | registered | 7589 | 62784 | yes | yes | yes | 44.99 | 34.19 | 684/1000 | 0.99984 | 1793 | 1261 |
| hall_cif_q22_reg | registered | 7589 | 61600 | yes | -- | -- | 41.48 | 32.72 | 300/300 | 0.99911 | 613 | 238 |
| hall_cif_q22_reg_t1_spread | registered | 7589 | 61600 | yes | -- | -- | 47.25 | 41.01 | 300/300 | 0.99749 | 2329 | 1398 |
| hall_monitor_cif_q22_reg_t1 | registered | 7589 | 61008 | yes | -- | -- | 42.25 | 37.74 | 100/300 | 0.99784 | 887 | 519 |
| harbour4cif_q22_inband | in-band | 14309 | 115360 | yes | -- | -- | 41.16 | 33.15 | 300/600 | 0.99987 | 3760 | 1108 |
| harbour4cif_q22_reg | registered | 7589 | 61304 | yes | -- | -- | 42.83 | 32.91 | 200/600 | 0.99994 | 2357 | 1954 |

## Carrier capacity

| Video | Frames | Min bits/100 fr. | Mean bits/100 fr. | Total bits | Registered fits | In-band fits |
|---|---|---|---|---|---|---|
| city_4cif_q22_g1.h264 | 600 | 68084 | 82265 | 246794 | yes | yes |
| city_cif_q22_g1.h264 | 300 | 537034 | 537034 | 537034 | yes | yes |
| city_cif_q22_g1.h264 | 300 | 21697 | 23836 | 71508 | yes | no |
| coastguard_cif_q22_g1.h264 | 300 | 549737 | 549737 | 549737 | yes | yes |
| coastguard_cif_q22_g1.h264 | 300 | 31404 | 36331 | 108994 | yes | no |
| container_cif_q18_g1.h264 | 300 | 86320 | 88305 | 264914 | yes | yes |
| container_cif_q22_g1.h264 | 300 | 467583 | 467583 | 467583 | yes | yes |
| container_cif_q18_g1.h264 | 300 | 86320 | 88305 | 264914 | yes | yes |
| container_cif_q22_g1.h264 | 300 | 47866 | 49768 | 149305 | yes | yes |
| container_cif_q28_g1.h264 | 300 | 9110 | 10015 | 30044 | no | no |
| crew_4cif_q22_g1.h264 | 600 | 11093 | 13236 | 39707 | no | no |
| football_cif_q22_g1.h264 | 260 | 14295 | 21554 | 64663 | yes | no |
| hall_monitor_cif_q22_g1.h264 | 300 | 468519 | 468519 | 468519 | yes | yes |
| hall_monitor_cif_q22_g1.h264 | 300 | 27065 | 27611 | 82832 | yes | no |
| harbour_4cif_q22_g1.h264 | 600 | 48816 | 49976 | 199905 | yes | yes |
| harbour_4cif_q22_g1.h264 | 600 | 48816 | 49357 | 148072 | yes | yes |
| akiyo_cif_q22_g1.h264 | 300 | 10501 | 10501 | 10501 | no | no |
| deadline_cif_q22_g1.h264 | 1374 | 46589 | 46589 | 46589 | no | no |
| foreman_cif_q22_g1.h264 | 300 | 14071 | 14071 | 14071 | no | no |
| soccer_4cif_q22_g1.h264 | 600 | 3501 | 30010 | 90030 | yes | no |

## Targeted classical steganalysis

| Case | PoV P(embed) cover | PoV P(embed) stego | Magnitude hist. p | T1 sign p | SPA cover | SPA stego |
|---|---|---|---|---|---|---|
| city4cif_q22_reg | 0.000 | 0.000 | 0.998 | 1.000 | 0.39448 | 0.39456 |
| city_cif_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.40765 | 0.40772 |
| city_cif_q22_reg_t1 | 0.000 | 0.000 | 1.000 | 0.119 | 0.40765 | 0.40857 |
| city_cif_q22_reg_t1_spread | 0.000 | 0.000 | 1.000 | 0.475 | 0.40765 | 0.40803 |
| coastguard3000f_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.40661 | 0.40664 |
| coastguard_cif_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.40661 | 0.40671 |
| coastguard_cif_q22_reg_t1 | 0.000 | 0.000 | 1.000 | 0.176 | 0.40661 | 0.40704 |
| coastguard_cif_q22_reg_t1_spread | 0.000 | 0.000 | 1.000 | 0.805 | 0.40661 | 0.40684 |
| container_cif_q18_inband | 0.000 | 0.000 | 1.000 | 1.000 | 0.33144 | 0.33156 |
| container_cif_q18_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.33144 | 0.33165 |
| container_cif_q22_inband | 0.000 | 0.000 | 1.000 | 1.000 | 0.27711 | 0.27752 |
| container_cif_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.27711 | 0.27729 |
| container_cif_q22_reg_t1 | 0.000 | 0.000 | 1.000 | 0.061 | 0.27711 | 0.27788 |
| container_cif_q22_reg_t1_spread | 0.000 | 0.000 | 1.000 | 0.283 | 0.27711 | 0.27759 |
| container_cif_q22_reg_t1v2_spread | 0.000 | 0.000 | 1.000 | 0.139 | 0.27711 | 0.27753 |
| deadline_cif_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.28793 | 0.28810 |
| hall_cif_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.26447 | 0.26538 |
| hall_cif_q22_reg_t1_spread | 0.000 | 0.000 | 1.000 | 0.419 | 0.25033 | 0.25206 |
| hall_monitor_cif_q22_reg_t1 | 0.000 | 0.000 | 1.000 | 0.173 | 0.25033 | 0.25419 |
| harbour4cif_q22_inband | 0.000 | 0.000 | 1.000 | 1.000 | 0.42423 | 0.42431 |
| harbour4cif_q22_reg | 0.000 | 0.000 | 1.000 | 1.000 | 0.42423 | 0.42435 |

## Learned steganalysis (1300 frame pairs, clips: city, coastguard, container, deadline, hall_monitor)

| Protocol | Features / detector | P_E | AUC |
|---|---|---|---|
| paired_half_split | coefficient/logistic | 0.414 | 0.617 |
| paired_half_split | coefficient/fld_ensemble | 0.394 | 0.638 |
| paired_half_split | pixel/logistic | 0.424 | 0.608 |
| paired_half_split | pixel/fld_ensemble | 0.410 | 0.627 |
| paired_half_split | combined/logistic | 0.401 | 0.633 |
| paired_half_split | combined/fld_ensemble | 0.357 | 0.685 |
| leave_one_clip_out | coefficient/logistic | 0.407 | 0.604 |
| leave_one_clip_out | coefficient/fld_ensemble | 0.399 | 0.628 |
| leave_one_clip_out | pixel/logistic | 0.454 | 0.538 |
| leave_one_clip_out | pixel/fld_ensemble | 0.458 | 0.536 |
| leave_one_clip_out | combined/logistic | 0.437 | 0.575 |
| leave_one_clip_out | combined/fld_ensemble | 0.422 | 0.583 |

## Baselines

| Scheme | PQ | ZK | In-video bytes | Prove (ms) | Verify (ms) | Setup |
|---|---|---|---|---|---|---|
| BDLOP (this work, registered) | yes | yes | 7589 | 187 | 41.9 | transparent |
| BDLOP (this work, in-band) | yes | yes | 14309 | 187 | 41.9 | transparent |
| Groth16 (BN128) | no | yes | 147 | 7222 | 2550 | trusted, per circuit |
| ML-DSA-44 (signature) | yes | no | 2420 | 18.6 | 0.33 | none |
| ISW21 (recorded) | broken KS assumption | stat. 2^-40 | 23907 | 328 | 0.6 | trusted, designated verifier |
