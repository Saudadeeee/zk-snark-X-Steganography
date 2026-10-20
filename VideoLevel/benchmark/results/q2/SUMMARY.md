# Lattice-ZK evaluation summary (generated)

## End-to-end runs

| Case | Mode | Envelope (B) | Carriers | Verified | Replay rej. | Tamper rej. | PSNR mod. (dB) | Worst (dB) | Frames mod. | SSIM | Embed (s) | Verify (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| coastguard3000f_q22_reg | registered | 7589 | 62784 | yes | yes | yes | -- | -- | --/-- | 0.99996 | 2164 | 740 |
| deadline_cif_q22_reg | registered | 7589 | 62784 | yes | yes | yes | -- | -- | --/-- | 0.99984 | 1793 | 1261 |

## Carrier capacity

| Video | Frames | Min bits/100 fr. | Mean bits/100 fr. | Total bits | Registered fits | In-band fits |
|---|---|---|---|---|---|---|
| akiyo_cif_q22_g1.h264 | 300 | 10501 | 10501 | 10501 | no | no |
| city_cif_q22_g1.h264 | 300 | 25238 | 25238 | 25238 | no | no |
| coastguard_cif_q22_g1.h264 | 300 | 31404 | 31404 | 31404 | no | no |
| container_cif_q22_g1.h264 | 300 | 50757 | 50757 | 50757 | no | no |
| deadline_cif_q22_g1.h264 | 1374 | 46589 | 46589 | 46589 | no | no |
| football_cif_q22_g1.h264 | 260 | 24059 | 24059 | 24059 | no | no |
| foreman_cif_q22_g1.h264 | 300 | 14071 | 14071 | 14071 | no | no |
| hall_monitor_cif_q22_g1.h264 | 300 | 27065 | 27065 | 27065 | no | no |

## Baselines

| Scheme | PQ | ZK | In-video bytes | Prove (ms) | Verify (ms) | Setup |
|---|---|---|---|---|---|---|
| BDLOP (this work, registered) | yes | yes | 7589 | 187 | 41.9 | transparent |
| BDLOP (this work, in-band) | yes | yes | 14309 | 187 | 41.9 | transparent |
| Groth16 (BN128) | no | yes | 147 | 7222 | 2550 | trusted, per circuit |
| ML-DSA-44 (signature) | yes | no | 2420 | 18.6 | 0.33 | none |
| ISW21 (recorded) | broken KS assumption | stat. 2^-40 | 23907 | 328 | 0.6 | trusted, designated verifier |
