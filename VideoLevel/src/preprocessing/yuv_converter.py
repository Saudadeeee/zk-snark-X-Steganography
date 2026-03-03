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
        # Ensure input is float for calculation
        frame_float = frame_rgb.astype(np.float32)
        
        # Extract R, G, B channels
        r = frame_float[:, :, 0]
        g = frame_float[:, :, 1]
        b = frame_float[:, :, 2]
        
        # Convert to YUV using ITU-T BT.601 matrix
        y = 0.299 * r + 0.587 * g + 0.114 * b
        cb_full = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
        cr_full = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0
        
        # Clip to valid range
        y = np.clip(y, 0, 255)
        cb_full = np.clip(cb_full, 0, 255)
        cr_full = np.clip(cr_full, 0, 255)
        
        # Apply 4:2:0 subsampling for chroma
        cb = self._subsample_chroma(cb_full)
        cr = self._subsample_chroma(cr_full)
        
        # Convert back to uint8 and adjust chroma range to [-128, 127]
        y = y.astype(np.uint8)
        cb = (cb.astype(np.float32) - 128.0).astype(np.int8)
        cr = (cr.astype(np.float32) - 128.0).astype(np.int8)
        
        return y, cb, cr
    
    def get_luma_channel(self, frame_rgb: np.ndarray) -> np.ndarray:
        """
        Get Y (Luma) channel only
        
        This is the primary channel for embedding.
        
        Args:
            frame_rgb: RGB frame (H x W x 3)
        
        Returns:
            Y channel (H x W), range [0, 255]
        """
        # Fast extraction without full YUV conversion
        frame_float = frame_rgb.astype(np.float32)
        
        r = frame_float[:, :, 0]
        g = frame_float[:, :, 1]
        b = frame_float[:, :, 2]
        
        # Y = 0.299*R + 0.587*G + 0.114*B
        y = 0.299 * r + 0.587 * g + 0.114 * b
        
        # Clip and convert
        y = np.clip(y, 0, 255).astype(np.uint8)
        
        return y
    
    def reconstruct_from_yuv(self, y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
        """
        Reconstruct RGB frame from YUV channels
        
        Args:
            y: Luma channel (H x W)
            cb: Blue chroma (H/2 x W/2), range [-128, 127]
            cr: Red chroma (H/2 x W/2), range [-128, 127]
        
        Returns:
            RGB frame (H x W x 3)
        """
        # Upsample chroma to full resolution
        cb_full = self._upsample_chroma(cb.astype(np.float32) + 128.0)
        cr_full = self._upsample_chroma(cr.astype(np.float32) + 128.0)
        
        # Convert to float for calculation
        y_float = y.astype(np.float32)
        
        # YUV to RGB conversion
        r = y_float + 1.402 * (cr_full - 128.0)
        g = y_float - 0.344136 * (cb_full - 128.0) - 0.714136 * (cr_full - 128.0)
        b = y_float + 1.772 * (cb_full - 128.0)
        
        # Clip to valid range
        r = np.clip(r, 0, 255)
        g = np.clip(g, 0, 255)
        b = np.clip(b, 0, 255)
        
        # Stack into RGB image
        rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
        
        return rgb
    
    def _rgb_to_yuv(self, rgb: np.ndarray) -> np.ndarray:
        """
        Convert RGB pixel values to YUV
        
        Formula (ITU-T BT.601):
            Y  =  0.299*R + 0.587*G + 0.114*B
            Cb = -0.169*R - 0.331*G + 0.500*B + 128
            Cr =  0.500*R - 0.419*G - 0.081*B + 128
        """
        # Reshape for matrix multiplication
        original_shape = rgb.shape
        rgb_flat = rgb.reshape(-1, 3).astype(np.float32)
        
        # Apply transformation matrix
        yuv_flat = np.dot(rgb_flat, self.rgb_to_yuv_matrix.T)
        
        # Add offset for chroma channels
        yuv_flat[:, 1:] += 128.0
        
        # Clip and reshape
        yuv_flat = np.clip(yuv_flat, 0, 255)
        yuv = yuv_flat.reshape(original_shape)
        
        return yuv
    
    def _yuv_to_rgb(self, yuv: np.ndarray) -> np.ndarray:
        """
        Convert YUV pixel values to RGB
        
        Formula:
            R = Y + 1.402*(Cr - 128)
            G = Y - 0.344*(Cb - 128) - 0.714*(Cr - 128)
            B = Y + 1.772*(Cb - 128)
        """
        # Reshape for matrix multiplication
        original_shape = yuv.shape
        yuv_flat = yuv.reshape(-1, 3).astype(np.float32)
        
        # Remove chroma offset
        yuv_flat[:, 1:] -= 128.0
        
        # Apply inverse transformation matrix
        rgb_flat = np.dot(yuv_flat, self.yuv_to_rgb_matrix.T)
        
        # Clip and reshape
        rgb_flat = np.clip(rgb_flat, 0, 255)
        rgb = rgb_flat.reshape(original_shape).astype(np.uint8)
        
        return rgb
    
    def _subsample_chroma(self, chroma: np.ndarray) -> np.ndarray:
        """
        4:2:0 subsampling: Average 2x2 blocks
        
        Args:
            chroma: Full resolution chroma (H x W)
        
        Returns:
            Subsampled chroma (H/2 x W/2)
        """
        h, w = chroma.shape
        
        # Ensure dimensions are even
        h_even = (h // 2) * 2
        w_even = (w // 2) * 2
        chroma_cropped = chroma[:h_even, :w_even]
        
        # Average pooling 2x2: take mean of each 2x2 block
        # Reshape to (H/2, 2, W/2, 2) then mean over axes 1 and 3
        subsampled = chroma_cropped.reshape(h_even // 2, 2, w_even // 2, 2).mean(axis=(1, 3))
        
        return subsampled
    
    def _upsample_chroma(self, chroma_sub: np.ndarray) -> np.ndarray:
        """
        Upsample chroma from 4:2:0 to full resolution
        
        Uses nearest-neighbor upsampling (fast, acceptable for chroma)
        
        Args:
            chroma_sub: Subsampled chroma (H/2 x W/2)
        
        Returns:
            Full resolution chroma (H x W)
        """
        # Fast vectorized upsampling using np.repeat
        # Each value repeated 2x horizontally, then 2x vertically
        upsampled = np.repeat(np.repeat(chroma_sub, 2, axis=0), 2, axis=1)
        
        return upsampled
