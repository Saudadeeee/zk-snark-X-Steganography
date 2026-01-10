"""
Motion Vector Statistics Analyzer
Analyzes statistical properties of motion vectors for steganography feasibility
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict, Tuple
from collections import Counter
import os


class MVStatistics:
    """Statistical analysis of Motion Vectors"""

    def __init__(self, mv_data: List):
        """
        Initialize statistics analyzer

        Args:
            mv_data: List of MVData objects from parser
        """
        self.mv_data = mv_data
        self.stats = {}

    def compute_all_statistics(self) -> Dict:
        """
        Compute all statistical metrics

        Returns:
            Dictionary containing all statistics
        """
        if not self.mv_data:
            print("Warning: No MV data to analyze")
            return {}

        print("Computing statistics...")

        self.stats = {
            'basic': self._compute_basic_stats(),
            'distribution': self._compute_distribution_stats(),
            'parity': self._compute_parity_stats(),
            'spatial': self._compute_spatial_stats(),
            'temporal': self._compute_temporal_stats(),
            'capacity': self._compute_capacity_estimates()
        }

        return self.stats

    def _compute_basic_stats(self) -> Dict:
        """Compute basic statistics"""
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]
        magnitudes = [mv.magnitude for mv in self.mv_data]

        # Separate by frame type
        p_mvs = [mv for mv in self.mv_data if mv.frame_type == 'P']
        b_mvs = [mv for mv in self.mv_data if mv.frame_type == 'B']

        # Count zero MVs
        zero_mvs = sum(1 for mv in self.mv_data if mv.mvx == 0 and mv.mvy == 0)

        return {
            'total_vectors': len(self.mv_data),
            'p_frame_vectors': len(p_mvs),
            'b_frame_vectors': len(b_mvs),
            'zero_mvs': zero_mvs,
            'zero_mv_ratio': zero_mvs / len(self.mv_data) if self.mv_data else 0,
            'mvx': {
                'min': min(mvx_values),
                'max': max(mvx_values),
                'mean': np.mean(mvx_values),
                'std': np.std(mvx_values),
                'median': np.median(mvx_values)
            },
            'mvy': {
                'min': min(mvy_values),
                'max': max(mvy_values),
                'mean': np.mean(mvy_values),
                'std': np.std(mvy_values),
                'median': np.median(mvy_values)
            },
            'magnitude': {
                'min': min(magnitudes),
                'max': max(magnitudes),
                'mean': np.mean(magnitudes),
                'std': np.std(magnitudes),
                'median': np.median(magnitudes)
            }
        }

    def _compute_distribution_stats(self) -> Dict:
        """Compute distribution statistics"""
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]

        # Histogram data
        mvx_hist, mvx_bins = np.histogram(mvx_values, bins=50)
        mvy_hist, mvy_bins = np.histogram(mvy_values, bins=50)

        # Magnitude ranges
        magnitudes = [mv.magnitude for mv in self.mv_data]
        small_motion = sum(1 for m in magnitudes if m < 5)
        medium_motion = sum(1 for m in magnitudes if 5 <= m < 15)
        large_motion = sum(1 for m in magnitudes if m >= 15)

        return {
            'magnitude_ranges': {
                'small (<5)': small_motion,
                'medium (5-15)': medium_motion,
                'large (>=15)': large_motion
            },
            'magnitude_ratios': {
                'small': small_motion / len(magnitudes),
                'medium': medium_motion / len(magnitudes),
                'large': large_motion / len(magnitudes)
            }
        }

    def _compute_parity_stats(self) -> Dict:
        """
        Compute parity statistics (critical for LSB steganography)
        """
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]

        # Parity distribution
        mvx_even = sum(1 for x in mvx_values if x % 2 == 0)
        mvx_odd = len(mvx_values) - mvx_even

        mvy_even = sum(1 for y in mvy_values if y % 2 == 0)
        mvy_odd = len(mvy_values) - mvy_even

        # Compute entropy of parity bits
        def compute_parity_entropy(values):
            """Compute entropy of parity bits"""
            total = len(values)
            even = sum(1 for v in values if v % 2 == 0)
            odd = total - even

            p_even = even / total if total > 0 else 0
            p_odd = odd / total if total > 0 else 0

            entropy = 0
            if p_even > 0:
                entropy -= p_even * np.log2(p_even)
            if p_odd > 0:
                entropy -= p_odd * np.log2(p_odd)

            return entropy

        mvx_parity_entropy = compute_parity_entropy(mvx_values)
        mvy_parity_entropy = compute_parity_entropy(mvy_values)

        return {
            'mvx_parity': {
                'even': mvx_even,
                'odd': mvx_odd,
                'even_ratio': mvx_even / len(mvx_values),
                'entropy': mvx_parity_entropy
            },
            'mvy_parity': {
                'even': mvy_even,
                'odd': mvy_odd,
                'even_ratio': mvy_even / len(mvy_values),
                'entropy': mvy_parity_entropy
            },
            'analysis': {
                'mvx_balanced': abs(mvx_even - mvx_odd) / len(mvx_values) < 0.1,
                'mvy_balanced': abs(mvy_even - mvy_odd) / len(mvy_values) < 0.1,
                'note': 'Balanced parity (close to 50/50) is good for LSB steganography'
            }
        }

    def _compute_spatial_stats(self) -> Dict:
        """Compute spatial correlation statistics"""
        # Group MVs by frame
        frames = {}
        for mv in self.mv_data:
            if mv.frame_idx not in frames:
                frames[mv.frame_idx] = []
            frames[mv.frame_idx].append(mv)

        # Compute spatial correlation for each frame
        spatial_correlations = []

        for frame_idx, frame_mvs in frames.items():
            if len(frame_mvs) < 2:
                continue

            # Create grid of MVs
            mv_dict = {(mv.mb_x, mv.mb_y): mv for mv in frame_mvs}

            # Calculate correlation with neighbors
            correlations = []
            for mv in frame_mvs:
                neighbors = []

                # Check 4-connected neighbors
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    neighbor_pos = (mv.mb_x + dx, mv.mb_y + dy)
                    if neighbor_pos in mv_dict:
                        neighbor = mv_dict[neighbor_pos]
                        # Euclidean distance between MVs
                        dist = np.sqrt((mv.mvx - neighbor.mvx)**2 + (mv.mvy - neighbor.mvy)**2)
                        correlations.append(dist)

            if correlations:
                spatial_correlations.append(np.mean(correlations))

        avg_spatial_correlation = np.mean(spatial_correlations) if spatial_correlations else 0

        return {
            'avg_neighbor_distance': avg_spatial_correlation,
            'note': 'Lower values indicate higher spatial correlation'
        }

    def _compute_temporal_stats(self) -> Dict:
        """Compute temporal correlation statistics"""
        # Group MVs by macroblock position
        mb_positions = {}
        for mv in self.mv_data:
            pos = (mv.mb_x, mv.mb_y)
            if pos not in mb_positions:
                mb_positions[pos] = []
            mb_positions[pos].append(mv)

        # Compute temporal stability (how much MVs change over time at same position)
        temporal_variations = []

        for pos, mvs in mb_positions.items():
            if len(mvs) < 2:
                continue

            # Sort by frame index
            mvs_sorted = sorted(mvs, key=lambda m: m.frame_idx)

            # Compute frame-to-frame variation
            for i in range(len(mvs_sorted) - 1):
                mv1 = mvs_sorted[i]
                mv2 = mvs_sorted[i + 1]

                variation = np.sqrt((mv1.mvx - mv2.mvx)**2 + (mv1.mvy - mv2.mvy)**2)
                temporal_variations.append(variation)

        avg_temporal_variation = np.mean(temporal_variations) if temporal_variations else 0

        return {
            'avg_temporal_variation': avg_temporal_variation,
            'note': 'Lower values indicate more stable MVs over time'
        }

    def _compute_capacity_estimates(self) -> Dict:
        """
        Estimate steganography capacity

        Assumes embedding in P-frames only, using parity embedding
        """
        p_mvs = [mv for mv in self.mv_data if mv.frame_type == 'P']

        # Count non-zero MVs (safer for embedding)
        non_zero_mvs = [mv for mv in p_mvs if mv.mvx != 0 or mv.mvy != 0]

        # Medium to large motion MVs (safest)
        safe_mvs = [mv for mv in p_mvs if mv.magnitude >= 5]

        # Get number of frames
        frames = set(mv.frame_idx for mv in self.mv_data)
        num_frames = len(frames)
        p_frames = set(mv.frame_idx for mv in p_mvs)
        num_p_frames = len(p_frames)

        # Estimate bits per frame with different strategies
        estimates = {
            'all_p_mvs': {
                'total_vectors': len(p_mvs),
                'bits_per_component': len(p_mvs),  # 1 bit per mvx or mvy
                'bits_total': len(p_mvs) * 2,  # both x and y
                'bits_per_frame': len(p_mvs) * 2 / num_p_frames if num_p_frames > 0 else 0
            },
            'non_zero_mvs': {
                'total_vectors': len(non_zero_mvs),
                'bits_total': len(non_zero_mvs) * 2,
                'bits_per_frame': len(non_zero_mvs) * 2 / num_p_frames if num_p_frames > 0 else 0
            },
            'safe_mvs': {
                'total_vectors': len(safe_mvs),
                'bits_total': len(safe_mvs) * 2,
                'bits_per_frame': len(safe_mvs) * 2 / num_p_frames if num_p_frames > 0 else 0
            }
        }

        # Sparse embedding (using only 10%, 25%, 50% of safe MVs)
        for ratio in [0.1, 0.25, 0.5]:
            estimates[f'sparse_{int(ratio*100)}pct'] = {
                'total_vectors': int(len(safe_mvs) * ratio),
                'bits_total': int(len(safe_mvs) * ratio * 2),
                'bits_per_frame': int(len(safe_mvs) * ratio * 2) / num_p_frames if num_p_frames > 0 else 0
            }

        return {
            'frames_info': {
                'total_frames': num_frames,
                'p_frames': num_p_frames,
                'p_frame_ratio': num_p_frames / num_frames if num_frames > 0 else 0
            },
            'capacity_estimates': estimates,
            'recommendations': {
                'strategy': 'Use safe_mvs or sparse embedding for steganography',
                'target_bits_per_frame': estimates['safe_mvs']['bits_per_frame']
            }
        }

    def create_visualization_plots(self, output_dir: str):
        """
        Create comprehensive visualization plots

        Args:
            output_dir: Directory to save plots
        """
        os.makedirs(output_dir, exist_ok=True)

        print(f"Creating visualization plots in {output_dir}...")

        # 1. MV Magnitude Histogram
        self._plot_magnitude_histogram(os.path.join(output_dir, 'magnitude_histogram.png'))

        # 2. MV Scatter Plot
        self._plot_mv_scatter(os.path.join(output_dir, 'mv_scatter.png'))

        # 3. Parity Distribution
        self._plot_parity_distribution(os.path.join(output_dir, 'parity_distribution.png'))

        # 4. Magnitude by Frame Type
        self._plot_magnitude_by_frame_type(os.path.join(output_dir, 'magnitude_by_frame_type.png'))

        print("[OK] All visualization plots created")

    def _plot_magnitude_histogram(self, output_path: str):
        """Plot MV magnitude distribution"""
        magnitudes = [mv.magnitude for mv in self.mv_data]

        plt.figure(figsize=(10, 6))
        plt.hist(magnitudes, bins=50, alpha=0.7, color='steelblue', edgecolor='black')
        plt.xlabel('MV Magnitude (pixels)')
        plt.ylabel('Frequency')
        plt.title('Motion Vector Magnitude Distribution')
        plt.grid(True, alpha=0.3)
        plt.axvline(np.mean(magnitudes), color='red', linestyle='--', label=f'Mean: {np.mean(magnitudes):.2f}')
        plt.axvline(np.median(magnitudes), color='green', linestyle='--', label=f'Median: {np.median(magnitudes):.2f}')
        plt.legend()
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

    def _plot_mv_scatter(self, output_path: str):
        """Plot MVx vs MVy scatter plot"""
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]

        plt.figure(figsize=(10, 10))
        plt.scatter(mvx_values, mvy_values, alpha=0.3, s=1)
        plt.xlabel('MVx')
        plt.ylabel('MVy')
        plt.title('Motion Vector Scatter Plot (MVx vs MVy)')
        plt.grid(True, alpha=0.3)
        plt.axhline(0, color='black', linewidth=0.5)
        plt.axvline(0, color='black', linewidth=0.5)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

    def _plot_parity_distribution(self, output_path: str):
        """Plot parity distribution"""
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]

        mvx_even = sum(1 for x in mvx_values if x % 2 == 0)
        mvx_odd = len(mvx_values) - mvx_even
        mvy_even = sum(1 for y in mvy_values if y % 2 == 0)
        mvy_odd = len(mvy_values) - mvy_even

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        # MVx parity
        ax1.bar(['Even', 'Odd'], [mvx_even, mvx_odd], color=['#2E86AB', '#A23B72'])
        ax1.set_ylabel('Count')
        ax1.set_title(f'MVx Parity Distribution\n(Even: {mvx_even/len(mvx_values)*100:.1f}%)')
        ax1.grid(True, alpha=0.3, axis='y')

        # MVy parity
        ax2.bar(['Even', 'Odd'], [mvy_even, mvy_odd], color=['#2E86AB', '#A23B72'])
        ax2.set_ylabel('Count')
        ax2.set_title(f'MVy Parity Distribution\n(Even: {mvy_even/len(mvy_values)*100:.1f}%)')
        ax2.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

    def _plot_magnitude_by_frame_type(self, output_path: str):
        """Plot magnitude distribution by frame type"""
        p_magnitudes = [mv.magnitude for mv in self.mv_data if mv.frame_type == 'P']
        b_magnitudes = [mv.magnitude for mv in self.mv_data if mv.frame_type == 'B']

        plt.figure(figsize=(10, 6))

        if p_magnitudes:
            plt.hist(p_magnitudes, bins=30, alpha=0.6, label='P-frames', color='blue')

        if b_magnitudes:
            plt.hist(b_magnitudes, bins=30, alpha=0.6, label='B-frames', color='red')

        plt.xlabel('MV Magnitude')
        plt.ylabel('Frequency')
        plt.title('MV Magnitude Distribution by Frame Type')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

    def save_statistics(self, output_path: str):
        """Save statistics to JSON file"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.stats, f, indent=2)

        print(f"[OK] Statistics saved to: {output_path}")

    def print_summary(self):
        """Print a summary of key statistics"""
        if not self.stats:
            self.compute_all_statistics()

        print("\n" + "="*60)
        print("MOTION VECTOR STATISTICS SUMMARY")
        print("="*60)

        basic = self.stats['basic']
        print(f"\n[Data] Basic Statistics:")
        print(f"  Total MVs: {basic['total_vectors']}")
        print(f"  P-frame MVs: {basic['p_frame_vectors']}")
        print(f"  B-frame MVs: {basic['b_frame_vectors']}")
        print(f"  Zero MVs: {basic['zero_mvs']} ({basic['zero_mv_ratio']*100:.1f}%)")

        print(f"\n[Magnitude] Magnitude:")
        mag = basic['magnitude']
        print(f"  Range: [{mag['min']:.2f}, {mag['max']:.2f}]")
        print(f"  Mean: {mag['mean']:.2f} ± {mag['std']:.2f}")
        print(f"  Median: {mag['median']:.2f}")

        parity = self.stats['parity']
        print(f"\n[Parity] Parity Analysis (for LSB embedding):")
        print(f"  MVx - Even: {parity['mvx_parity']['even_ratio']*100:.1f}%, Entropy: {parity['mvx_parity']['entropy']:.3f}")
        print(f"  MVy - Even: {parity['mvy_parity']['even_ratio']*100:.1f}%, Entropy: {parity['mvy_parity']['entropy']:.3f}")
        print(f"  Balanced: {parity['analysis']['mvx_balanced'] and parity['analysis']['mvy_balanced']}")

        capacity = self.stats['capacity']
        print(f"\n[Capacity] Embedding Capacity Estimates:")
        print(f"  P-frames: {capacity['frames_info']['p_frames']} ({capacity['frames_info']['p_frame_ratio']*100:.1f}%)")
        safe = capacity['capacity_estimates']['safe_mvs']
        print(f"  Safe MVs (magnitude >= 5): {safe['total_vectors']}")
        print(f"  Bits per P-frame: {safe['bits_per_frame']:.1f}")
        print(f"  Total capacity: {safe['bits_total']} bits ({safe['bits_total']//8} bytes)")

        print("\n" + "="*60)


def main():
    """Example usage"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python statistics.py <mv_data.json> [output_dir]")
        print("\nExample:")
        print("  python statistics.py results/mv_data/video_mv.json results/stats/")
        return

    mv_json_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else './results/stats/'

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Load MV data
        print(f"Loading MV data from: {mv_json_path}")
        with open(mv_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Convert to MVData objects
        from tools.mv_extractor.parser import MVData
        mv_data = []
        for mv_dict in data['motion_vectors']:
            mv = MVData(**{k: v for k, v in mv_dict.items() if k in [
                'frame_idx', 'frame_type', 'timestamp', 'mb_x', 'mb_y', 'mvx', 'mvy', 'block_type'
            ]})
            mv_data.append(mv)

        # Create analyzer
        analyzer = MVStatistics(mv_data)

        # Compute statistics
        stats = analyzer.compute_all_statistics()

        # Print summary
        analyzer.print_summary()

        # Save statistics
        stats_file = os.path.join(output_dir, 'statistics.json')
        analyzer.save_statistics(stats_file)

        # Create visualizations
        analyzer.create_visualization_plots(output_dir)

        print(f"\n[OK] Analysis complete! Results saved to: {output_dir}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
