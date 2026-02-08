"""
Visual Quality Benchmark with Charts
=====================================

Creates comprehensive quality comparison between original and stego videos
with visual charts for PSNR, SSIM, and other metrics.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
import subprocess
import tempfile
import os

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.zk_mv_stego.decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
from src.zk_mv_stego.embedder.payload_embedder import PayloadEmbedder
from src.zk_mv_stego.bitstream.bitstream_reconstructor import BitstreamReconstructor


class VisualQualityBenchmark:
    """
    Comprehensive video quality benchmark with visual charts
    """
    
    def __init__(self):
        self.extractor = SimpleCAVLCExtractor()
        self.embedder = PayloadEmbedder(
            use_safety_filter=True,
            skip_dc=True,
            skip_zeros=True,
            allow_small_values=False,
            enable_trailing_ones_protection=True,
            enable_bit_length_check=True
        )
        self.reconstructor = BitstreamReconstructor()
    
    def create_stego_video(self, 
                          original_video: str, 
                          stego_video: str,
                          payload_size: int = 53,
                          max_frames: int = 1) -> Dict:
        """
        Create stego video for benchmarking
        
        Args:
            original_video: Path to original video
            stego_video: Path to output stego video
            payload_size: Payload size in bytes
            max_frames: Number of frames to process (NOTE: BitstreamReconstructor only supports 1 frame)
            
        Returns:
            Statistics dict
        """
        print(f"\n{'='*70}")
        print("CREATING STEGO VIDEO FOR BENCHMARK")
        print(f"{'='*70}")
        
        # NOTE: Currently limited to 1 frame due to BitstreamReconstructor limitation
        if max_frames > 1:
            print(f"[INFO] Testing multi-frame with max_slices=100 (~10 frames)")
            # Remove the limitation warning since we're testing it now
        
        # Create payload
        payload = b"X" * payload_size  # Simple test payload
        print(f"\nPayload: {payload_size} bytes ({payload_size * 8} bits)")
        
        # Extract coefficients
        print(f"\nExtracting DCT coefficients from original video...")
        frames = self.extractor.extract_from_video(original_video, max_frames=max_frames)
        
        frame = frames[0]
        print(f"  Frame 0: {frame['total_coefficients']} coeffs, {frame['non_zero_count']} non-zero")
        
        # Prepare coefficients (FILTER OUT SKIP MBs to prevent CBP mismatch)
        coefficients = []
        skip_mb_count = 0
        coded_mb_count = 0
        
        for mb in frame['macroblocks']:
            mb_idx = mb['mb_idx']
            coeffs = mb['coefficients']
            
            # CRITICAL: Skip macroblocks with CBP=0 (skip/prediction-only MBs)
            # These MBs have no residual data and should NOT be modified
            is_skip_mb = mb.get('is_skip_mb', False) or mb.get('cbp', 1) == 0
            
            if is_skip_mb:
                skip_mb_count += 1
                continue  # Do NOT include skip MBs in coefficient list
            
            coded_mb_count += 1
            for block_idx in range(24):
                start = block_idx * 16
                block_coeffs = coeffs[start:start+16]
                coefficients.append((mb_idx, block_idx, block_coeffs))
        
        print(f"  Coded MBs: {coded_mb_count}, Skip MBs: {skip_mb_count} (filtered out)")
        
        # Get safe positions
        safe_positions = self.embedder.safety_filter.get_safe_positions(coefficients, skip_dc=True)
        capacity_bits = len(safe_positions)
        required_bits = len(payload) * 8
        
        print(f"\nCapacity Analysis:")
        print(f"  Safe positions: {len(safe_positions)}")
        print(f"  Capacity: {capacity_bits} bits ({capacity_bits//8} bytes)")
        print(f"  Required: {required_bits} bits ({required_bits//8} bytes)")
        print(f"  Safety rate: {len(safe_positions)/len(coefficients)*100:.1f}%")
        
        if capacity_bits < required_bits:
            print(f"\n[WARN] Insufficient capacity! Truncating payload...")
            payload = payload[:capacity_bits//8]
        
        # Embed payload
        print(f"\nEmbedding payload...")
        modified_coeffs, total_embedded = self.embedder.embed_payload(coefficients, payload)
        print(f"  Bits embedded: {total_embedded}")
        
        # Reconstruct video
        print(f"\nReconstructing video bitstream...")
        result = self.reconstructor.reconstruct_video(
            original_file=original_video,
            modified_coefficients=modified_coeffs,
            output_file=stego_video,
            max_slices=300  # Support full 300-frame video (CIF resolution)
        )
        
        print(f"\n[OK] Stego video created: {stego_video}")
        
        return {
            'payload_size': len(payload),
            'capacity_bits': capacity_bits,
            'safety_rate': len(safe_positions)/len(coefficients),
            'bits_embedded': total_embedded,
            'status': 'success'
        }
    
    def calculate_psnr(self, img1: np.ndarray, img2: np.ndarray, max_value: float = 255.0) -> float:
        """Calculate PSNR between two images"""
        mse = np.mean((img1.astype(float) - img2.astype(float)) ** 2)
        if mse == 0:
            return float('inf')
        return 20 * np.log10(max_value / np.sqrt(mse))
    
    def calculate_ssim(self, img1: np.ndarray, img2: np.ndarray, max_value: float = 255.0) -> float:
        """Calculate SSIM between two images (simplified version)"""
        C1 = (0.01 * max_value) ** 2
        C2 = (0.03 * max_value) ** 2
        
        mu1 = np.mean(img1)
        mu2 = np.mean(img2)
        sigma1 = np.var(img1)
        sigma2 = np.var(img2)
        sigma12 = np.mean((img1 - mu1) * (img2 - mu2))
        
        ssim = ((2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)) / \
               ((mu1**2 + mu2**2 + C1) * (sigma1 + sigma2 + C2))
        
        return float(ssim)
    
    def decode_video_to_yuv(self, video_path: str, max_frames: int = 1) -> Tuple[str, int, int, int]:
        """
        Decode H.264 video to raw YUV using ffmpeg
        
        Returns:
            (yuv_path, width, height, num_frames)
        """
        # Use ffprobe to get video dimensions
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            video_path
        ]
        
        try:
            result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            width, height = map(int, result.stdout.strip().split(','))
        except:
            # Fallback to common CIF resolution
            width, height = 352, 288
        
        # Create temporary YUV file
        yuv_file = tempfile.NamedTemporaryFile(delete=False, suffix='.yuv')
        yuv_path = yuv_file.name
        yuv_file.close()
        
        # Decode to YUV
        ffmpeg_cmd = [
            'ffmpeg', '-i', video_path,
            '-vframes', str(max_frames),
            '-f', 'rawvideo',
            '-pix_fmt', 'yuv420p',
            '-y', yuv_path
        ]
        
        subprocess.run(ffmpeg_cmd, capture_output=True, check=True)
        
        return yuv_path, width, height, max_frames
    
    def analyze_video_frames(self, yuv_path: str, width: int, height: int, num_frames: int) -> Dict:
        """
        Analyze individual video frames (original or stego)
        
        Returns:
            Dict with per-frame statistics
        """
        frame_size_y = width * height
        frame_size_uv = (width // 2) * (height // 2)
        
        brightness_values = []
        contrast_values = []
        entropy_values = []
        
        with open(yuv_path, 'rb') as f:
            for frame_idx in range(num_frames):
                # Read Y plane only (luma)
                y_plane = np.frombuffer(f.read(frame_size_y), dtype=np.uint8)
                
                # Skip U and V planes
                f.read(2 * frame_size_uv)
                
                if len(y_plane) != frame_size_y:
                    break
                
                # Reshape to 2D
                y_plane = y_plane.reshape(height, width)
                
                # Calculate frame statistics
                brightness = np.mean(y_plane)
                contrast = np.std(y_plane)
                
                # Calculate entropy (simplified)
                hist, _ = np.histogram(y_plane, bins=256, range=(0, 256))
                hist = hist / np.sum(hist)  # Normalize
                hist = hist[hist > 0]  # Remove zeros
                entropy = -np.sum(hist * np.log2(hist))
                
                brightness_values.append(brightness)
                contrast_values.append(contrast)
                entropy_values.append(entropy)
        
        return {
            'brightness': brightness_values,
            'contrast': contrast_values,
            'entropy': entropy_values
        }
    
    def compare_pixel_quality(self, 
                             original_yuv: str, 
                             stego_yuv: str,
                             width: int, 
                             height: int,
                             num_frames: int) -> Dict:
        """
        Compare pixel-level quality between original and stego
        
        Returns:
            Dict with per-frame PSNR, SSIM, and individual video stats
        """
        frame_size_y = width * height
        frame_size_uv = (width // 2) * (height // 2)
        frame_size_total = frame_size_y + 2 * frame_size_uv
        
        psnr_values = []
        ssim_values = []
        mse_values = []
        mae_values = []
        
        # Also collect stats for each video separately
        orig_brightness = []
        orig_contrast = []
        orig_entropy = []
        stego_brightness = []
        stego_contrast = []
        stego_entropy = []
        
        with open(original_yuv, 'rb') as f_orig, open(stego_yuv, 'rb') as f_steg:
            for frame_idx in range(num_frames):
                # Read Y plane only (luma)
                orig_y = np.frombuffer(f_orig.read(frame_size_y), dtype=np.uint8)
                steg_y = np.frombuffer(f_steg.read(frame_size_y), dtype=np.uint8)
                
                # Skip U and V planes
                f_orig.read(2 * frame_size_uv)
                f_steg.read(2 * frame_size_uv)
                
                if len(orig_y) != frame_size_y or len(steg_y) != frame_size_y:
                    break
                
                # Reshape to 2D
                orig_y = orig_y.reshape(height, width)
                steg_y = steg_y.reshape(height, width)
                
                # Calculate comparison metrics
                psnr = self.calculate_psnr(orig_y, steg_y)
                ssim = self.calculate_ssim(orig_y, steg_y)
                mse = np.mean((orig_y.astype(float) - steg_y.astype(float)) ** 2)
                mae = np.mean(np.abs(orig_y.astype(float) - steg_y.astype(float)))
                
                psnr_values.append(psnr)
                ssim_values.append(ssim)
                mse_values.append(mse)
                mae_values.append(mae)
                
                # Calculate individual video stats
                # Original
                orig_brightness.append(np.mean(orig_y))
                orig_contrast.append(np.std(orig_y))
                hist_orig, _ = np.histogram(orig_y, bins=256, range=(0, 256))
                hist_orig = hist_orig / np.sum(hist_orig)
                hist_orig = hist_orig[hist_orig > 0]
                orig_entropy.append(-np.sum(hist_orig * np.log2(hist_orig)))
                
                # Stego
                stego_brightness.append(np.mean(steg_y))
                stego_contrast.append(np.std(steg_y))
                hist_stego, _ = np.histogram(steg_y, bins=256, range=(0, 256))
                hist_stego = hist_stego / np.sum(hist_stego)
                hist_stego = hist_stego[hist_stego > 0]
                stego_entropy.append(-np.sum(hist_stego * np.log2(hist_stego)))
        
        return {
            'psnr': psnr_values,
            'ssim': ssim_values,
            'mse': mse_values,
            'mae': mae_values,
            'average_psnr': np.mean(psnr_values) if psnr_values else 0,
            'average_ssim': np.mean(ssim_values) if ssim_values else 0,
            'average_mse': np.mean(mse_values) if mse_values else 0,
            'average_mae': np.mean(mae_values) if mae_values else 0,
            # Individual video stats
            'original': {
                'brightness': orig_brightness,
                'contrast': orig_contrast,
                'entropy': orig_entropy
            },
            'stego': {
                'brightness': stego_brightness,
                'contrast': stego_contrast,
                'entropy': stego_entropy
            }
        }
    
    def create_quality_charts(self, 
                             metrics: Dict,
                             embedding_stats: Dict,
                             output_dir: str):
        """
        Create comprehensive quality visualization charts with original vs stego comparison
        
        Args:
            metrics: Quality metrics dict
            embedding_stats: Embedding statistics
            output_dir: Output directory for charts
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Set style
        plt.style.use('seaborn-v0_8-darkgrid')
        
        # Create figure with multiple subplots
        fig = plt.figure(figsize=(20, 12))
        
        frames = range(1, len(metrics['psnr']) + 1)
        avg_psnr = metrics['average_psnr']
        avg_ssim = metrics['average_ssim']
        
        # 1. Brightness Comparison (TOP LEFT)
        ax1 = plt.subplot(3, 3, 1)
        ax1.plot(frames, metrics['original']['brightness'], marker='o', linewidth=2.5, 
                markersize=7, color='#3498db', label='Original', alpha=0.8)
        ax1.plot(frames, metrics['stego']['brightness'], marker='s', linewidth=2.5,
                markersize=7, color='#e74c3c', label='Stego', alpha=0.8)
        ax1.set_xlabel('Frame', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Brightness (0-255)', fontsize=11, fontweight='bold')
        ax1.set_title('Brightness Comparison', fontsize=13, fontweight='bold')
        ax1.legend(loc='best', fontsize=10)
        ax1.grid(True, alpha=0.3)
        
        # 2. Contrast Comparison (TOP MIDDLE)
        ax2 = plt.subplot(3, 3, 2)
        ax2.plot(frames, metrics['original']['contrast'], marker='o', linewidth=2.5,
                markersize=7, color='#3498db', label='Original', alpha=0.8)
        ax2.plot(frames, metrics['stego']['contrast'], marker='s', linewidth=2.5,
                markersize=7, color='#e74c3c', label='Stego', alpha=0.8)
        ax2.set_xlabel('Frame', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Contrast (std dev)', fontsize=11, fontweight='bold')
        ax2.set_title('Contrast Comparison', fontsize=13, fontweight='bold')
        ax2.legend(loc='best', fontsize=10)
        ax2.grid(True, alpha=0.3)
        
        # 3. Entropy Comparison (TOP RIGHT)
        ax3 = plt.subplot(3, 3, 3)
        ax3.plot(frames, metrics['original']['entropy'], marker='o', linewidth=2.5,
                markersize=7, color='#3498db', label='Original', alpha=0.8)
        ax3.plot(frames, metrics['stego']['entropy'], marker='s', linewidth=2.5,
                markersize=7, color='#e74c3c', label='Stego', alpha=0.8)
        ax3.set_xlabel('Frame', fontsize=11, fontweight='bold')
        ax3.set_ylabel('Entropy (bits)', fontsize=11, fontweight='bold')
        ax3.set_title('Entropy Comparison', fontsize=13, fontweight='bold')
        ax3.legend(loc='best', fontsize=10)
        ax3.grid(True, alpha=0.3)
        
        # 4. PSNR per frame (MIDDLE LEFT)
        ax4 = plt.subplot(3, 3, 4)
        ax4.plot(frames, metrics['psnr'], marker='D', linewidth=2.5, 
                markersize=8, color='#9b59b6', label='PSNR (Original vs Stego)')
        ax4.axhline(y=avg_psnr, color='r', linestyle='--', linewidth=2, alpha=0.7,
                   label=f'Average: {avg_psnr:.2f} dB')
        ax4.fill_between(frames, metrics['psnr'], avg_psnr, alpha=0.2, color='#9b59b6')
        ax4.set_xlabel('Frame', fontsize=11, fontweight='bold')
        ax4.set_ylabel('PSNR (dB)', fontsize=11, fontweight='bold')
        ax4.set_title('Per-Frame PSNR', fontsize=13, fontweight='bold')
        ax4.legend(loc='best', fontsize=10)
        ax4.grid(True, alpha=0.3)
        
        # 5. SSIM per frame (MIDDLE MIDDLE)
        ax5 = plt.subplot(3, 3, 5)
        ax5.plot(frames, metrics['ssim'], marker='D', linewidth=2.5,
                markersize=8, color='#2ecc71', label='SSIM (Original vs Stego)')
        ax5.axhline(y=avg_ssim, color='r', linestyle='--', linewidth=2, alpha=0.7,
                   label=f'Average: {avg_ssim:.4f}')
        ax5.fill_between(frames, metrics['ssim'], avg_ssim, alpha=0.2, color='#2ecc71')
        ax5.set_xlabel('Frame', fontsize=11, fontweight='bold')
        ax5.set_ylabel('SSIM', fontsize=11, fontweight='bold')
        ax5.set_title('Per-Frame SSIM', fontsize=13, fontweight='bold')
        ax5.legend(loc='best', fontsize=10)
        ax5.grid(True, alpha=0.3)
        
        # 6. Difference Metrics (MIDDLE RIGHT)
        ax6 = plt.subplot(3, 3, 6)
        brightness_diff = [abs(o - s) for o, s in zip(metrics['original']['brightness'], 
                                                       metrics['stego']['brightness'])]
        contrast_diff = [abs(o - s) for o, s in zip(metrics['original']['contrast'],
                                                     metrics['stego']['contrast'])]
        ax6.plot(frames, brightness_diff, marker='o', linewidth=2,
                markersize=6, color='#f39c12', label='Brightness Δ')
        ax6.plot(frames, contrast_diff, marker='s', linewidth=2,
                markersize=6, color='#e67e22', label='Contrast Δ')
        ax6.set_xlabel('Frame', fontsize=11, fontweight='bold')
        ax6.set_ylabel('Absolute Difference', fontsize=11, fontweight='bold')
        ax6.set_title('Feature Differences (|Original - Stego|)', fontsize=13, fontweight='bold')
        ax6.legend(loc='best', fontsize=10)
        ax6.grid(True, alpha=0.3)
        
        # 7. Quality Metrics Summary Bar (BOTTOM LEFT)
        ax7 = plt.subplot(3, 3, 7)
        bars = ax7.bar(['PSNR (dB)', 'SSIM (×100)'], 
                       [avg_psnr, avg_ssim * 100],
                       color=['#3498db', '#2ecc71'])
        ax7.set_ylabel('Value', fontsize=11, fontweight='bold')
        ax7.set_title('Overall Quality Metrics', fontsize=13, fontweight='bold')
        ax7.grid(axis='y', alpha=0.3)
        
        for bar in bars:
            height = bar.get_height()
            ax7.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}',
                    ha='center', va='bottom', fontweight='bold', fontsize=10)
        
        # Add quality rating
        if avg_psnr > 40:
            rating = "Excellent"
            color = '#27ae60'
        elif avg_psnr > 30:
            rating = "Very Good"
            color = '#2ecc71'
        elif avg_psnr > 25:
            rating = "Good"
            color = '#f39c12'
        else:
            rating = "Fair"
            color = '#e74c3c'
        
        ax7.text(0.5, 0.92, f'Rating: {rating}', 
                transform=ax7.transAxes,
                ha='center', va='top',
                bbox=dict(boxstyle='round', facecolor=color, alpha=0.8),
                color='white', fontweight='bold', fontsize=10)
        
        # 8. Embedding Statistics (BOTTOM MIDDLE)
        ax8 = plt.subplot(3, 3, 8)
        safety_rate = embedding_stats.get('safety_rate', 0) * 100
        capacity_used = (embedding_stats.get('bits_embedded', 0) / 
                        embedding_stats.get('capacity_bits', 1) * 100)
        
        stats_data = [safety_rate, capacity_used]
        stats_labels = ['Safety Rate\n(%)', 'Capacity Used\n(%)']
        colors_stats = ['#9b59b6', '#1abc9c']
        
        bars = ax8.bar(stats_labels, stats_data, color=colors_stats)
        ax8.set_ylabel('Percentage (%)', fontsize=11, fontweight='bold')
        ax8.set_title('Embedding Statistics', fontsize=13, fontweight='bold')
        ax8.set_ylim([0, 100])
        ax8.grid(axis='y', alpha=0.3)
        
        for bar in bars:
            height = bar.get_height()
            ax8.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}%',
                    ha='center', va='bottom', fontweight='bold', fontsize=10)
        
        # 9. Summary Table (BOTTOM RIGHT)
        ax9 = plt.subplot(3, 3, 9)
        ax9.axis('off')
        
        # Calculate average differences
        avg_brightness_diff = np.mean([abs(o - s) for o, s in zip(
            metrics['original']['brightness'], metrics['stego']['brightness'])])
        avg_contrast_diff = np.mean([abs(o - s) for o, s in zip(
            metrics['original']['contrast'], metrics['stego']['contrast'])])
        
        summary_data = [
            ['Metric', 'Value'],
            ['─' * 18, '─' * 18],
            ['PSNR', f'{avg_psnr:.2f} dB'],
            ['SSIM', f'{avg_ssim:.4f}'],
            ['MSE', f'{metrics["average_mse"]:.2f}'],
            ['MAE', f'{metrics["average_mae"]:.2f}'],
            ['─' * 18, '─' * 18],
            ['Brightness Δ', f'{avg_brightness_diff:.2f}'],
            ['Contrast Δ', f'{avg_contrast_diff:.2f}'],
            ['─' * 18, '─' * 18],
            ['Payload', f'{embedding_stats.get("payload_size", 0)} B'],
            ['Safety Rate', f'{safety_rate:.1f}%'],
            ['Capacity', f'{capacity_used:.1f}%'],
        ]
        
        table = ax9.table(cellText=summary_data, loc='center',
                         cellLoc='left', colWidths=[0.55, 0.45])
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.8)
        
        # Style header
        for i in range(2):
            table[(0, i)].set_facecolor('#34495e')
            table[(0, i)].set_text_props(weight='bold', color='white')
        
        # Style separator rows
        for i in range(2):
            table[(1, i)].set_facecolor('#ecf0f1')
            table[(6, i)].set_facecolor('#ecf0f1')
            table[(9, i)].set_facecolor('#ecf0f1')
        
        ax9.set_title('Quality Summary', fontsize=13, fontweight='bold', pad=20)
        
        # Overall title
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fig.suptitle(f'Video Quality Benchmark Report\n{timestamp}', 
                    fontsize=16, fontweight='bold', y=0.98)
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.96])
        
        # Save chart
        chart_path = output_path / 'quality_benchmark_chart.png'
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        print(f"\n[OK] Chart saved: {chart_path}")
        
        plt.close()
        
        return str(chart_path)
    
    def run_full_benchmark(self,
                          original_video: str,
                          output_dir: str = "benchmark_results",
                          payload_size: int = 53,
                          max_frames: int = 1) -> Dict:
        """
        Run complete benchmark with stego creation, quality analysis, and visualization
        
        Args:
            original_video: Path to original video
            output_dir: Output directory for results
            payload_size: Payload size in bytes
            max_frames: Number of frames to analyze
            
        Returns:
            Complete benchmark results
        """
        print(f"\n{'='*70}")
        print("VIDEO QUALITY BENCHMARK WITH VISUALIZATION")
        print(f"{'='*70}")
        print(f"\nOriginal video: {original_video}")
        print(f"Output directory: {output_dir}")
        print(f"Payload size: {payload_size} bytes")
        print(f"Max frames: {max_frames}")
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Step 1: Create stego video
        stego_video = str(output_path / 'benchmark_stego.h264')
        embedding_stats = self.create_stego_video(original_video, stego_video, payload_size)
        
        # Step 2: Decode both videos to YUV
        print(f"\n{'='*70}")
        print("DECODING VIDEOS TO YUV")
        print(f"{'='*70}")
        
        print(f"\nDecoding original video...")
        orig_yuv, width, height, num_frames = self.decode_video_to_yuv(original_video, max_frames)
        
        print(f"Decoding stego video...")
        stego_yuv, _, _, _ = self.decode_video_to_yuv(stego_video, max_frames)
        
        print(f"\n[OK] Videos decoded: {width}x{height}, {num_frames} frames")
        
        # Step 3: Compare pixel quality
        print(f"\n{'='*70}")
        print("CALCULATING QUALITY METRICS")
        print(f"{'='*70}")
        
        metrics = self.compare_pixel_quality(orig_yuv, stego_yuv, width, height, num_frames)
        
        print(f"\n[OK] Metrics calculated:")
        print(f"  Average PSNR: {metrics['average_psnr']:.2f} dB")
        print(f"  Average SSIM: {metrics['average_ssim']:.4f}")
        print(f"  Average MSE: {metrics['average_mse']:.2f}")
        print(f"  Average MAE: {metrics['average_mae']:.2f}")
        
        # Cleanup temp files
        os.unlink(orig_yuv)
        os.unlink(stego_yuv)
        
        # Step 4: Create visualization charts
        print(f"\n{'='*70}")
        print("CREATING VISUALIZATION CHARTS")
        print(f"{'='*70}")
        
        chart_path = self.create_quality_charts(metrics, embedding_stats, output_dir)
        
        # Step 5: Save JSON results
        results = {
            'timestamp': datetime.now().isoformat(),
            'original_video': original_video,
            'stego_video': stego_video,
            'video_info': {
                'width': width,
                'height': height,
                'frames_analyzed': num_frames
            },
            'embedding_stats': embedding_stats,
            'quality_metrics': metrics,
            'chart_path': chart_path
        }
        
        json_path = output_path / 'benchmark_results.json'
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"[OK] Results saved: {json_path}")
        
        # Print summary
        print(f"\n{'='*70}")
        print("BENCHMARK COMPLETE")
        print(f"{'='*70}")
        print(f"\n[METRICS] Quality Metrics:")
        print(f"  PSNR: {metrics['average_psnr']:.2f} dB")
        print(f"  SSIM: {metrics['average_ssim']:.4f}")
        print(f"\n[CHART] Chart: {chart_path}")
        print(f"[DATA] JSON: {json_path}")
        
        return results


def main():
    parser = argparse.ArgumentParser(
        description="Visual Quality Benchmark for Video Steganography"
    )
    parser.add_argument('--original', required=True, help='Original H.264 video')
    parser.add_argument('--output', default='benchmark_results', help='Output directory')
    parser.add_argument('--payload', type=int, default=53, help='Payload size in bytes')
    parser.add_argument('--frames', type=int, default=1, help='Number of frames to analyze')
    
    args = parser.parse_args()
    
    benchmark = VisualQualityBenchmark()
    benchmark.run_full_benchmark(
        original_video=args.original,
        output_dir=args.output,
        payload_size=args.payload,
        max_frames=args.frames
    )


if __name__ == "__main__":
    main()
