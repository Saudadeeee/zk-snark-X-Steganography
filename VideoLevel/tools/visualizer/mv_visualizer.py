"""
Motion Vector Visualizer
Visualizes motion vectors extracted from H.264 videos
"""

import subprocess
import os
import json
from typing import List, Optional
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np


class MVVisualizer:
    """Visualize Motion Vectors"""

    def __init__(self, video_path: str):
        """
        Initialize MV Visualizer

        Args:
            video_path: Path to input video file
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        self.video_path = video_path

    def create_overlay_video(self, output_path: str, mv_type: str = 'pf'):
        """
        Create video with motion vector overlay using FFmpeg

        Args:
            output_path: Path to save output video
            mv_type: Type of MVs to display
                    'pf' - P-frame forward
                    'bf' - B-frame forward
                    'bb' - B-frame backward
                    'pf+bf' - Both P and B forward
                    'pf+bf+bb' - All MVs

        Returns:
            Path to output video
        """
        print(f"Creating MV overlay video...")
        print(f"Input: {self.video_path}")
        print(f"Output: {output_path}")
        print(f"MV type: {mv_type}")

        cmd = [
            'ffmpeg',
            '-flags2', '+export_mvs',
            '-i', self.video_path,
            '-vf', f'codecview=mv={mv_type}:mv_type=fp:frame_type=',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '18',
            '-y',  # Overwrite output
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                check=True
            )
            print(f"[OK] MV overlay video created: {output_path}")
            return output_path

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFmpeg overlay creation failed: {e}\n{e.stderr}")

    def create_mv_arrows_plot(self, mv_data: List, output_path: str,
                              frame_idx: int = 0, subsample: int = 1):
        """
        Create a plot showing MV as arrows on a grid

        Args:
            mv_data: List of MVData objects from parser
            output_path: Path to save plot image
            frame_idx: Which frame to visualize
            subsample: Only show every Nth vector (for clarity)
        """
        # Filter MVs for specific frame
        frame_mvs = [mv for mv in mv_data if mv.frame_idx == frame_idx]

        if not frame_mvs:
            print(f"No MVs found for frame {frame_idx}")
            return

        # Get video dimensions from first MV
        max_x = max(mv.mb_x for mv in mv_data)
        max_y = max(mv.mb_y for mv in mv_data)

        fig, ax = plt.subplots(figsize=(12, 8))

        # Subsample for clarity
        frame_mvs = frame_mvs[::subsample]

        # Draw arrows for each MV
        for mv in frame_mvs:
            x = mv.mb_x * 16  # Convert MB coordinates to pixels
            y = mv.mb_y * 16

            # Scale MVs for visibility
            dx = mv.mvx * 2
            dy = mv.mvy * 2

            # Color based on magnitude
            magnitude = mv.magnitude
            if magnitude < 5:
                color = 'green'
            elif magnitude < 15:
                color = 'yellow'
            else:
                color = 'red'

            ax.arrow(x, y, dx, dy,
                    head_width=10, head_length=10,
                    fc=color, ec=color, alpha=0.6,
                    linewidth=1)

        ax.set_xlim(0, (max_x + 1) * 16)
        ax.set_ylim((max_y + 1) * 16, 0)  # Invert Y axis
        ax.set_xlabel('X (pixels)')
        ax.set_ylabel('Y (pixels)')
        ax.set_title(f'Motion Vectors - Frame {frame_idx} ({len(frame_mvs)} vectors)')
        ax.grid(True, alpha=0.3)

        # Add legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], marker='>', color='green', label='Low (<5)', markersize=10),
            Line2D([0], [0], marker='>', color='yellow', label='Medium (5-15)', markersize=10),
            Line2D([0], [0], marker='>', color='red', label='High (>15)', markersize=10)
        ]
        ax.legend(handles=legend_elements, title='MV Magnitude')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[OK] MV arrows plot saved: {output_path}")

    def create_magnitude_heatmap(self, mv_data: List, output_path: str, frame_idx: int = 0):
        """
        Create heatmap showing MV magnitude across the frame

        Args:
            mv_data: List of MVData objects
            output_path: Path to save heatmap image
            frame_idx: Which frame to visualize
        """
        # Filter MVs for specific frame
        frame_mvs = [mv for mv in mv_data if mv.frame_idx == frame_idx]

        if not frame_mvs:
            print(f"No MVs found for frame {frame_idx}")
            return

        # Get dimensions
        max_x = max(mv.mb_x for mv in mv_data) + 1
        max_y = max(mv.mb_y for mv in mv_data) + 1

        # Create magnitude grid
        magnitude_grid = np.zeros((max_y, max_x))

        for mv in frame_mvs:
            magnitude_grid[mv.mb_y, mv.mb_x] = mv.magnitude

        # Create heatmap
        fig, ax = plt.subplots(figsize=(12, 8))

        im = ax.imshow(magnitude_grid, cmap='hot', interpolation='nearest', aspect='auto')

        ax.set_xlabel('Macroblock X')
        ax.set_ylabel('Macroblock Y')
        ax.set_title(f'Motion Vector Magnitude Heatmap - Frame {frame_idx}')

        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('MV Magnitude (pixels)')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[OK] Magnitude heatmap saved: {output_path}")

    def create_frame_comparison(self, frame_number: int, output_path: str):
        """
        Extract a specific frame from original and MV overlay video for comparison

        Args:
            frame_number: Frame number to extract
            output_path: Base path for output images (will create _original.png and _overlay.png)
        """
        base_name = os.path.splitext(output_path)[0]
        original_frame = f"{base_name}_original.png"

        # Extract original frame
        cmd = [
            'ffmpeg',
            '-i', self.video_path,
            '-vf', f'select=eq(n\\,{frame_number})',
            '-vframes', '1',
            '-y',
            original_frame
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            print(f"[OK] Original frame extracted: {original_frame}")

        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not extract frame: {e}")

    def create_temporal_mv_plot(self, mv_data: List, output_path: str):
        """
        Create plot showing MV activity over time

        Args:
            mv_data: List of MVData objects
            output_path: Path to save plot
        """
        # Group by frame
        frames = {}
        for mv in mv_data:
            if mv.frame_idx not in frames:
                frames[mv.frame_idx] = []
            frames[mv.frame_idx].append(mv)

        # Calculate average magnitude per frame
        frame_indices = sorted(frames.keys())
        avg_magnitudes = []
        max_magnitudes = []
        mv_counts = []

        for idx in frame_indices:
            frame_mvs = frames[idx]
            magnitudes = [mv.magnitude for mv in frame_mvs]
            avg_magnitudes.append(np.mean(magnitudes))
            max_magnitudes.append(np.max(magnitudes))
            mv_counts.append(len(frame_mvs))

        # Create plot with subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # Plot 1: MV magnitude over time
        ax1.plot(frame_indices, avg_magnitudes, label='Average Magnitude', linewidth=2)
        ax1.plot(frame_indices, max_magnitudes, label='Max Magnitude', alpha=0.6, linewidth=1)
        ax1.set_xlabel('Frame Index')
        ax1.set_ylabel('MV Magnitude')
        ax1.set_title('Motion Vector Magnitude Over Time')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Plot 2: Number of MVs per frame
        ax2.bar(frame_indices, mv_counts, alpha=0.7, color='steelblue')
        ax2.set_xlabel('Frame Index')
        ax2.set_ylabel('Number of MVs')
        ax2.set_title('Motion Vector Count Per Frame')
        ax2.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[OK] Temporal MV plot saved: {output_path}")


def main():
    """Example usage"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python mv_visualizer.py <video_path> <output_dir>")
        print("\nExample:")
        print("  python mv_visualizer.py input.mp4 ./results/visualizations/")
        return

    video_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else './results/visualizations/'

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    try:
        visualizer = MVVisualizer(video_path)

        # Create MV overlay video
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        overlay_video = os.path.join(output_dir, f"{base_name}_mv_overlay.mp4")

        visualizer.create_overlay_video(overlay_video, mv_type='pf+bf')

        print("\n[OK] Visualization complete!")
        print(f"Output directory: {output_dir}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
