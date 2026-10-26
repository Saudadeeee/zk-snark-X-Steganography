"""Robust (semi-fragile) carrier mode for the lattice video proof.

The fragile mode (``src.lattice_zk.video_pipeline``) binds the exact H.264
bitstream; one re-encode destroys it.  This package carries the same BDLOP
envelope in the *decoded* picture instead: dithered quantization-index
modulation on low-order DCT coefficients of 16x16 luma blocks, repeated over
temporal groups and protected by a convolutional code, so the proof survives
re-compression at the same resolution with any codec ffmpeg can decode.
Integrity is semi-fragile: the statement binds a carried coarse content
fingerprint (luma cell means of every frame, U/V cell means of sampled
frames) that the verifier recomputes and compares within pinned tolerances.
Design, resource limits and limitations: ``docs/ROBUST_MODE.md``.
"""
