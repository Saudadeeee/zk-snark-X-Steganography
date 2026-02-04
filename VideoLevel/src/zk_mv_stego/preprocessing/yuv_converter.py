"""
YUV Color Space Converter

Converts H.264 frames between RGB and YUV color spaces.
Focuses on Y (Luma) channel for steganographic embedding.

Reference: ITU-T H.264 Section 6.2
"""

import numpy as np
from typing import Tuple


class YUVConverter:
    """
    Convert between RGB and YUV color spaces for H.264 frames
    
    YUV 4:2:0 subsampling (standard for H.264):
    - Y (Luma): Full resolution
    - Cb, Cr (Chroma): Half resolution in both dimensions
    
    Why embed in Y channel?
    - Human eye is less sensitive to luma changes than chroma
    - Y has full resolution (more capacity)
    - Chroma subsampling makes Cb/Cr unreliable for embedding
    """
    
    def __init__(self):
        """Initialize YUV converter with ITU-T BT.601 coefficients"""
        # ITU-T BT.601 conversion matrix (standard definition)
        self.rgb_to_yuv_matrix = np.array([
            [ 0.299,     0.587,     0.114   ],  # Y
            [-0.168736, -0.331264,  0.5     ],  # Cb (U)
            [ 0.5,      -0.418688, -0.081312]   # Cr (V)
        ])
        
        self.yuv_to_rgb_matrix = np.array([
            [1.0,  0.0,      1.402   ],  # R
            [1.0, -0.344136, -0.714136],  # G
            [1.0,  1.772,    0.0     ]   # B
        ])
    
    def extract_yuv_from_frame(self, frame_rgb: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Extract Y, Cb, Cr channels from RGB frame
        
        Args:
            frame_rgb: RGB frame (H x W x 3), values in [0, 255]
        
        Returns:
            Tuple of (Y, Cb, Cr) channels
            - Y: Luma channel (H x W), range [0, 255]
            - Cb: Blue chroma (H/2 x W/2), range [-128, 127]
            - Cr: Red chroma (H/2 x W/2), range [-128, 127]
        """
        # TODO: Implement RGB to YUV conversion
        # TODO: Apply 4:2:0 subsampling for Cb, Cr
        raise NotImplementedError("Week 1 - Day 3-4")
    
    def get_luma_channel(self, frame_rgb: np.ndarray) -> np.ndarray:
        """
        Get Y (Luma) channel only
        
        This is the primary channel for embedding.
        
        Args:
            frame_rgb: RGB frame (H x W x 3)
        
        Returns:
            Y channel (H x W), range [0, 255]
        """
        # TODO: Fast extraction of Y channel only
        raise NotImplementedError("Week 1 - Day 3-4")
    
    def reconstruct_from_yuv(self, y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
        """
        Reconstruct RGB frame from YUV channels
        
        Args:
            y: Luma channel (H x W)
            cb: Blue chroma (H/2 x W/2)
            cr: Red chroma (H/2 x W/2)
        
        Returns:
            RGB frame (H x W x 3)
        """
        # TODO: Upsample Cb, Cr to full resolution
        # TODO: Apply YUV to RGB conversion matrix
        raise NotImplementedError("Week 1 - Day 3-4")
    
    def _rgb_to_yuv(self, rgb: np.ndarray) -> np.ndarray:
        """
        Convert RGB pixel values to YUV
        
        Formula (ITU-T BT.601):
            Y  =  0.299*R + 0.587*G + 0.114*B
            Cb = -0.169*R - 0.331*G + 0.500*B + 128
            Cr =  0.500*R - 0.419*G - 0.081*B + 128
        """
        # TODO: Matrix multiplication
        pass
    
    def _yuv_to_rgb(self, yuv: np.ndarray) -> np.ndarray:
        """
        Convert YUV pixel values to RGB
        
        Formula:
            R = Y + 1.402*(Cr - 128)
            G = Y - 0.344*(Cb - 128) - 0.714*(Cr - 128)
            B = Y + 1.772*(Cb - 128)
        """
        # TODO: Inverse matrix multiplication
        pass
    
    def _subsample_chroma(self, chroma: np.ndarray) -> np.ndarray:
        """
        4:2:0 subsampling: Average 2x2 blocks
        
        Args:
            chroma: Full resolution chroma (H x W)
        
        Returns:
            Subsampled chroma (H/2 x W/2)
        """
        # TODO: Average pooling 2x2
        pass
    
    def _upsample_chroma(self, chroma_sub: np.ndarray) -> np.ndarray:
        """
        Upsample chroma from 4:2:0 to full resolution
        
        Uses bilinear interpolation
        
        Args:
            chroma_sub: Subsampled chroma (H/2 x W/2)
        
        Returns:
            Full resolution chroma (H x W)
        """
        # TODO: Bilinear interpolation
        pass


# TODO: Week 1 - Day 5
# Add unit tests in tests/test_yuv_converter.py
# Benchmark conversion time
