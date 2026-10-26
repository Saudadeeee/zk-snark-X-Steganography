"""Native H.264 CABAC (Main/High profile) I-slice decoding and canonical re-encoding.

See docs/CABAC_SUPPORT.md.  Supported subset: 8-bit 4:2:0 progressive frames,
I/IDR slices (I_NxN with 4x4 or 8x8 transform, I_16x16, I_PCM), several slices
per picture.  Inter slices are never parsed; the transport keeps them byte-exact.
"""

from .engine import BitWriter, CabacDecoder, CabacEncoder, CabacError
from .headers import PpsInfo, SpsInfo, UnsupportedStream
from .slice import CabacSlice, decode_slice, encode_slice, is_canonical_slice
from .stream import AnnexBUnit, collect_parameter_sets, join_annexb, split_annexb
from .syntax import Macroblock

__all__ = [
    "AnnexBUnit", "BitWriter", "CabacDecoder", "CabacEncoder", "CabacError", "CabacSlice",
    "Macroblock", "PpsInfo", "SpsInfo", "UnsupportedStream", "collect_parameter_sets",
    "decode_slice", "encode_slice", "is_canonical_slice", "join_annexb", "split_annexb",
]
