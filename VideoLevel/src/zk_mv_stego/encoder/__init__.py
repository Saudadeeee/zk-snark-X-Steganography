"""
Video Encoder Module

This module provides tools for encoding stego videos with modified motion vectors.

Classes:
    H264BitstreamParser: Parse and modify H.264 NAL units
    H264VideoEncoder: High-level interface for creating stego videos

Implementation Status:
    🚧 SKELETON - Core infrastructure needs implementation
    
Priority:
    🔴 CRITICAL - Required for production deployment

See: IMPLEMENTATION_ROADMAP.md for detailed implementation plan
"""

from .h264_bitstream import H264BitstreamParser, H264VideoEncoder

__all__ = [
    'H264BitstreamParser',
    'H264VideoEncoder'
]
