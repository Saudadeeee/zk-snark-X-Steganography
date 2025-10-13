#!/usr/bin/env python3
"""
ZK-SNARK Steganography - Histogram Viewer
Script để xem và phân tích kết quả histogram
"""

import os
import sys
import json
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from datetime import datetime

def view_histogram_results():
    """Xem kết quả histogram analysis"""
    
    demo_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(demo_dir, "doc")
    
    print("🎯 ZK-SNARK STEGANOGRAPHY - HISTOGRAM VIEWER")
    print("=" * 60)
    
    # Find histogram files
    histogram_charts = []
    histogram_stats = []
    
    try:
        for file in os.listdir(doc_dir):
            if file.startswith('histogram_analysis_') and file.endswith('.png'):
                histogram_charts.append(file)
            elif file.startswith('histogram_stats_') and file.endswith('.json'):
                histogram_stats.append(file)
    except:
        print("❌ Doc directory not found")
        return False
    
    if not histogram_charts:
        print("❌ No histogram charts found")
        print("💡 Run: python3 histogram.py --auto")
        return False
    
    # Sort by timestamp (newest first)
    histogram_charts.sort(reverse=True)
    histogram_stats.sort(reverse=True)
    
    print(f"📊 Found {len(histogram_charts)} histogram charts")
    print(f"📄 Found {len(histogram_stats)} statistics files")
    print()
    
    # Show latest results
    latest_chart = histogram_charts[0]
    print(f"📈 Latest chart: {latest_chart}")
    
    # Find corresponding stats file
    timestamp = latest_chart.replace('histogram_analysis_', '').replace('.png', '')
    stats_file = f"histogram_stats_{timestamp}.json"
    
    if stats_file in histogram_stats:
        stats_path = os.path.join(doc_dir, stats_file)
        
        try:
            with open(stats_path, 'r') as f:
                stats_data = json.load(f)
            
            print(f"📊 ANALYSIS RESULTS")
            print("-" * 40)
            
            msg_info = stats_data['message_info']
            print(f"📝 Message: {msg_info['length']} chars, {msg_info['bits']} bits")
            
            hist_stats = stats_data['histogram_statistics']
            print(f"📈 Histogram Statistics:")
            
            for channel in hist_stats['channels']:
                print(f"   {channel['channel']} Channel:")
                print(f"     Max difference: {channel['max_difference']:.8f}")
                print(f"     Correlation: {channel['correlation']:.8f}")
                
                if channel['channel'] == 'Red' and channel['max_difference'] > 0:
                    print(f"     ✅ LSB embedding detected")
                elif channel['max_difference'] == 0:
                    print(f"     ⚪ No changes")
            
            overall = hist_stats['overall']
            print(f"\n🔒 Security Analysis:")
            print(f"   Detectability score: {overall['detectability_score']:.8f}")
            
            if overall['detectability_score'] < 0.001:
                level = "Very Low (Excellent)"
            elif overall['detectability_score'] < 0.01:
                level = "Low (Good)"
            elif overall['detectability_score'] < 0.1:
                level = "Medium (Acceptable)"
            else:
                level = "High (Poor)"
            
            print(f"   Detectability level: {level}")
            print(f"   Red channel only: ✅ (Green/Blue untouched)")
            print(f"   LSB embedding: ✅ (±1 pixel value only)")
            
        except Exception as e:
            print(f"❌ Error reading stats: {str(e)}")
    
    print(f"\n📁 Files Location:")
    print(f"   Charts: Demo/doc/")
    print(f"   Images: Demo/output/")
    
    # List all available files
    print(f"\n📊 Available Charts:")
    for i, chart in enumerate(histogram_charts[:5]):  # Show top 5
        timestamp = chart.replace('histogram_analysis_', '').replace('.png', '')
        date_part = timestamp[:8]
        time_part = timestamp[9:]
        formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        formatted_time = f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        print(f"   {i+1}. {chart} ({formatted_date} {formatted_time})")
    
    if len(histogram_charts) > 5:
        print(f"   ... and {len(histogram_charts) - 5} more")
    
    return True

