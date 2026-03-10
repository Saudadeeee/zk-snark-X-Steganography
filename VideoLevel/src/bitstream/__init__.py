"""
Bitstream Processing Module

4-file structure:
  bitstream_io   - BitstreamReader, BitstreamWriter
  cavlc          - CAVLC tables, CAVLCDecoder, CAVLCEncoder
  h264           - NAL parsing, Slice headers, Macroblock parser, TraceableCAVLCParser
  bitstream_ops  - BitstreamPatcher, BitstreamReconstructor
"""

from .bitstream_io import BitstreamReader, BitstreamWriter
from .h264 import (NALUnit, NALUnitType, NALParser, SliceHeaderParser, SliceHeader,
                   SPSData, PPSData, H264BitstreamParser,
                   MacroblockParser, MBType, TraceableCAVLCParser)
from .cavlc import CAVLCDecoder, CAVLCEncoder
from .bitstream_ops import BitArray, BitstreamPatcher, BitstreamReconstructor
