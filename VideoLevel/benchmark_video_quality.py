"""
Video Quality Benchmark for DCT Steganography
==============================================

Compares original video vs stego video using standard quality metrics:
- PSNR (Peak Signal-to-Noise Ratio)
- SSIM (Structural Similarity Index)
- MSE (Mean Squared Error)
- MAE (Mean Absolute Error)
- Histogram Similarity

Requires: ffmpeg-python or opencv-python for video decoding
"""

import sys
import subprocess
import numpy as np
from pathlib import Path
from typing import Tuple, Dict, List, Optional
import time
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from zk_mv_stego.decoder.cavlc_extractor_simple import SimpleCAVLCExtractor


class VideoQualityBenchmark:
    """
    Benchmark video quality metrics for steganography
    """
    
    def __init__(self):
        self.extractor = SimpleCAVLCExtractor()
    
    @staticmethod
    def calculate_psnr(img1: np.ndarray, img2: np.ndarray, max_value: float = 255.0) -> float:
        """
        Calculate Peak Signal-to-Noise Ratio
        
        Formula: PSNR = 20 * log10(MAX / sqrt(MSE))
        
        Args:
            img1: Original image/frame
            img2: Modified image/frame
            max_value: Maximum pixel value (255 for 8-bit)
        
        Returns:
            PSNR in dB (higher is better)
            - > 50 dB: Excellent (virtually identical)
            - 40-50 dB: Very good
            - 30-40 dB: Good
            - < 30 dB: Poor
        """
        mse = np.mean((img1.astype(float) - img2.astype(float)) ** 2)
        
        if mse == 0:
            return float('inf')  # Perfect match
        
        psnr = 20 * np.log10(max_value / np.sqrt(mse))
        return psnr
    
    @staticmethod
    def calculate_ssim(img1: np.ndarray, img2: np.ndarray, 
                       max_value: float = 255.0,
                       k1: float = 0.01, k2: float = 0.03) -> float:
        """
        Calculate Structural Similarity Index (simplified version)
        
        SSIM considers:
        - Luminance similarity
        - Contrast similarity
        - Structure similarity
        
        Args:
            img1: Original image/frame
            img2: Modified image/frame
            max_value: Maximum pixel value
            k1, k2: Algorithm constants
        
        Returns:
            SSIM value in range [-1, 1]
            - 1.0: Perfect match
            - > 0.99: Excellent (imperceptible)
            - > 0.95: Very good
            - > 0.90: Good
            - < 0.90: Noticeable differences
        """
        # Constants
        c1 = (k1 * max_value) ** 2
        c2 = (k2 * max_value) ** 2
        
        # Convert to float
        img1 = img1.astype(float)
        img2 = img2.astype(float)
        
        # Calculate means
        mu1 = np.mean(img1)
        mu2 = np.mean(img2)
        
        # Calculate variances and covariance
        sigma1_sq = np.var(img1)
        sigma2_sq = np.var(img2)
        sigma12 = np.mean((img1 - mu1) * (img2 - mu2))
        
        # SSIM formula
        numerator = (2 * mu1 * mu2 + c1) * (2 * sigma12 + c2)
        denominator = (mu1**2 + mu2**2 + c1) * (sigma1_sq + sigma2_sq + c2)
        
        ssim = numerator / denominator
        return ssim
    
    @staticmethod
    def calculate_mse(img1: np.ndarray, img2: np.ndarray) -> float:
        """
        Calculate Mean Squared Error
        
        Args:
            img1: Original image
            img2: Modified image
        
        Returns:
            MSE value (lower is better)
            - 0: Perfect match
            - < 10: Excellent
            - < 100: Good
            - > 100: Poor
        """
        return np.mean((img1.astype(float) - img2.astype(float)) ** 2)
    
    @staticmethod
    def calculate_mae(img1: np.ndarray, img2: np.ndarray) -> float:
        """
        Calculate Mean Absolute Error
        
        Args:
            img1: Original image
            img2: Modified image
        
        Returns:
            MAE value (lower is better)
        """
        return np.mean(np.abs(img1.astype(float) - img2.astype(float)))
    
    def compare_dct_coefficients(self, original_video: str, stego_video: str, 
                                 max_frames: int = 10) -> Dict:
        """
        Compare DCT coefficients between original and stego videos
        
        This is the most direct comparison for DCT-based steganography
        
        Args:
            original_video: Path to original H.264 video
            stego_video: Path to stego video
            max_frames: Maximum frames to analyze
        
        Returns:
            Dictionary with DCT-level metrics
        """
        print(f"\n{'='*80}")
        print("DCT COEFFICIENT COMPARISON")
        print(f"{'='*80}\n")
        
        print(f"Extracting DCT coefficients from original video...")
        original_frames = self.extractor.extract_from_video(original_video, max_frames=max_frames)
        
        print(f"Extracting DCT coefficients from stego video...")
        stego_frames = self.extractor.extract_from_video(stego_video, max_frames=max_frames)
        
        if len(original_frames) != len(stego_frames):
            print(f"[WARN] Frame count mismatch: {len(original_frames)} vs {len(stego_frames)}")
        
        num_frames = min(len(original_frames), len(stego_frames))
        
        # Collect statistics
        total_coeffs = 0
        modified_coeffs = 0
        total_abs_diff = 0
        max_abs_diff = 0
        
        coefficient_diffs = []
        
        for i in range(num_frames):
            orig_frame = original_frames[i]
            stego_frame = stego_frames[i]
            
            # Convert macroblock format to blocks format if needed
            if 'blocks' not in orig_frame:
                # SimpleCAVLCExtractor returns 'macroblock' format
                # Convert to blocks: [(mb_idx, block_idx, coeffs), ...]
                orig_blocks = []
                for mb in orig_frame['macroblocks']:
                    mb_idx = mb['mb_idx']
                    coeffs = mb['coefficients']
                    # Split into 24 blocks (16 luma + 8 chroma)
                    for block_idx in range(24):
                        start = block_idx * 16
                        block_coeffs = coeffs[start:start+16]
                        orig_blocks.append((mb_idx, block_idx, block_coeffs))
            else:
                orig_blocks = orig_frame['blocks']
            
            if 'blocks' not in stego_frame:
                stego_blocks = []
                for mb in stego_frame['macroblocks']:
                    mb_idx = mb['mb_idx']
                    coeffs = mb['coefficients']
                    for block_idx in range(24):
                        start = block_idx * 16
                        block_coeffs = coeffs[start:start+16]
                        stego_blocks.append((mb_idx, block_idx, block_coeffs))
            else:
                stego_blocks = stego_frame['blocks']
            
            # Compare coefficients block by block
            
            for (mb_o, blk_o, coeffs_o), (mb_s, blk_s, coeffs_s) in zip(orig_blocks, stego_blocks):
                for coeff_orig, coeff_stego in zip(coeffs_o, coeffs_s):
                    total_coeffs += 1
                    
                    diff = abs(coeff_orig - coeff_stego)
                    
                    if diff > 0:
                        modified_coeffs += 1
                        total_abs_diff += diff
                        max_abs_diff = max(max_abs_diff, diff)
                        coefficient_diffs.append(diff)
        
        modification_rate = (modified_coeffs / total_coeffs * 100) if total_coeffs > 0 else 0
        avg_diff = (total_abs_diff / modified_coeffs) if modified_coeffs > 0 else 0
        
        print(f"\nDCT Coefficient Analysis:")
        print(f"  Total coefficients: {total_coeffs:,}")
        print(f"  Modified coefficients: {modified_coeffs:,}")
        print(f"  Modification rate: {modification_rate:.4f}%")
        print(f"  Average absolute difference: {avg_diff:.4f}")
        print(f"  Maximum absolute difference: {max_abs_diff}")
        
        # Calculate PSNR in DCT domain
        if modified_coeffs > 0:
            # MSE in DCT domain
            mse_dct = total_abs_diff / total_coeffs
            # Assume max coefficient value ~255 (typical for QP=28)
            max_coeff = 255.0
            psnr_dct = 20 * np.log10(max_coeff / np.sqrt(mse_dct)) if mse_dct > 0 else float('inf')
            print(f"  PSNR (DCT domain): {psnr_dct:.2f} dB")
        else:
            psnr_dct = float('inf')
            print(f"  PSNR (DCT domain): Infinity (no changes)")
        
        # Histogram of differences
        if coefficient_diffs:
            diffs_array = np.array(coefficient_diffs)
            print(f"\n  Difference histogram:")
            print(f"    Diff = 1: {np.sum(diffs_array == 1):,} ({np.sum(diffs_array == 1)/len(diffs_array)*100:.2f}%)")
            print(f"    Diff = 2: {np.sum(diffs_array == 2):,} ({np.sum(diffs_array == 2)/len(diffs_array)*100:.2f}%)")
            print(f"    Diff > 2: {np.sum(diffs_array > 2):,} ({np.sum(diffs_array > 2)/len(diffs_array)*100:.2f}%)")
        
        return {
            'total_coefficients': total_coeffs,
            'modified_coefficients': modified_coeffs,
            'modification_rate': modification_rate,
            'average_difference': avg_diff,
            'max_difference': max_abs_diff,
            'psnr_dct': psnr_dct,
            'frames_analyzed': num_frames
        }
    
    def decode_video_to_yuv(self, video_path: str, output_yuv: str, max_frames: int = 10) -> Tuple[int, int, int]:
        """
        Decode H.264 video to raw YUV frames using ffmpeg
        
        Args:
            video_path: Input H.264 video
            output_yuv: Output YUV file
            max_frames: Maximum frames to decode
        
        Returns:
            (width, height, frame_count)
        """
        # Get video info first
        cmd_info = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,nb_frames',
            '-of', 'json',
            video_path
        ]
        
        try:
            result = subprocess.run(cmd_info, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            width = info['streams'][0]['width']
            height = info['streams'][0]['height']
            
            # Decode to YUV
            cmd_decode = [
                'ffmpeg', '-i', video_path,
                '-vframes', str(max_frames),
                '-f', 'rawvideo',
                '-pix_fmt', 'yuv420p',
                '-y',  # Overwrite
                output_yuv
            ]
            
            subprocess.run(cmd_decode, capture_output=True, check=True)
            
            return width, height, max_frames
            
        except Exception as e:
            print(f"[ERROR] ffmpeg not available or decode failed: {e}")
            return None, None, 0
    
    def compare_pixel_quality(self, original_yuv: str, stego_yuv: str,
                             width: int, height: int, num_frames: int) -> Dict:
        """
        Compare pixel-level quality between original and stego YUV frames
        
        Args:
            original_yuv: Original YUV file
            stego_yuv: Stego YUV file
            width: Frame width
            height: Frame height
            num_frames: Number of frames
        
        Returns:
            Dictionary with quality metrics
        """
        print(f"\n{'='*80}")
        print("PIXEL-LEVEL QUALITY COMPARISON")
        print(f"{'='*80}\n")
        
        # YUV420 frame size
        y_size = width * height
        uv_size = (width // 2) * (height // 2)
        frame_size = y_size + 2 * uv_size
        
        # Read YUV data
        with open(original_yuv, 'rb') as f:
            original_data = f.read()
        
        with open(stego_yuv, 'rb') as f:
            stego_data = f.read()
        
        psnr_values = []
        ssim_values = []
        mse_values = []
        mae_values = []
        
        print(f"Analyzing {num_frames} frames ({width}x{height})...\n")
        
        for i in range(num_frames):
            offset = i * frame_size
            
            # Extract Y plane only (luma) for simplicity
            orig_y = np.frombuffer(original_data[offset:offset+y_size], dtype=np.uint8).reshape(height, width)
            stego_y = np.frombuffer(stego_data[offset:offset+y_size], dtype=np.uint8).reshape(height, width)
            
            # Calculate metrics
            psnr = self.calculate_psnr(orig_y, stego_y)
            ssim = self.calculate_ssim(orig_y, stego_y)
            mse = self.calculate_mse(orig_y, stego_y)
            mae = self.calculate_mae(orig_y, stego_y)
            
            psnr_values.append(psnr)
            ssim_values.append(ssim)
            mse_values.append(mse)
            mae_values.append(mae)
            
            print(f"  Frame {i+1:2d}: PSNR={psnr:6.2f} dB, SSIM={ssim:.6f}, MSE={mse:6.2f}, MAE={mae:5.2f}")
        
        # Calculate averages
        avg_psnr = np.mean(psnr_values)
        avg_ssim = np.mean(ssim_values)
        avg_mse = np.mean(mse_values)
        avg_mae = np.mean(mae_values)
        
        min_psnr = np.min(psnr_values)
        min_ssim = np.min(ssim_values)
        
        print(f"\n{'='*80}")
        print(f"AVERAGE QUALITY METRICS (over {num_frames} frames)")
        print(f"{'='*80}")
        print(f"  PSNR: {avg_psnr:.2f} dB (min: {min_psnr:.2f} dB)")
        print(f"  SSIM: {avg_ssim:.6f} (min: {min_ssim:.6f})")
        print(f"  MSE:  {avg_mse:.2f}")
        print(f"  MAE:  {avg_mae:.2f}")
        print(f"{'='*80}\n")
        
        return {
            'average_psnr': avg_psnr,
            'min_psnr': min_psnr,
            'average_ssim': avg_ssim,
            'min_ssim': min_ssim,
            'average_mse': avg_mse,
            'average_mae': avg_mae,
            'per_frame_psnr': psnr_values,
            'per_frame_ssim': ssim_values
        }
    
    def run_full_benchmark(self, original_video: str, stego_video: str, 
                          max_frames: int = 5) -> Dict:
        """
        Run complete quality benchmark
        
        Args:
            original_video: Path to original H.264 video
            stego_video: Path to stego H.264 video
            max_frames: Maximum frames to analyze
        
        Returns:
            Complete benchmark results
        """
        print(f"\n{'='*80}")
        print("VIDEO QUALITY BENCHMARK")
        print(f"{'='*80}")
        print(f"Original: {original_video}")
        print(f"Stego:    {stego_video}")
        print(f"Frames:   {max_frames}")
        print(f"{'='*80}\n")
        
        start_time = time.time()
        
        # Step 1: DCT coefficient comparison
        dct_metrics = self.compare_dct_coefficients(original_video, stego_video, max_frames)
        
        # Step 2: Pixel-level comparison (requires ffmpeg)
        print(f"\nAttempting pixel-level comparison (requires ffmpeg)...")
        try:
            # Decode videos to YUV
            orig_yuv = "temp_original.yuv"
            stego_yuv = "temp_stego.yuv"
            
            width, height, frames = self.decode_video_to_yuv(original_video, orig_yuv, max_frames)
            
            if width and height:
                self.decode_video_to_yuv(stego_video, stego_yuv, max_frames)
                pixel_metrics = self.compare_pixel_quality(orig_yuv, stego_yuv, width, height, frames)
                
                # Cleanup
                Path(orig_yuv).unlink(missing_ok=True)
                Path(stego_yuv).unlink(missing_ok=True)
            else:
                print("[INFO] Skipping pixel-level comparison (ffmpeg not available)")
                pixel_metrics = None
                
        except Exception as e:
            print(f"[INFO] Pixel-level comparison skipped: {e}")
            pixel_metrics = None
        
        elapsed = time.time() - start_time
        
        # Summary
        print(f"\n{'='*80}")
        print("BENCHMARK SUMMARY")
        print(f"{'='*80}")
        print(f"\nDCT Domain Metrics:")
        print(f"  Modification rate: {dct_metrics['modification_rate']:.4f}%")
        print(f"  Average difference: {dct_metrics['average_difference']:.4f}")
        print(f"  PSNR (DCT): {dct_metrics['psnr_dct']:.2f} dB")
        
        if pixel_metrics:
            print(f"\nPixel Domain Metrics:")
            print(f"  PSNR (Pixel): {pixel_metrics['average_psnr']:.2f} dB")
            print(f"  SSIM: {pixel_metrics['average_ssim']:.6f}")
            
            # Quality assessment
            if pixel_metrics['average_psnr'] > 50:
                quality_rating = "EXCELLENT - Visually identical"
            elif pixel_metrics['average_psnr'] > 40:
                quality_rating = "VERY GOOD - Imperceptible differences"
            elif pixel_metrics['average_psnr'] > 30:
                quality_rating = "GOOD - Minor quality loss"
            else:
                quality_rating = "POOR - Noticeable degradation"
            
            print(f"\n  Quality Rating: {quality_rating}")
        
        print(f"\nBenchmark completed in {elapsed:.2f}s")
        print(f"{'='*80}\n")
        
        return {
            'dct_metrics': dct_metrics,
            'pixel_metrics': pixel_metrics,
            'elapsed_time': elapsed
        }


def main():
    """Run benchmark on test videos"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Video Quality Benchmark')
    parser.add_argument('--original', required=True, help='Original H.264 video')
    parser.add_argument('--stego', required=True, help='Stego H.264 video')
    parser.add_argument('--frames', type=int, default=5, help='Max frames to analyze')
    parser.add_argument('--output', help='JSON output file for results')
    
    args = parser.parse_args()
    
    # Run benchmark
    benchmark = VideoQualityBenchmark()
    results = benchmark.run_full_benchmark(args.original, args.stego, args.frames)
    
    # Save results
    if args.output:
        with open(args.output, 'w') as f:
            # Convert inf to string for JSON
            def convert_inf(obj):
                if isinstance(obj, float) and np.isinf(obj):
                    return "Infinity"
                elif isinstance(obj, dict):
                    return {k: convert_inf(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_inf(v) for v in obj]
                return obj
            
            json.dump(convert_inf(results), f, indent=2)
        print(f"Results saved to: {args.output}")


if __name__ == '__main__':
    main()