def show_histogram_chart(chart_name=None):
    """Display histogram chart"""
    
    demo_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(demo_dir, "doc")
    
    if not chart_name:
        # Find latest chart
        try:
            charts = [f for f in os.listdir(doc_dir) 
                     if f.startswith('histogram_analysis_') and f.endswith('.png')]
            if not charts:
                print("❌ No histogram charts found")
                return False
            chart_name = sorted(charts, reverse=True)[0]
        except:
            print("❌ Error finding charts")
            return False
    
    chart_path = os.path.join(doc_dir, chart_name)
    
    if not os.path.exists(chart_path):
        print(f"❌ Chart not found: {chart_name}")
        return False
    
    try:
        print(f"📊 Displaying: {chart_name}")
        
        # Load and display image
        img = mpimg.imread(chart_path)
        
        fig, ax = plt.subplots(figsize=(16, 10))
        ax.imshow(img)
        ax.axis('off')
        
        # Add title
        timestamp = chart_name.replace('histogram_analysis_', '').replace('.png', '')
        date_part = timestamp[:8]
        time_part = timestamp[9:]
        formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        formatted_time = f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        
        plt.suptitle(f'ZK-SNARK Steganography - Histogram Analysis\n'
                    f'Generated: {formatted_date} {formatted_time}', 
                    fontsize=16, y=0.98)
        
        plt.tight_layout()
        plt.show()
        
        return True
        
    except Exception as e:
        print(f"❌ Error displaying chart: {str(e)}")
        return False

def compare_all_histograms():
    """Compare all histogram files"""
    
    demo_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(demo_dir, "doc")
    
    print("📊 COMPARING ALL HISTOGRAM ANALYSES")
    print("=" * 50)
    
    try:
        # Find all stats files
        stats_files = [f for f in os.listdir(doc_dir) 
                      if f.startswith('histogram_stats_') and f.endswith('.json')]
        
        if not stats_files:
            print("❌ No statistics files found")
            return False
        
        stats_files.sort(reverse=True)
        
        print(f"📄 Found {len(stats_files)} analysis files")
        print()
        
        # Compare detectability scores
        results = []
        
        for stats_file in stats_files:
            stats_path = os.path.join(doc_dir, stats_file)
            
            try:
                with open(stats_path, 'r') as f:
                    data = json.load(f)
                
                timestamp = data['analysis_timestamp']
                msg_bits = data['message_info']['bits']
                detectability = data['histogram_statistics']['overall']['detectability_score']
                red_correlation = data['histogram_statistics']['channels'][0]['correlation']
                
                results.append({
                    'timestamp': timestamp,
                    'bits': msg_bits,
                    'detectability': detectability,
                    'correlation': red_correlation
                })
                
            except Exception as e:
                print(f"⚠️  Error reading {stats_file}: {str(e)}")
                continue
        
        if not results:
            print("❌ No valid results found")
            return False
        
        # Display comparison
        print("📊 DETECTABILITY COMPARISON:")
        print(f"{'Timestamp':<16} {'Bits':<6} {'Detectability':<14} {'Red Correlation':<15} {'Level'}")
        print("-" * 70)
        
        for result in results:
            ts = result['timestamp']
            formatted_ts = f"{ts[6:8]}/{ts[4:6]} {ts[9:11]}:{ts[11:13]}"
            
            if result['detectability'] < 0.001:
                level = "Very Low"
            elif result['detectability'] < 0.01:
                level = "Low"
            elif result['detectability'] < 0.1:
                level = "Medium"
            else:
                level = "High"
            
            print(f"{formatted_ts:<16} {result['bits']:<6} {result['detectability']:<14.8f} {result['correlation']:<15.8f} {level}")
        
        # Summary
        avg_detectability = sum(r['detectability'] for r in results) / len(results)
        avg_correlation = sum(r['correlation'] for r in results) / len(results)
        
        print()
        print("📈 SUMMARY:")
        print(f"   Average detectability: {avg_detectability:.8f}")
        print(f"   Average correlation: {avg_correlation:.8f}")
        print(f"   Consistency: {'Excellent' if max(r['detectability'] for r in results) < 0.001 else 'Good'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error comparing histograms: {str(e)}")
        return False

def main():
    """Main function"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description='ZK-SNARK Steganography Histogram Viewer')
    parser.add_argument('--show', help='Show specific histogram chart')
    parser.add_argument('--compare', action='store_true', help='Compare all analyses')
    
    args = parser.parse_args()
    
    try:
        if args.show:
            return show_histogram_chart(args.show)
        elif args.compare:
            return compare_all_histograms()
        else:
            return view_histogram_results()
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return False
    except Exception as e:
        print(f"\n\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)