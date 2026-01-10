"""
Video Quality Benchmark with Overlay Charts
Compare Original vs Stego Video Side-by-Side
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List

class OverlayBenchmark:
    """Generate overlay comparison charts for Original vs Stego videos"""
    
    def __init__(self, results_dir: str = "benchmark_results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True)
    
    def load_benchmark_data(self, stego_metadata_path: str) -> Dict:
        """Load stego metadata with MV comparison data"""
        with open(stego_metadata_path, 'r') as f:
            return json.load(f)
    
    def extract_comparison_metrics(self, stego_data: Dict) -> Dict:
        """Extract frame-by-frame metrics for Original vs Stego"""
        original_mvs_flat = stego_data['original_mvs']  # Flat list of all MVs
        stego_mvs_flat = stego_data['modified_mvs']
        
        # Group MVs by frame
        print("\n" + "="*80)
        print("GROUPING MOTION VECTORS BY FRAME")
        print("="*80 + "\n")
        
        original_by_frame = {}
        for mv in original_mvs_flat:
            fidx = mv['frame_idx']
            if fidx not in original_by_frame:
                original_by_frame[fidx] = []
            original_by_frame[fidx].append(mv)
        
        stego_by_frame = {}
        for mv in stego_mvs_flat:
            fidx = mv['frame_idx']
            if fidx not in stego_by_frame:
                stego_by_frame[fidx] = []
            stego_by_frame[fidx].append(mv)
        
        print(f"Grouped {len(original_mvs_flat)} MVs into {len(original_by_frame)} frames\n")
        
        metrics = {
            'frames': [],
            # Original video (baseline - perfect quality)
            'original_psnr': [],
            'original_ssim': [],
            'original_avg_magnitude': [],
            # Stego video (after embedding)
            'stego_psnr': [],
            'stego_ssim': [],
            'stego_avg_magnitude': [],
            # Differences
            'psnr_delta': [],
            'ssim_delta': [],
            'distortion': [],
            'modification_rate': []
        }
        
        print("="*80)
        print("EXTRACTING COMPARISON METRICS: ORIGINAL vs STEGO")
        print("="*80 + "\n")
        
        processed = 0
        frame_indices = sorted(set(original_by_frame.keys()) & set(stego_by_frame.keys()))
        
        for frame_idx in frame_indices:
            orig_mvs = original_by_frame[frame_idx]
            steg_mvs = stego_by_frame[frame_idx]
            
            if len(orig_mvs) == 0:
                continue
            
            # Convert to numpy
            orig_array = np.array([[mv['mvx'], mv['mvy']] for mv in orig_mvs])
            steg_array = np.array([[mv['mvx'], mv['mvy']] for mv in steg_mvs])
            
            # Original metrics (perfect baseline)
            orig_mag = np.mean(np.sqrt(np.sum(orig_array ** 2, axis=1)))
            
            # Stego metrics
            steg_mag = np.mean(np.sqrt(np.sum(steg_array ** 2, axis=1)))
            
            # PSNR calculation
            mse = np.mean((orig_array - steg_array) ** 2)
            if mse < 1e-10:
                stego_psnr = 50.0
            else:
                max_val = max(np.abs(orig_array).max(), 1.0)
                stego_psnr = min(50.0, 20 * np.log10(max_val / (np.sqrt(mse) + 1e-10)))
            
            # SSIM calculation (simplified)
            stego_ssim = self._calculate_ssim(orig_array, steg_array)
            
            # Distortion
            distortion = np.mean(np.sqrt(np.sum((orig_array - steg_array) ** 2, axis=1)))
            
            # Modification rate
            modified_count = np.sum(np.any(orig_array != steg_array, axis=1))
            mod_rate = modified_count / len(orig_array)
            
            # Store metrics
            metrics['frames'].append(frame_idx)
            
            # Original = perfect
            metrics['original_psnr'].append(50.0)
            metrics['original_ssim'].append(1.0)
            metrics['original_avg_magnitude'].append(orig_mag)
            
            # Stego = degraded
            metrics['stego_psnr'].append(stego_psnr)
            metrics['stego_ssim'].append(stego_ssim)
            metrics['stego_avg_magnitude'].append(steg_mag)
            
            # Deltas
            metrics['psnr_delta'].append(50.0 - stego_psnr)
            metrics['ssim_delta'].append(1.0 - stego_ssim)
            metrics['distortion'].append(distortion)
            metrics['modification_rate'].append(mod_rate)
            
            processed += 1
            if processed % 50 == 0:
                print(f"Processed {processed} frames - PSNR: {stego_psnr:.2f}dB, SSIM: {stego_ssim:.4f}")
        
        print(f"\n[OK] Extracted metrics from {processed} frames\n")
        return metrics
    
    def _calculate_ssim(self, orig: np.ndarray, steg: np.ndarray) -> float:
        """Simplified SSIM calculation for MV fields"""
        C1 = (0.01 * 255) ** 2
        C2 = (0.03 * 255) ** 2
        
        # Normalize to [0, 255] range
        orig_norm = (orig - orig.min()) / (orig.max() - orig.min() + 1e-10) * 255
        steg_norm = (steg - steg.min()) / (steg.max() - steg.min() + 1e-10) * 255
        
        mu1 = np.mean(orig_norm)
        mu2 = np.mean(steg_norm)
        
        sigma1 = np.var(orig_norm)
        sigma2 = np.var(steg_norm)
        sigma12 = np.mean((orig_norm - mu1) * (steg_norm - mu2))
        
        ssim = ((2*mu1*mu2 + C1) * (2*sigma12 + C2)) / \
               ((mu1**2 + mu2**2 + C1) * (sigma1 + sigma2 + C2))
        
        return max(0.0, min(1.0, ssim))
    
    def plot_overlay_comparison(self, metrics: Dict, output_name: str = "overlay_comparison"):
        """Generate overlay charts with Original (blue) vs Stego (red)"""
        print("\n" + "="*80)
        print("GENERATING OVERLAY COMPARISON CHARTS")
        print("="*80 + "\n")
        
        fig, axes = plt.subplots(2, 2, figsize=(18, 12))
        frames = metrics['frames']
        
        # === Chart 1: PSNR Overlay ===
        ax1 = axes[0, 0]
        ax1.plot(frames, metrics['original_psnr'], 
                linewidth=3, color='#2E86AB', label='Original (Baseline)', 
                linestyle='-', alpha=0.9, marker='o', markersize=3, markevery=10)
        ax1.plot(frames, metrics['stego_psnr'], 
                linewidth=3, color='#C73E1D', label='Stego (After Embedding)', 
                linestyle='-', alpha=0.9, marker='s', markersize=3, markevery=10)
        
        ax1.fill_between(frames, metrics['original_psnr'], metrics['stego_psnr'], 
                         alpha=0.2, color='#FF6B6B', label='Quality Gap')
        
        ax1.axhline(y=40, color='#27AE60', linestyle=':', linewidth=2, alpha=0.6, label='Excellent (>40dB)')
        ax1.axhline(y=35, color='#F39C12', linestyle=':', linewidth=2, alpha=0.6, label='Good (>35dB)')
        
        ax1.set_xlabel('Frame Number', fontsize=13, fontweight='bold')
        ax1.set_ylabel('PSNR (dB)', fontsize=13, fontweight='bold')
        ax1.set_title('PSNR: Original vs Stego Video', fontsize=15, fontweight='bold', pad=15)
        ax1.grid(True, alpha=0.25, linestyle='--', linewidth=0.7)
        ax1.legend(loc='lower left', fontsize=10, framealpha=0.95)
        ax1.set_ylim([30, 52])
        
        # === Chart 2: SSIM Overlay ===
        ax2 = axes[0, 1]
        ax2.plot(frames, metrics['original_ssim'], 
                linewidth=3, color='#2E86AB', label='Original (Perfect=1.0)', 
                linestyle='-', alpha=0.9, marker='o', markersize=3, markevery=10)
        ax2.plot(frames, metrics['stego_ssim'], 
                linewidth=3, color='#C73E1D', label='Stego (After Embedding)', 
                linestyle='-', alpha=0.9, marker='s', markersize=3, markevery=10)
        
        ax2.fill_between(frames, metrics['original_ssim'], metrics['stego_ssim'], 
                         alpha=0.2, color='#FF6B6B', label='Quality Gap')
        
        ax2.axhline(y=0.98, color='#27AE60', linestyle=':', linewidth=2, alpha=0.6, label='Excellent (>0.98)')
        ax2.axhline(y=0.95, color='#F39C12', linestyle=':', linewidth=2, alpha=0.6, label='Good (>0.95)')
        
        ax2.set_xlabel('Frame Number', fontsize=13, fontweight='bold')
        ax2.set_ylabel('SSIM Index', fontsize=13, fontweight='bold')
        ax2.set_title('SSIM: Original vs Stego Video', fontsize=15, fontweight='bold', pad=15)
        ax2.grid(True, alpha=0.25, linestyle='--', linewidth=0.7)
        ax2.legend(loc='lower left', fontsize=10, framealpha=0.95)
        ax2.set_ylim([0.85, 1.02])
        
        # === Chart 3: Motion Vector Magnitude Overlay ===
        ax3 = axes[1, 0]
        ax3.plot(frames, metrics['original_avg_magnitude'], 
                linewidth=3, color='#2E86AB', label='Original MV', 
                linestyle='-', alpha=0.9, marker='o', markersize=3, markevery=10)
        ax3.plot(frames, metrics['stego_avg_magnitude'], 
                linewidth=3, color='#C73E1D', label='Stego MV (Modified)', 
                linestyle='-', alpha=0.9, marker='s', markersize=3, markevery=10)
        
        ax3.fill_between(frames, 
                         np.minimum(metrics['original_avg_magnitude'], metrics['stego_avg_magnitude']),
                         np.maximum(metrics['original_avg_magnitude'], metrics['stego_avg_magnitude']), 
                         alpha=0.15, color='#9B59B6', label='MV Change')
        
        ax3.set_xlabel('Frame Number', fontsize=13, fontweight='bold')
        ax3.set_ylabel('Avg MV Magnitude (pixels)', fontsize=13, fontweight='bold')
        ax3.set_title('Motion Vector Magnitude: Original vs Stego', fontsize=15, fontweight='bold', pad=15)
        ax3.grid(True, alpha=0.25, linestyle='--', linewidth=0.7)
        ax3.legend(loc='best', fontsize=10, framealpha=0.95)
        
        # === Chart 4: Quality Degradation (Delta) ===
        ax4 = axes[1, 1]
        
        # Twin axes for two metrics
        ax4_twin = ax4.twinx()
        
        line1 = ax4.plot(frames, metrics['psnr_delta'], 
                        linewidth=3, color='#E74C3C', label='PSNR Degradation (dB)', 
                        linestyle='-', alpha=0.9, marker='o', markersize=3, markevery=10)
        
        line2 = ax4_twin.plot(frames, [s*100 for s in metrics['ssim_delta']], 
                             linewidth=3, color='#9B59B6', label='SSIM Degradation (%)', 
                             linestyle='--', alpha=0.9, marker='s', markersize=3, markevery=10)
        
        ax4.set_xlabel('Frame Number', fontsize=13, fontweight='bold')
        ax4.set_ylabel('PSNR Degradation (dB)', fontsize=13, fontweight='bold', color='#E74C3C')
        ax4_twin.set_ylabel('SSIM Degradation (%)', fontsize=13, fontweight='bold', color='#9B59B6')
        ax4.set_title('Quality Degradation from Original to Stego', fontsize=15, fontweight='bold', pad=15)
        ax4.grid(True, alpha=0.25, linestyle='--', linewidth=0.7)
        ax4.tick_params(axis='y', labelcolor='#E74C3C')
        ax4_twin.tick_params(axis='y', labelcolor='#9B59B6')
        
        # Combined legend
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        ax4.legend(lines, labels, loc='upper right', fontsize=10, framealpha=0.95)
        
        plt.tight_layout()
        output_path = self.results_dir / f"{output_name}.png"
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"[OK] Saved overlay chart: {output_path}\n")
        return output_path
    
    def generate_summary_stats(self, metrics: Dict) -> Dict:
        """Calculate summary statistics"""
        return {
            'total_frames': len(metrics['frames']),
            'avg_psnr_original': np.mean(metrics['original_psnr']),
            'avg_psnr_stego': np.mean(metrics['stego_psnr']),
            'avg_psnr_degradation': np.mean(metrics['psnr_delta']),
            'max_psnr_degradation': np.max(metrics['psnr_delta']),
            
            'avg_ssim_original': np.mean(metrics['original_ssim']),
            'avg_ssim_stego': np.mean(metrics['stego_ssim']),
            'avg_ssim_degradation': np.mean(metrics['ssim_delta']),
            'max_ssim_degradation': np.max(metrics['ssim_delta']),
            
            'avg_distortion': np.mean(metrics['distortion']),
            'max_distortion': np.max(metrics['distortion']),
            'avg_modification_rate': np.mean(metrics['modification_rate']) * 100,
        }
    
    def print_summary_report(self, stats: Dict):
        """Print summary comparison report"""
        print("\n" + "="*80)
        print("OVERLAY BENCHMARK SUMMARY: ORIGINAL vs STEGO")
        print("="*80 + "\n")
        
        print(f"Total Frames Analyzed: {stats['total_frames']}\n")
        
        print("PSNR COMPARISON:")
        print(f"  Original (Baseline):     {stats['avg_psnr_original']:.2f} dB")
        print(f"  Stego (After Embedding): {stats['avg_psnr_stego']:.2f} dB")
        print(f"  Average Degradation:     {stats['avg_psnr_degradation']:.4f} dB")
        print(f"  Maximum Degradation:     {stats['max_psnr_degradation']:.4f} dB")
        
        print("\nSSIM COMPARISON:")
        print(f"  Original (Baseline):     {stats['avg_ssim_original']:.6f}")
        print(f"  Stego (After Embedding): {stats['avg_ssim_stego']:.6f}")
        print(f"  Average Degradation:     {stats['avg_ssim_degradation']:.6f}")
        print(f"  Maximum Degradation:     {stats['max_ssim_degradation']:.6f}")
        
        print("\nEMBEDDING IMPACT:")
        print(f"  Avg MV Distortion:       {stats['avg_distortion']:.4f} pixels")
        print(f"  Max MV Distortion:       {stats['max_distortion']:.4f} pixels")
        print(f"  Avg Modification Rate:   {stats['avg_modification_rate']:.2f}%")
        
        print("\nQUALITY VERDICT:")
        if stats['avg_psnr_degradation'] < 0.1:
            print("  ✓ EXCELLENT - Negligible PSNR degradation")
        elif stats['avg_psnr_degradation'] < 0.5:
            print("  ✓ GOOD - Minor PSNR degradation")
        else:
            print("  ⚠ FAIR - Noticeable PSNR degradation")
        
        if stats['avg_ssim_degradation'] < 0.02:
            print("  ✓ EXCELLENT - Negligible SSIM degradation")
        elif stats['avg_ssim_degradation'] < 0.05:
            print("  ✓ GOOD - Minor SSIM degradation")
        else:
            print("  ⚠ FAIR - Noticeable SSIM degradation")
        
        print("\n" + "="*80 + "\n")

def main():
    """Main benchmark execution"""
    print("\n" + "="*80)
    print("VIDEO OVERLAY BENCHMARK: ORIGINAL vs STEGO COMPARISON")
    print("="*80 + "\n")
    
    # Initialize benchmark
    benchmark = OverlayBenchmark(results_dir="benchmark_results")
    
    # Load stego metadata
    stego_file = "benchmark_stego.json"
    print(f"Loading stego metadata from: {stego_file}")
    stego_data = benchmark.load_benchmark_data(stego_file)
    
    # Extract comparison metrics
    metrics = benchmark.extract_comparison_metrics(stego_data)
    
    # Generate overlay charts
    benchmark.plot_overlay_comparison(metrics, output_name="overlay_comparison")
    
    # Calculate and print summary
    stats = benchmark.generate_summary_stats(metrics)
    benchmark.print_summary_report(stats)
    
    print("[SUCCESS] Overlay benchmark completed!")
    print(f"Charts saved to: {benchmark.results_dir.absolute()}/overlay_comparison.png\n")

if __name__ == "__main__":
    main()
