"""
Analyze PSNR degradation issues - Find root causes
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Tuple

class PSNRAnalyzer:
    """Analyze why PSNR has degradation in some frames"""
    
    def __init__(self, stego_file: str = "benchmark_stego.json"):
        with open(stego_file, 'r') as f:
            self.data = json.load(f)
        
        # Group MVs by frame
        self.original_by_frame = self._group_by_frame(self.data['original_mvs'])
        self.stego_by_frame = self._group_by_frame(self.data['modified_mvs'])
    
    def _group_by_frame(self, mvs_flat: List[Dict]) -> Dict[int, List[Dict]]:
        """Group flat MV list by frame index"""
        by_frame = {}
        for mv in mvs_flat:
            fidx = mv['frame_idx']
            if fidx not in by_frame:
                by_frame[fidx] = []
            by_frame[fidx].append(mv)
        return by_frame
    
    def analyze_all_frames(self) -> Dict:
        """Analyze PSNR, distortion, and MV count for all frames"""
        results = []
        
        frame_indices = sorted(set(self.original_by_frame.keys()) & set(self.stego_by_frame.keys()))
        
        for frame_idx in frame_indices:
            orig_mvs = self.original_by_frame[frame_idx]
            steg_mvs = self.stego_by_frame[frame_idx]
            
            if len(orig_mvs) == 0:
                continue
            
            # Convert to arrays
            orig_array = np.array([[mv['mvx'], mv['mvy']] for mv in orig_mvs])
            steg_array = np.array([[mv['mvx'], mv['mvy']] for mv in steg_mvs])
            
            # Calculate metrics
            mse = np.mean((orig_array - steg_array) ** 2)
            
            if mse < 1e-10:
                psnr = 50.0
            else:
                max_val = max(np.abs(orig_array).max(), 1.0)
                psnr = min(50.0, 20 * np.log10(max_val / (np.sqrt(mse) + 1e-10)))
            
            # MV statistics
            orig_mag = np.mean(np.sqrt(np.sum(orig_array ** 2, axis=1)))
            steg_mag = np.mean(np.sqrt(np.sum(steg_array ** 2, axis=1)))
            distortion = np.mean(np.sqrt(np.sum((orig_array - steg_array) ** 2, axis=1)))
            max_distortion = np.max(np.sqrt(np.sum((orig_array - steg_array) ** 2, axis=1)))
            
            # Modification count
            modified_count = np.sum(np.any(orig_array != steg_array, axis=1))
            mod_rate = modified_count / len(orig_array)
            
            # Check if this is I-frame or P-frame (heuristic: low MV count = I-frame)
            frame_type = orig_mvs[0]['frame_type'] if len(orig_mvs) > 0 else 'unknown'
            
            results.append({
                'frame_idx': frame_idx,
                'frame_type': frame_type,
                'mv_count': len(orig_mvs),
                'psnr': psnr,
                'psnr_degradation': 50.0 - psnr,
                'orig_avg_magnitude': orig_mag,
                'steg_avg_magnitude': steg_mag,
                'avg_distortion': distortion,
                'max_distortion': max_distortion,
                'modified_count': modified_count,
                'modification_rate': mod_rate,
                'mse': mse,
                'max_mv_value': np.abs(orig_array).max()
            })
        
        return results
    
    def find_problematic_frames(self, results: List[Dict], threshold: float = 5.0) -> List[Dict]:
        """Find frames with PSNR degradation > threshold"""
        return [r for r in results if r['psnr_degradation'] > threshold]
    
    def print_analysis(self, results: List[Dict]):
        """Print detailed analysis of PSNR issues"""
        print("\n" + "="*80)
        print("PSNR DEGRADATION ANALYSIS")
        print("="*80 + "\n")
        
        # Overall statistics
        psnr_values = [r['psnr'] for r in results]
        degradations = [r['psnr_degradation'] for r in results]
        
        print("OVERALL STATISTICS:")
        print(f"  Total frames analyzed: {len(results)}")
        print(f"  Average PSNR: {np.mean(psnr_values):.2f} dB")
        print(f"  Average degradation: {np.mean(degradations):.4f} dB")
        print(f"  Max degradation: {np.max(degradations):.4f} dB")
        print(f"  Std degradation: {np.std(degradations):.4f} dB")
        
        # Find problematic frames
        bad_frames = self.find_problematic_frames(results, threshold=5.0)
        
        print(f"\n⚠ PROBLEMATIC FRAMES (degradation > 5.0 dB): {len(bad_frames)}")
        
        if len(bad_frames) > 0:
            print("\nTOP 10 WORST FRAMES:")
            print(f"{'Frame':<8} {'Type':<6} {'MVs':<8} {'PSNR':<10} {'Degrad':<10} {'MSE':<12} {'MaxMV':<10} {'ModRate':<8}")
            print("-" * 80)
            
            # Sort by degradation
            bad_sorted = sorted(bad_frames, key=lambda x: x['psnr_degradation'], reverse=True)[:10]
            
            for r in bad_sorted:
                print(f"{r['frame_idx']:<8} {r['frame_type']:<6} {r['mv_count']:<8} "
                      f"{r['psnr']:<10.2f} {r['psnr_degradation']:<10.4f} "
                      f"{r['mse']:<12.8f} {r['max_mv_value']:<10.2f} {r['modification_rate']*100:<8.2f}%")
        
        # Analyze correlation
        print("\n" + "="*80)
        print("ROOT CAUSE ANALYSIS")
        print("="*80 + "\n")
        
        # Check if low MV count causes issues
        low_mv_frames = [r for r in results if r['mv_count'] < 100]
        avg_degrad_low_mv = np.mean([r['psnr_degradation'] for r in low_mv_frames]) if low_mv_frames else 0
        
        high_mv_frames = [r for r in results if r['mv_count'] >= 100]
        avg_degrad_high_mv = np.mean([r['psnr_degradation'] for r in high_mv_frames]) if high_mv_frames else 0
        
        print(f"1. MV COUNT IMPACT:")
        print(f"   Frames with <100 MVs: {len(low_mv_frames)} frames, avg degradation: {avg_degrad_low_mv:.4f} dB")
        print(f"   Frames with ≥100 MVs: {len(high_mv_frames)} frames, avg degradation: {avg_degrad_high_mv:.4f} dB")
        
        # Check if small MV values cause numerical issues
        small_mv_frames = [r for r in results if r['max_mv_value'] < 2.0]
        avg_degrad_small = np.mean([r['psnr_degradation'] for r in small_mv_frames]) if small_mv_frames else 0
        
        large_mv_frames = [r for r in results if r['max_mv_value'] >= 2.0]
        avg_degrad_large = np.mean([r['psnr_degradation'] for r in large_mv_frames]) if large_mv_frames else 0
        
        print(f"\n2. MV MAGNITUDE IMPACT:")
        print(f"   Frames with max MV <2 pixels: {len(small_mv_frames)} frames, avg degradation: {avg_degrad_small:.4f} dB")
        print(f"   Frames with max MV ≥2 pixels: {len(large_mv_frames)} frames, avg degradation: {avg_degrad_large:.4f} dB")
        
        # Check modification rate impact
        high_mod_frames = [r for r in results if r['modification_rate'] > 0.02]
        avg_degrad_high_mod = np.mean([r['psnr_degradation'] for r in high_mod_frames]) if high_mod_frames else 0
        
        low_mod_frames = [r for r in results if r['modification_rate'] <= 0.02]
        avg_degrad_low_mod = np.mean([r['psnr_degradation'] for r in low_mod_frames]) if low_mod_frames else 0
        
        print(f"\n3. MODIFICATION RATE IMPACT:")
        print(f"   Frames with >2% mod rate: {len(high_mod_frames)} frames, avg degradation: {avg_degrad_high_mod:.4f} dB")
        print(f"   Frames with ≤2% mod rate: {len(low_mod_frames)} frames, avg degradation: {avg_degrad_low_mod:.4f} dB")
        
        # Frame type analysis
        frame_types = {}
        for r in results:
            ft = r['frame_type']
            if ft not in frame_types:
                frame_types[ft] = []
            frame_types[ft].append(r['psnr_degradation'])
        
        print(f"\n4. FRAME TYPE IMPACT:")
        for ftype, degrads in frame_types.items():
            print(f"   Type '{ftype}': {len(degrads)} frames, avg degradation: {np.mean(degrads):.4f} dB")
        
        print("\n" + "="*80)
        print("CONCLUSION")
        print("="*80 + "\n")
        
        # Identify main cause
        if avg_degrad_small > avg_degrad_large * 2:
            print("⚠ MAIN CAUSE: Frames with SMALL MV values (<2 pixels)")
            print("  → PSNR calculation becomes unstable when max_val is very small")
            print("  → Solution: Use video pixel domain PSNR instead of MV-based PSNR")
        elif avg_degrad_low_mv > avg_degrad_high_mv * 2:
            print("⚠ MAIN CAUSE: Frames with FEW MVs (<100)")
            print("  → Small sample size causes statistical instability")
            print("  → These are likely I-frames with minimal motion")
        elif avg_degrad_high_mod > avg_degrad_low_mod * 2:
            print("⚠ MAIN CAUSE: High modification rate (>2%)")
            print("  → More modifications = more distortion")
        else:
            print("✓ PSNR degradation is EVENLY distributed across all frame types")
            print("  → No single root cause identified")
            print("  → MV-based PSNR may not be the best quality metric")
        
        print("\n")
    
    def plot_detailed_analysis(self, results: List[Dict], output_dir: Path = Path("benchmark_results")):
        """Plot detailed analysis charts"""
        output_dir.mkdir(exist_ok=True)
        
        fig, axes = plt.subplots(2, 3, figsize=(20, 12))
        
        frames = [r['frame_idx'] for r in results]
        
        # 1. PSNR degradation over frames
        ax1 = axes[0, 0]
        degradations = [r['psnr_degradation'] for r in results]
        ax1.scatter(frames, degradations, s=20, alpha=0.6, c=degradations, cmap='RdYlGn_r')
        ax1.axhline(y=5.0, color='red', linestyle='--', linewidth=2, label='Critical (>5dB)')
        ax1.axhline(y=1.0, color='orange', linestyle='--', linewidth=2, label='Warning (>1dB)')
        ax1.set_xlabel('Frame Number', fontsize=12, fontweight='bold')
        ax1.set_ylabel('PSNR Degradation (dB)', fontsize=12, fontweight='bold')
        ax1.set_title('PSNR Degradation per Frame', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        
        # 2. MV count vs PSNR degradation
        ax2 = axes[0, 1]
        mv_counts = [r['mv_count'] for r in results]
        ax2.scatter(mv_counts, degradations, s=30, alpha=0.5, c='#E74C3C')
        ax2.set_xlabel('MV Count per Frame', fontsize=12, fontweight='bold')
        ax2.set_ylabel('PSNR Degradation (dB)', fontsize=12, fontweight='bold')
        ax2.set_title('MV Count vs PSNR Degradation', fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3)
        
        # 3. Max MV value vs PSNR degradation
        ax3 = axes[0, 2]
        max_mvs = [r['max_mv_value'] for r in results]
        ax3.scatter(max_mvs, degradations, s=30, alpha=0.5, c='#9B59B6')
        ax3.set_xlabel('Max MV Magnitude (pixels)', fontsize=12, fontweight='bold')
        ax3.set_ylabel('PSNR Degradation (dB)', fontsize=12, fontweight='bold')
        ax3.set_title('MV Magnitude vs PSNR Degradation', fontsize=14, fontweight='bold')
        ax3.grid(True, alpha=0.3)
        ax3.set_xlim([0, min(50, max(max_mvs))])
        
        # 4. Modification rate vs PSNR degradation
        ax4 = axes[1, 0]
        mod_rates = [r['modification_rate']*100 for r in results]
        ax4.scatter(mod_rates, degradations, s=30, alpha=0.5, c='#F39C12')
        ax4.set_xlabel('Modification Rate (%)', fontsize=12, fontweight='bold')
        ax4.set_ylabel('PSNR Degradation (dB)', fontsize=12, fontweight='bold')
        ax4.set_title('Modification Rate vs PSNR Degradation', fontsize=14, fontweight='bold')
        ax4.grid(True, alpha=0.3)
        
        # 5. MSE distribution
        ax5 = axes[1, 1]
        mses = [r['mse'] for r in results]
        ax5.hist(np.log10(np.array(mses) + 1e-10), bins=50, color='#3498DB', alpha=0.7, edgecolor='black')
        ax5.set_xlabel('log10(MSE)', fontsize=12, fontweight='bold')
        ax5.set_ylabel('Frequency', fontsize=12, fontweight='bold')
        ax5.set_title('MSE Distribution (log scale)', fontsize=14, fontweight='bold')
        ax5.grid(True, alpha=0.3)
        
        # 6. Frame type distribution
        ax6 = axes[1, 2]
        frame_types = {}
        for r in results:
            ft = r['frame_type']
            if ft not in frame_types:
                frame_types[ft] = []
            frame_types[ft].append(r['psnr_degradation'])
        
        type_labels = list(frame_types.keys())
        type_means = [np.mean(frame_types[t]) for t in type_labels]
        type_stds = [np.std(frame_types[t]) for t in type_labels]
        
        x_pos = np.arange(len(type_labels))
        ax6.bar(x_pos, type_means, yerr=type_stds, capsize=5, color='#27AE60', alpha=0.7, edgecolor='black')
        ax6.set_xticks(x_pos)
        ax6.set_xticklabels(type_labels)
        ax6.set_xlabel('Frame Type', fontsize=12, fontweight='bold')
        ax6.set_ylabel('Avg PSNR Degradation (dB)', fontsize=12, fontweight='bold')
        ax6.set_title('PSNR Degradation by Frame Type', fontsize=14, fontweight='bold')
        ax6.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        output_path = output_dir / "psnr_analysis_detailed.png"
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"[OK] Saved detailed analysis: {output_path}\n")

def main():
    print("\n" + "="*80)
    print("ANALYZING PSNR DEGRADATION ROOT CAUSES")
    print("="*80 + "\n")
    
    analyzer = PSNRAnalyzer("benchmark_stego.json")
    
    # Analyze all frames
    results = analyzer.analyze_all_frames()
    
    # Print analysis
    analyzer.print_analysis(results)
    
    # Plot detailed charts
    analyzer.plot_detailed_analysis(results)
    
    print("[SUCCESS] Analysis complete!\n")

if __name__ == "__main__":
    main()
