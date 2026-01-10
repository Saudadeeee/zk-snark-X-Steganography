#!/usr/bin/env python3
"""
ZK-SNARK Video Steganography - Analysis Tool
Analyze H.264 video motion vectors for steganography capacity
"""

import sys
import argparse
from pathlib import Path
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zk_mv_stego import H264MVExtractor, MVStatistics


def main():
    parser = argparse.ArgumentParser(
        description="Analyze H.264 video for MV steganography capacity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic analysis
  python analyze.py -i video.mp4
  
  # Detailed statistics with visualization
  python analyze.py -i video.mp4 --detailed --visualize
  
  # Export analysis to JSON
  python analyze.py -i video.mp4 --output analysis.json
  
  # Analyze specific frame range
  python analyze.py -i video.mp4 --max-frames 100
"""
    )
    
    # Required arguments
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Input H.264 video file"
    )
    
    # Optional arguments
    parser.add_argument(
        "--max-frames",
        type=int,
        help="Maximum frames to analyze"
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed per-frame statistics"
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate MV visualization (requires matplotlib)"
    )
    parser.add_argument(
        "--output",
        help="Export analysis results to JSON file"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Validate input
    if not Path(args.input).exists():
        print(f"❌ Error: Video file not found: {args.input}")
        sys.exit(1)
    
    print("=" * 70)
    print("📊 ZK-SNARK Video Steganography - MV Analysis")
    print("=" * 70)
    print(f"Video: {args.input}")
    print("=" * 70)
    
    try:
        # Extract motion vectors
        print("\n🔍 Extracting motion vectors...")
        extractor = H264MVExtractor()
        mv_data = extractor.extract_from_video(
            args.input,
            max_frames=args.max_frames
        )
        
        if not mv_data or not mv_data.motion_vectors:
            print("❌ No motion vectors found in video")
            sys.exit(1)
        
        # Compute statistics
        print("📈 Computing statistics...")
        stats = MVStatistics()
        analysis = stats.compute_full_statistics(mv_data)
        
        # Print summary
        print("\n" + "=" * 70)
        print("📋 SUMMARY")
        print("=" * 70)
        print(f"Total MVs:           {analysis['summary']['total_mvs']:,}")
        print(f"Suitable carriers:   {analysis['summary']['suitable_carriers']:,}")
        print(f"Capacity per frame:  {analysis['summary']['capacity_per_frame']:,} bytes")
        print(f"Total capacity:      {analysis['summary']['total_capacity']:,} bytes")
        print(f"Entropy:             {analysis['summary']['entropy']:.4f}")
        print(f"Quality:             {analysis['summary']['quality_score']}")
        
        # Detailed frame-by-frame
        if args.detailed and analysis.get("per_frame"):
            print("\n" + "=" * 70)
            print("📝 DETAILED PER-FRAME STATISTICS")
            print("=" * 70)
            print(f"{'Frame':<8} {'MVs':<10} {'Carriers':<10} {'Capacity (B)':<15}")
            print("-" * 70)
            for frame_stat in analysis["per_frame"][:20]:  # Show first 20
                print(
                    f"{frame_stat['frame_idx']:<8} "
                    f"{frame_stat['total_mvs']:<10} "
                    f"{frame_stat['suitable_carriers']:<10} "
                    f"{frame_stat['capacity_bytes']:<15}"
                )
            if len(analysis["per_frame"]) > 20:
                print(f"... ({len(analysis['per_frame']) - 20} more frames)")
        
        # Export to JSON
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(analysis, f, indent=2)
            print(f"\n💾 Analysis exported to: {output_path}")
        
        # Visualization
        if args.visualize:
            try:
                from zk_mv_stego.utils.visualizer import MVVisualizer
                print("\n🎨 Generating visualization...")
                visualizer = MVVisualizer()
                # Use first frame with MVs
                first_frame_idx = next(
                    (i for i, mvs in enumerate(mv_data.motion_vectors) if mvs),
                    0
                )
                visualizer.plot_mv_arrows(
                    mv_data,
                    frame_idx=first_frame_idx,
                    save_path=f"mv_analysis_frame{first_frame_idx}.png"
                )
                print(f"   Saved: mv_analysis_frame{first_frame_idx}.png")
            except ImportError:
                print("⚠️  Visualization skipped (matplotlib not installed)")
        
        print("\n" + "=" * 70)
        sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
