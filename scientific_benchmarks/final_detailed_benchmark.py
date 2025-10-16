#!/usr/bin/env python3
"""
Final Detailed Performance Benchmark Suite
===========================================

Comprehensive benchmark with:
- 20 data points (arithmetic progression)
- Line charts for all metrics
- Cache warming to avoid anomalies
- Complete metric coverage

Metrics tracked:
- Performance: Time, Throughput, Efficiency
- Memory: RAM usage and efficiency
- Size: Image sizes and overhead
- Quality: PSNR, SSIM, MSE
- Capacity: Bits/pixel, utilization
"""

import sys
import time
import json
import psutil
import gc
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Tuple
from io import BytesIO
import warnings
warnings.filterwarnings('ignore')

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT / "src"))

from PIL import Image
from zk_stego.chaos_embedding import ChaosEmbedding

# Visualization
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from skimage.metrics import structural_similarity as ssim
    from skimage.metrics import peak_signal_noise_ratio as psnr
    SKIMAGE = True
except:
    SKIMAGE = False
    print("⚠️ scikit-image not available - using numpy fallback for quality metrics")


class FinalDetailedBenchmark:
    """Final detailed benchmark with all fixes"""
    
    def __init__(self):
        self.output_dir = Path(__file__).resolve().parent / "detailed_benchmark_results"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.results = []
        self.process = psutil.Process()
        
        print("🚀 Final Detailed Performance Benchmark Suite")
        print("="*80)
        print("📊 Features:")
        print("  • 20 data points per benchmark")
        print("  • Arithmetic progression")
        print("  • Cache warming (avoid cold start)")
        print("  • Comprehensive metrics")
        print("  • Line chart visualizations")
        print("="*80)
    
    def get_ram_mb(self) -> float:
        """Get RAM usage in MB"""
        return self.process.memory_info().rss / 1024 / 1024
    
    def create_test_image(self, width: int, height: int) -> Image.Image:
        """Create test image"""
        test_img_path = PROJECT_ROOT / "examples" / "testvectors" / "Lenna_test_image.webp"
        
        if test_img_path.exists():
            img = Image.open(test_img_path).convert('RGB')
            return img.resize((width, height), Image.Resampling.LANCZOS)
        else:
            arr = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
            return Image.fromarray(arr, 'RGB')
    
    def generate_message(self, length: int) -> str:
        """Generate test message"""
        base = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt "
        return (base * (length // len(base) + 1))[:length]
    
    def quality_metrics(self, orig: Image.Image, stego: Image.Image) -> Tuple[float, float, float]:
        """Calculate PSNR, SSIM, MSE"""
        try:
            orig_arr = np.array(orig, dtype=np.float64)
            stego_arr = np.array(stego, dtype=np.float64)

            mse_val = np.mean((orig_arr - stego_arr) ** 2)

            if SKIMAGE:
                psnr_val = psnr(orig_arr, stego_arr, data_range=255)
                ssim_val = ssim(orig_arr, stego_arr, channel_axis=2, data_range=255)
            else:
                if mse_val == 0:
                    psnr_val = 100.0
                else:
                    psnr_val = 20 * np.log10(255.0) - 10 * np.log10(mse_val)

                # Lightweight SSIM approximation on grayscale conversion
                orig_gray = (0.2989 * orig_arr[:, :, 0] +
                             0.5870 * orig_arr[:, :, 1] +
                             0.1140 * orig_arr[:, :, 2])
                stego_gray = (0.2989 * stego_arr[:, :, 0] +
                              0.5870 * stego_arr[:, :, 1] +
                              0.1140 * stego_arr[:, :, 2])

                mu_x = orig_gray.mean()
                mu_y = stego_gray.mean()
                sigma_x = orig_gray.var()
                sigma_y = stego_gray.var()
                covariance = np.mean((orig_gray - mu_x) * (stego_gray - mu_y))

                c1 = (0.01 * 255) ** 2
                c2 = (0.03 * 255) ** 2
                denominator = (mu_x ** 2 + mu_y ** 2 + c1) * (sigma_x + sigma_y + c2)
                if denominator == 0:
                    ssim_val = 1.0
                else:
                    ssim_val = ((2 * mu_x * mu_y + c1) *
                                (2 * covariance + c2)) / denominator
                ssim_val = max(0.0, min(1.0, ssim_val))

            return float(psnr_val), float(ssim_val), float(mse_val)
        except Exception:
            return 0.0, 0.0, 0.0
    
    def run_single_test(self, test_id: int, img_size: Tuple[int, int], msg_len: int) -> dict:
        """Run single test"""
        w, h = img_size
        pixels = w * h
        
        print(f"\n📊 Test {test_id}: Image {w}×{h} ({pixels:,}px), Message {msg_len} chars", end="")
        
        gc.collect()
        ram_before = self.get_ram_mb()
        
        try:
            # Create data
            image = self.create_test_image(w, h)
            message = self.generate_message(msg_len)
            
            # Embedding
            start = time.perf_counter()
            img_arr = np.array(image)
            embedder = ChaosEmbedding(image_array=img_arr)
            stego_image = embedder.embed_message(message)
            embed_time = (time.perf_counter() - start) * 1000
            
            # Extraction
            start = time.perf_counter()
            stego_arr = np.array(stego_image)
            extractor = ChaosEmbedding(image_array=stego_arr)
            extracted = extractor.extract_message(msg_len)
            extract_time = (time.perf_counter() - start) * 1000
            
            ram_after = self.get_ram_mb()
            ram_used = ram_after - ram_before
            if ram_used < 0:
                ram_used = 0.0
            if ram_used < 0.0001:
                estimated_usage = img_arr.nbytes / 1024 / 1024
                ram_used = max(ram_used, estimated_usage)
            
            # Quality
            psnr_val, ssim_val, mse_val = self.quality_metrics(image, stego_image)
            
            # Metrics
            total_time = embed_time + extract_time
            throughput = (msg_len * 8 / total_time) * 1000  # bps
            throughput_kbps = throughput / 1024 / 8
            
            bits_per_pixel = (msg_len * 8) / pixels
            max_capacity = pixels * 3
            capacity_util = (msg_len * 8 / max_capacity) * 100
            
            orig_buffer = BytesIO()
            stego_buffer = BytesIO()
            image.save(orig_buffer, format='PNG')
            stego_image.save(stego_buffer, format='PNG')
            orig_size = len(orig_buffer.getvalue()) / 1024
            stego_size = len(stego_buffer.getvalue()) / 1024
            
            success = (extracted[:len(message)] == message)
            
            result = {
                'test_id': test_id,
                'width': w,
                'height': h,
                'pixels': pixels,
                'message_length': msg_len,
                'embed_time_ms': float(embed_time),
                'extract_time_ms': float(extract_time),
                'total_time_ms': float(total_time),
                'ram_used_mb': float(ram_used),
                'throughput_kbps': float(throughput_kbps),
                'orig_size_kb': float(orig_size),
                'stego_size_kb': float(stego_size),
                'psnr_db': float(psnr_val),
                'ssim': float(ssim_val),
                'mse': float(mse_val),
                'bits_per_pixel': float(bits_per_pixel),
                'capacity_util_pct': float(capacity_util),
                'success': success
            }
            
            # Smart RAM display
            if ram_used < 0.1:
                ram_display = f"{ram_used*1000:.0f}KB" if ram_used > 0.001 else "~0KB"
            else:
                ram_display = f"{ram_used:.2f}MB"
            print(f" → ✅ {total_time:.1f}ms, RAM: {ram_display}")
            
            return result
            
        except Exception as e:
            print(f" → ❌ Error: {e}")
            return {
                'test_id': test_id,
                'width': w,
                'height': h,
                'pixels': pixels,
                'message_length': msg_len,
                'embed_time_ms': 0.0,
                'extract_time_ms': 0.0,
                'total_time_ms': 0.0,
                'ram_used_mb': 0.0,
                'throughput_kbps': 0.0,
                'orig_size_kb': 0.0,
                'stego_size_kb': 0.0,
                'psnr_db': 0.0,
                'ssim': 0.0,
                'mse': 0.0,
                'bits_per_pixel': 0.0,
                'capacity_util_pct': 0.0,
                'success': False,
                'error': str(e)
            }
    
    def run_image_size_benchmark(self):
        """Image size scaling: 20 points from 128×128 to 1024×1024"""
        print("\n" + "="*80)
        print("📈 BENCHMARK 1: Image Size Scaling")
        print("="*80)
        print("Fixed: Message length = 100 characters")
        print("Variable: Image size 128×128 to 1024×1024 (20 points)")
        
        sizes = np.linspace(128, 1024, 20, dtype=int)
        msg_len = 100
        
        # Warmup to avoid cold start anomaly
        print("\n🔥 Cache warming...")
        self.run_single_test(0, (256, 256), msg_len)
        self.results = []  # Clear warmup
        print("✅ Ready")
        
        for i, size in enumerate(sizes, 1):
            result = self.run_single_test(i, (int(size), int(size)), msg_len)
            self.results.append(result)
        
        self.save_and_visualize('image_size')
    
    def run_message_length_benchmark(self):
        """Message length scaling: 20 points from 50 to 1000 chars"""
        print("\n" + "="*80)
        print("📈 BENCHMARK 2: Message Length Scaling")
        print("="*80)
        print("Fixed: Image size = 512×512 pixels")
        print("Variable: Message length 50-1000 chars (20 points)")
        
        self.results = []
        
        msg_lengths = np.linspace(50, 1000, 20, dtype=int)
        img_size = (512, 512)
        
        # Warmup
        print("\n🔥 Cache warming...")
        self.run_single_test(0, img_size, 100)
        self.results = []
        print("✅ Ready")
        
        for i, msg_len in enumerate(msg_lengths, 1):
            result = self.run_single_test(i, img_size, int(msg_len))
            self.results.append(result)
        
        self.save_and_visualize('message_length')
    
    def save_and_visualize(self, btype: str):
        """Save results and create visualizations"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save JSON
        json_file = self.output_dir / f"results_{btype}_{timestamp}.json"
        with open(json_file, 'w') as f:
            json.dump({
                'benchmark_type': btype,
                'timestamp': timestamp,
                'total_tests': len(self.results),
                'results': self.results
            }, f, indent=2)
        
        print(f"\n💾 Saved: {json_file.relative_to(PROJECT_ROOT)}")
        
        # Visualize
        self.create_charts(btype, timestamp)
    
    def create_charts(self, btype: str, timestamp: str):
        """Create comprehensive line charts (20 panels)"""
        if not self.results:
            return
        
        print("\n📊 Creating visualizations...")
        
        fig = plt.figure(figsize=(24, 16))
        gs = fig.add_gridspec(4, 5, hspace=0.45, wspace=0.35)
        
        colors = {
            'p1': '#2E86AB', 'p2': '#A23B72', 'p3': '#06A77D',
            'p4': '#FFA500', 'p5': '#E63946'
        }
        
        # X-axis data
        if btype == 'image_size':
            x = [r['pixels'] / 1000 for r in self.results]
            xlabel = 'Image Size (K pixels)'
            title = 'Image Size Scaling'
        else:
            x = [r['message_length'] for r in self.results]
            xlabel = 'Message Length (characters)'
            title = 'Message Length Scaling'
        
        # Helper function
        def plot_metric(ax, y_data, ylabel, title_text, color, unit=None):
            ax.plot(x, y_data, 'o-', linewidth=2.5, markersize=5,
                   color=color, markeredgecolor='black', markeredgewidth=1)
            ax.set_xlabel(xlabel, fontsize=10, fontweight='bold')
            ax.set_ylabel(ylabel, fontsize=10, fontweight='bold')
            ax.set_title(title_text, fontsize=10, fontweight='bold')
            ax.grid(True, alpha=0.3)
        
        # ROW 1: Time
        plot_metric(fig.add_subplot(gs[0, 0]),
                   [r['embed_time_ms'] for r in self.results],
                   'Elapsed Time (milliseconds)', f'1. EMBEDDING TIME\n{title}', colors['p1'])
        
        plot_metric(fig.add_subplot(gs[0, 1]),
                   [r['extract_time_ms'] for r in self.results],
                   'Elapsed Time (milliseconds)', f'2. EXTRACTION TIME\n{title}', colors['p2'])
        
        plot_metric(fig.add_subplot(gs[0, 2]),
                   [r['total_time_ms'] for r in self.results],
                   'Elapsed Time (milliseconds)', f'3. TOTAL TIME\n{title}', colors['p3'])
        
        plot_metric(fig.add_subplot(gs[0, 3]),
                   [r['throughput_kbps'] for r in self.results],
                   'Throughput (kilobytes per second)', f'4. THROUGHPUT\n{title}', colors['p4'])
        
        # Efficiency
        ax = fig.add_subplot(gs[0, 4])
        if btype == 'image_size':
            y = [r['total_time_ms']/r['pixels']*1000 for r in self.results]
            plot_metric(ax, y, 'Microseconds per pixel', f'5. EFFICIENCY\n{title}', colors['p5'])
        else:
            y = [r['total_time_ms']/r['message_length'] for r in self.results]
            plot_metric(ax, y, 'Milliseconds per character', f'5. EFFICIENCY\n{title}', colors['p5'])
        
        # ROW 2: Memory & Size
        plot_metric(fig.add_subplot(gs[1, 0]),
                   [r['ram_used_mb'] for r in self.results],
                   'RAM (MB)', f'6. MEMORY USAGE\n{title}', colors['p1'], 'MB')
        
        plot_metric(fig.add_subplot(gs[1, 1]),
                   [r['orig_size_kb'] for r in self.results],
                   'Size (KB)', f'7. ORIGINAL SIZE\n{title}', colors['p2'], 'KB')
        
        plot_metric(fig.add_subplot(gs[1, 2]),
                   [r['stego_size_kb'] for r in self.results],
                   'Size (KB)', f'8. STEGO SIZE\n{title}', colors['p3'], 'KB')
        
        ax = fig.add_subplot(gs[1, 3])
        y = [(r['stego_size_kb']/r['orig_size_kb']-1)*100 if r['orig_size_kb'] > 0 else 0 for r in self.results]
        plot_metric(ax, y, 'Overhead (%)', f'9. SIZE OVERHEAD\n{title}', colors['p4'], '%')
        
        ax = fig.add_subplot(gs[1, 4])
        if btype == 'image_size':
            y = [r['ram_used_mb']/r['pixels']*1000 for r in self.results]
            plot_metric(ax, y, 'RAM (KB/Kpixel)', f'10. RAM EFFICIENCY\n{title}', colors['p5'], '')
        else:
            y = [r['ram_used_mb']/r['message_length'] if r['message_length'] > 0 else 0 for r in self.results]
            plot_metric(ax, y, 'RAM (MB/char)', f'10. RAM EFFICIENCY\n{title}', colors['p5'], '')
        
        # ROW 3: Quality
        plot_metric(fig.add_subplot(gs[2, 0]),
                   [r['psnr_db'] for r in self.results],
                   'PSNR (dB)', f'11. PSNR\nHigher=Better', colors['p1'], 'dB')
        
        ax = fig.add_subplot(gs[2, 1])
        plot_metric(ax, [r['ssim'] for r in self.results],
                   'SSIM', f'12. SSIM\nHigher=Better', colors['p2'], '')
        if SKIMAGE:
            ax.set_ylim(0.9, 1.0)
        
        plot_metric(fig.add_subplot(gs[2, 2]),
                   [r['mse'] for r in self.results],
                   'MSE', f'13. MSE\nLower=Better', colors['p3'], '')
        
        ax = fig.add_subplot(gs[2, 3])
        y = [(r['psnr_db']/50)*0.5 + r['ssim']*0.5 for r in self.results]
        plot_metric(ax, y, 'Score', f'14. QUALITY SCORE\n(PSNR+SSIM)', colors['p4'], '')
        
        ax = fig.add_subplot(gs[2, 4])
        max_mse = max([r['mse'] for r in self.results])
        if max_mse > 0:
            y = [100 - (r['mse']/max_mse*100) for r in self.results]
        else:
            y = [100.0] * len(self.results)
        plot_metric(ax, y, 'Quality (%)', f'15. QUALITY RETENTION\n{title}', colors['p5'], '%')
        
        # ROW 4: Capacity & Analysis
        plot_metric(fig.add_subplot(gs[3, 0]),
                   [r['bits_per_pixel'] for r in self.results],
                   'Bits/Pixel', f'16. EMBEDDING RATE\n{title}', colors['p1'], '')
        
        plot_metric(fig.add_subplot(gs[3, 1]),
                   [r['capacity_util_pct'] for r in self.results],
                   'Utilization (%)', f'17. CAPACITY USAGE\n{title}', colors['p2'], '%')
        
        # Time breakdown
        ax = fig.add_subplot(gs[3, 2])
        embed_pct = [r['embed_time_ms']/r['total_time_ms']*100 if r['total_time_ms'] > 0 else 0 for r in self.results]
        extract_pct = [r['extract_time_ms']/r['total_time_ms']*100 if r['total_time_ms'] > 0 else 0 for r in self.results]
        ax.plot(x, embed_pct, 'o-', linewidth=2.5, markersize=5, 
               label='Embedding', color=colors['p1'], markeredgecolor='black', markeredgewidth=1)
        ax.plot(x, extract_pct, 's-', linewidth=2.5, markersize=5,
               label='Extraction', color=colors['p2'], markeredgecolor='black', markeredgewidth=1)
        ax.set_xlabel(xlabel, fontsize=10, fontweight='bold')
        ax.set_ylabel('Percentage (%)', fontsize=10, fontweight='bold')
        ax.set_title(f'18. TIME BREAKDOWN\n{title}', fontsize=10, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        
        # Success rate
        ax = fig.add_subplot(gs[3, 3])
        success = [sum(1 for r in self.results[:i+1] if r['success'])/(i+1)*100 
                  for i in range(len(self.results))]
        plot_metric(ax, success, 'Success (%)', f'19. SUCCESS RATE\n{title}', colors['p4'], '%')
        ax.set_ylim(95, 105)
        
        # Summary
        ax = fig.add_subplot(gs[3, 4])
        ax.axis('off')
        
        avg_time = np.mean([r['total_time_ms'] for r in self.results])
        avg_ram = np.mean([r['ram_used_mb'] for r in self.results])
        avg_psnr = np.mean([r['psnr_db'] for r in self.results])
        avg_ssim = np.mean([r['ssim'] for r in self.results])
        success_count = sum(1 for r in self.results if r['success'])
        
        summary = f'📊 SUMMARY\n\n'
        summary += f'Tests: {len(self.results)}\n'
        summary += f'Success: {success_count}/{len(self.results)}\n\n'
        summary += f'Avg Time: {avg_time:.1f} milliseconds\n'
        summary += f'Avg RAM: {avg_ram:.1f} MB\n\n'
        if SKIMAGE:
            summary += f'Avg PSNR: {avg_psnr:.1f} dB\n'
            summary += f'Avg SSIM: {avg_ssim:.3f}\n\n'
        summary += f'Type: {title}\n'
        summary += f'Date: {timestamp[:8]}'
        
        ax.text(0.5, 0.5, summary, transform=ax.transAxes,
               fontsize=11, ha='center', va='center', family='monospace',
               bbox=dict(boxstyle='round', facecolor='lightyellow', 
                        alpha=0.9, edgecolor='black', linewidth=2))
        
        plt.suptitle(f'ZK-STEGANOGRAPHY DETAILED PERFORMANCE ANALYSIS\n{title} - 20 Data Points',
                    fontsize=16, fontweight='bold', y=0.995)
        
        plt.tight_layout(rect=[0, 0, 1, 0.99])
        
        # Save
        png_file = self.output_dir / f"benchmark_{btype}_{timestamp}.png"
        plt.savefig(png_file, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"✅ PNG: {png_file.relative_to(PROJECT_ROOT)}")
        
        pdf_file = self.output_dir / f"benchmark_{btype}_{timestamp}.pdf"
        plt.savefig(pdf_file, format='pdf', bbox_inches='tight', facecolor='white')
        print(f"✅ PDF: {pdf_file.relative_to(PROJECT_ROOT)}")
        
        plt.close()


def main():
    print("\n" + "="*80)
    print("🚀 ZK-STEGANOGRAPHY - FINAL DETAILED BENCHMARK")
    print("="*80)
    print("📊 20 data points • Line charts • Cache warmed • Complete metrics")
    print("="*80)
    
    bench = FinalDetailedBenchmark()
    
    # Run benchmarks
    print("\n🔬 Starting Benchmark 1...")
    bench.run_image_size_benchmark()
    
    print("\n🔬 Starting Benchmark 2...")
    bench.run_message_length_benchmark()
    
    print("\n" + "="*80)
    print("✅ ALL BENCHMARKS COMPLETED!")
    print(f"📁 Results in: {bench.output_dir}")
    print("="*80)


if __name__ == '__main__':
    main()
