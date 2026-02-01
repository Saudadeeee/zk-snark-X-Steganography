"""
Bitstream Processing Module
===========================

Handles low-level H.264 bitstream parsing, modifying, and reconstructing.

Key components:
- BitstreamIO: Reader/Writer for bit-level access
- NAL Handler: NAL Unit and Slice Header parsing
- CAVLC: Context-Adaptive Variable Length Coding
- Macroblock Parser: Detailed macroblock analysis
- Bitstream Reconstructor: Re-encoding logic
"""

from .bitstream_io import BitstreamReader, BitstreamWriter
from .nal_handler import NALUnit, NALUnitType, NALParser, SliceHeaderParser, SliceHeader, SPSData, PPSData
from .h264_parser import H264BitstreamParser
from .macroblock_parser import MacroblockParser, MBType
from .cavlc_decoder import CAVLCDecoder
from .cavlc_encoder import CAVLCEncoder
from .cavlc_tables import TOTAL_ZEROS_TABLES, RUN_BEFORE_TABLES
from .bitstream_reconstructor import BitstreamReconstructor
