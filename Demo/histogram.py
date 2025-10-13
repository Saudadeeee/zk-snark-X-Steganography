#!/usr/bin/env python3
"""
ZK-SNARK Steganography - Histogram Analysis Tool
Tạo biểu đồ histogram để phân tích sự thay đổi của ảnh trước và sau embedding
"""

import os
import sys
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from datetime import datetime
from typing import Tuple, Optional

# Add parent directory to path to import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.zk_stego.chaos_embedding import ChaosEmbedding
from src.zk_stego.metadata_message_generator import MetadataMessageGenerator

class HistogramAnalyzer:
    """Phân tích histogram cho steganography"""
    
    def __init__(self):
        self.demo_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.demo_dir)
        self.test_images_dir = os.path.join(self.project_root, "examples", "testvectors")
        self.output_dir = os.path.join(self.demo_dir, "output")
        self.doc_dir = os.path.join(self.demo_dir, "doc")
        
        # Create directories
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.doc_dir, exist_ok=True)
    
    def rgb_histogram(self, img_path: str) -> Tuple[np.ndarray, np.ndarray]:
        """Calculate RGB histogram for image"""
        img = Image.open(img_path).convert('RGB')
        arr = np.asarray(img)  # H×W×3, uint8
        
        hists = []
        bins = np.arange(257)  # 0-256 for histogram bins
        
        for c in range(3):  # 0=R,1=G,2=B
            hist, _ = np.histogram(arr[..., c], bins=bins, density=True)
            hists.append(hist)
        
        return np.stack(hists), bins[:-1]  # Return 3×256 and bin centers
    
    def create_stego_image(self, cover_path: str, message: str, secret_key: str) -> str:
        """Tạo stego image và return path"""
        print(f"📷 Creating stego image from: {os.path.basename(cover_path)}")
        
        # Load cover image
        image = Image.open(cover_path)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image_array = np.array(image)
        
        # Embed message
        chaos_embedder = ChaosEmbedding(image_array)
        stego_image = chaos_embedder.embed_message(message, secret_key)
        
        # Save as PNG (lossless)
        stego_filename = f"stego_histogram_{os.path.splitext(os.path.basename(cover_path))[0]}.png"
        stego_path = os.path.join(self.output_dir, stego_filename)
        stego_image.save(stego_path, 'PNG')
        
        print(f"💾 Stego image saved: {stego_filename}")
        return stego_path
    
    def plot_histogram_comparison(self, cover_path: str, stego_path: str, 
                                message_info: dict, save_path: Optional[str] = None):
        """Plot histogram comparison between cover and stego images"""
        
        print(f"📊 Generating histogram comparison...")
        
        # Calculate histograms
        cover_hist, bins = self.rgb_histogram(cover_path)
        stego_hist, _ = self.rgb_histogram(stego_path)
        
        # Create single row comparison plot (centered)
        fig, axes = plt.subplots(1, 3, figsize=(15, 6))
        channel_names = ['Red Channel', 'Green Channel', 'Blue Channel']
        colors = ['red', 'green', 'blue']
        
        # Plot individual channel histograms (single row)
        for i in range(3):
            ax = axes[i]
            ax.plot(bins, cover_hist[i], label='Cover Image', 
                   linewidth=2.5, color=colors[i], alpha=0.8)
            ax.plot(bins, stego_hist[i], label='Stego Image', 
                   linestyle='--', linewidth=2.5, color='black', alpha=0.9)
            ax.set_title(f'{channel_names[i]} - Cover vs Stego')
            ax.set_xlabel('Pixel Intensity (0-255)')
            ax.set_ylabel('Probability Density')
            ax.grid(alpha=0.3)
            ax.legend()
            
            # Add correlation info
            # correlation = np.corrcoef(cover_hist[i], stego_hist[i])[0,1]
            # ax.text(0.02, 0.98, f'Correlation: {correlation:.6f}', 
            #        transform=ax.transAxes, fontsize=10,
            #        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8),
            #        verticalalignment='top')
        
        # Add title with message information
        title = f'RGB Histogram Analysis - ZK-SNARK Steganography'
        subtitle = f'Message: {message_info["length"]} chars, Channel: Red (LSB), Method: Chaos-based'
        fig.suptitle(f'{title}\n{subtitle}', fontsize=14, y=0.98)
        
        plt.tight_layout()
        plt.subplots_adjust(top=0.85)
        
        # Save plot
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"📈 Histogram chart saved: {os.path.basename(save_path)}")
        
        return fig
    
    def calculate_histogram_statistics(self, cover_path: str, stego_path: str) -> dict:
        """Tính toán thống kê histogram"""
        
        cover_hist, bins = self.rgb_histogram(cover_path)
        stego_hist, _ = self.rgb_histogram(stego_path)
        
        stats = {
            'channels': [],
            'overall': {}
        }
        
        channel_names = ['Red', 'Green', 'Blue']
        
        for i in range(3):
            # Calculate differences
            hist_diff = stego_hist[i] - cover_hist[i]
            
            channel_stats = {
                'channel': channel_names[i],
                'max_difference': np.max(np.abs(hist_diff)),
                'mean_absolute_difference': np.mean(np.abs(hist_diff)),
                'total_variation': np.sum(np.abs(hist_diff)),
                'correlation': np.corrcoef(cover_hist[i], stego_hist[i])[0,1]
            }
            
            stats['channels'].append(channel_stats)
        
        # Overall statistics
        all_diffs = []
        for i in range(3):
            hist_diff = stego_hist[i] - cover_hist[i]
            all_diffs.extend(hist_diff)
        
        stats['overall'] = {
            'max_change': max(abs(d) for d in all_diffs),
            'mean_change': np.mean([abs(d) for d in all_diffs]),
            'detectability_score': max(abs(d) for d in all_diffs)  # Higher = more detectable
        }
        
        return stats
    
    def generate_comprehensive_analysis(self, cover_path: str, message: str, secret_key: str):
        """Tạo phân tích tổng hợp với histogram"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        print(f"\n🔍 COMPREHENSIVE HISTOGRAM ANALYSIS")
        print(f"{'='*60}")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Create stego image
        stego_path = self.create_stego_image(cover_path, message, secret_key)
        
        # Message info
        message_info = {
            'content': message,
            'length': len(message),
            'bytes': len(message.encode('utf-8')),
            'bits': len(message) * 8
        }
        
        print(f"📝 Message Info:")
        print(f"   Length: {message_info['length']} characters")
        print(f"   Bits: {message_info['bits']} bits")
        print()
        
        # Calculate statistics
        stats = self.calculate_histogram_statistics(cover_path, stego_path)
        
        print(f"📊 Histogram Statistics:")
        for channel_stat in stats['channels']:
            print(f"   {channel_stat['channel']} Channel:")
            print(f"     Max difference: {channel_stat['max_difference']:.6f}")
            print(f"     Mean difference: {channel_stat['mean_absolute_difference']:.6f}")
            print(f"     Correlation: {channel_stat['correlation']:.6f}")
        print()
        
        print(f"🔒 Detectability Analysis:")
        print(f"   Overall max change: {stats['overall']['max_change']:.6f}")
        print(f"   Detectability score: {stats['overall']['detectability_score']:.6f}")
        
        detectability = "Very Low" if stats['overall']['detectability_score'] < 0.001 else \
                       "Low" if stats['overall']['detectability_score'] < 0.01 else \
                       "Medium" if stats['overall']['detectability_score'] < 0.1 else "High"
        print(f"   Detectability level: {detectability}")
        print()
        
        # Generate histogram plots
        chart_path = os.path.join(self.doc_dir, f"histogram_analysis_{timestamp}.png")
        fig = self.plot_histogram_comparison(cover_path, stego_path, message_info, chart_path)
        
        # Save statistics report
        stats_report = {
            'analysis_timestamp': timestamp,
            'cover_image': os.path.basename(cover_path),
            'stego_image': os.path.basename(stego_path),
            'message_info': message_info,
            'histogram_statistics': stats,
            'files_generated': {
                'stego_image': os.path.basename(stego_path),
                'histogram_chart': os.path.basename(chart_path)
            }
        }
        
        stats_file = os.path.join(self.doc_dir, f"histogram_stats_{timestamp}.json")
        import json
        with open(stats_file, 'w') as f:
            json.dump(stats_report, f, indent=2)
        
        print(f"📄 Statistics report saved: {os.path.basename(stats_file)}")
        
        return {
            'stego_path': stego_path,
            'chart_path': chart_path,
            'stats_file': stats_file,
            'statistics': stats
        }

def main():
    """Main function để chạy histogram analysis"""
    
    print("🎯 ZK-SNARK STEGANOGRAPHY - HISTOGRAM ANALYSIS")
    print("=" * 60)
    
    analyzer = HistogramAnalyzer()
    
    # Check for test images
    if not os.path.exists(analyzer.test_images_dir):
        print("❌ Test images directory not found!")
        return False
    
    # Find test images
    test_images = [f for f in os.listdir(analyzer.test_images_dir) 
                   if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    
    if not test_images:
        print("❌ No test images found!")
        return False
    
    print(f"📷 Found {len(test_images)} test images")
    
    # Generate test message
    msg_generator = MetadataMessageGenerator()
    test_message = msg_generator.generate_processing_history_message(
        "Histogram analysis test - ZK-Stego steganography with chaos embedding"
    )
    
    # Process each image
    for image_file in test_images:
        print(f"\n🖼️  Processing: {image_file}")
        print("-" * 40)
        
        cover_path = os.path.join(analyzer.test_images_dir, image_file)
        
        try:
            # Generate comprehensive analysis
            results = analyzer.generate_comprehensive_analysis(
                cover_path=cover_path,
                message=test_message,
                secret_key="histogram_analysis_key"
            )
            
            print(f"✅ Analysis completed for {image_file}")
            
        except Exception as e:
            print(f"❌ Error processing {image_file}: {str(e)}")
            continue
    
    print(f"\n🎯 HISTOGRAM ANALYSIS COMPLETED!")
    print(f"📁 Results saved in: {analyzer.doc_dir}")
    print(f"🖼️  Stego images in: {analyzer.output_dir}")
    
    # Show generated files
    print(f"\n📊 Generated files:")
    try:
        for file in os.listdir(analyzer.doc_dir):
            if 'histogram' in file:
                print(f"  - doc/{file}")
        
        for file in os.listdir(analyzer.output_dir):
            if 'stego_histogram' in file:
                print(f"  - output/{file}")
    except:
        pass
    
    return True

def create_custom_histogram(cover_image_path: str, stego_image_path: str, 
                          output_path: Optional[str] = None):
    """Tạo histogram cho 2 ảnh bất kỳ"""
    
    print(f"📊 Creating custom histogram comparison")
    print(f"Cover: {os.path.basename(cover_image_path)}")
    print(f"Stego: {os.path.basename(stego_image_path)}")
    
    analyzer = HistogramAnalyzer()
    
    # Calculate histograms
    cover_hist, bins = analyzer.rgb_histogram(cover_image_path)
    stego_hist, _ = analyzer.rgb_histogram(stego_image_path)
    
    # Create single row plot (centered)
    fig, axes = plt.subplots(1, 3, figsize=(15, 6))
    channel_names = ['Red Channel', 'Green Channel', 'Blue Channel']
    colors = ['red', 'green', 'blue']
    
    for i in range(3):
        ax = axes[i]
        ax.plot(bins, cover_hist[i], label='Cover Image', 
               linewidth=2.5, color=colors[i], alpha=0.8)
        ax.plot(bins, stego_hist[i], label='Stego Image', 
               linestyle='--', linewidth=2.5, color='black', alpha=0.9)
        ax.set_title(f'{channel_names[i]} - Cover vs Stego')
        ax.set_xlabel('Pixel Intensity (0-255)')
        ax.set_ylabel('Probability Density')
        ax.grid(alpha=0.3)
        ax.legend()
        
        # Add correlation info
        correlation = np.corrcoef(cover_hist[i], stego_hist[i])[0,1]
        ax.text(0.02, 0.98, f'Correlation: {correlation:.6f}', 
               transform=ax.transAxes, fontsize=10,
               bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8),
               verticalalignment='top')
    
    # Title
    fig.suptitle('RGB Histogram Analysis - ZK-SNARK Steganography\nChaos-based LSB Embedding with High Invisibility', 
                 fontsize=14, y=0.98)
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.85)
    
    # Save or show
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"📈 Histogram saved: {os.path.basename(output_path)}")
    else:
        plt.show()
    
    return fig

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='ZK-SNARK Steganography Histogram Analysis')
    parser.add_argument('--cover', help='Path to cover image')
    parser.add_argument('--stego', help='Path to stego image') 
    parser.add_argument('--output', help='Output path for histogram chart')
    parser.add_argument('--auto', action='store_true', help='Run automatic analysis on test images')
    
    args = parser.parse_args()
    
    try:
        if args.cover and args.stego:
            # Custom histogram for specific images
            create_custom_histogram(args.cover, args.stego, args.output)
        elif args.auto or (not args.cover and not args.stego):
            # Auto analysis
            success = main()
            sys.exit(0 if success else 1)
        else:
            print("❌ Please provide both --cover and --stego, or use --auto")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Analysis interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
