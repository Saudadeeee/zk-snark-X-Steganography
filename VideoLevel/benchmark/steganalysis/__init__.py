"""Steganalysis toolkit for H.264 CAVLC trailing-one-sign embedding.

Modules
-------
common          manifest loading, FFmpeg luma decoding, feature cache
cavlc_trace     streaming parser for ``zkstego_inspect`` JSON traces
features_cavlc  compressed-domain trailing-one-sign features (323-D)
features_pixel  SPAM-686 and SRM-lite (3978-D) on decoded luma
ensemble        Kodovsky-Fridrich-Holub FLD ensemble (numpy)
metrics         AUC and P_E
cnn             Xu-Net-style CNN steganalyser (PyTorch)
evaluate        CLI: train / val / test protocol over a manifest
selfcheck       builds a tiny dataset and runs every detector end to end
"""
