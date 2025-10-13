#!/usr/bin/env python3
"""
ZK-SNARK Steganography - Test Histogram Analysis
Script test nhanh để kiểm tra histogram analyzer
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.zk_stego.metadata_message_generator import MetadataMessageGenerator
from histogram import HistogramAnalyzer, create_custom_histogram

def test_histogram_analysis():
    """Test histogram analysis với một ảnh mẫu"""
    
    print("🎯 TESTING HISTOGRAM ANALYSIS")
    print("=" * 50)
    
    # Initialize
    analyzer = HistogramAnalyzer()
    
    # Find test image
    test_image_path = None
    for ext in ['.webp', '.png', '.jpg', '.jpeg']:
        potential_path = os.path.join(analyzer.test_images_dir, f"Lenna_test_image{ext}")
        if os.path.exists(potential_path):
            test_image_path = potential_path
            break
    
    if not test_image_path:
        print("❌ No Lenna test image found!")
        return False
    
    print(f"📷 Using test image: {os.path.basename(test_image_path)}")
    
    # Generate test message
    msg_generator = MetadataMessageGenerator()
    test_message = msg_generator.generate_processing_history_message(
        "Quick histogram test - ZK-Stego analysis demo"
    )
    
    print(f"📝 Test message: {len(test_message)} characters")
    
    try:
        # Run analysis
        print("\n🔍 Running histogram analysis...")
        results = analyzer.generate_comprehensive_analysis(
            cover_path=test_image_path,
            message=test_message,
            secret_key="test_histogram_key"
        )
        
        print("\n✅ HISTOGRAM ANALYSIS COMPLETED!")
        print(f"📊 Chart saved: {os.path.basename(results['chart_path'])}")
        print(f"📄 Stats saved: {os.path.basename(results['stats_file'])}")
        print(f"🖼️  Stego image: {os.path.basename(results['stego_path'])}")
        
        # Print key statistics
        stats = results['statistics']
        print(f"\n📈 Key Results:")
        for channel_stat in stats['channels']:
            if channel_stat['channel'] == 'Red':  # Red channel có changes
                print(f"   Red Channel (LSB embedding):")
                print(f"     Max difference: {channel_stat['max_difference']:.6f}")
                print(f"     Correlation: {channel_stat['correlation']:.6f}")
        
        print(f"   Detectability: {stats['overall']['detectability_score']:.6f}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def quick_comparison():
    """So sánh nhanh 2 ảnh có sẵn"""
    
    print("\n🔄 QUICK COMPARISON TEST")
    print("=" * 50)
    
    analyzer = HistogramAnalyzer()
    
    # Tìm 2 ảnh để so sánh
    output_files = []
    try:
        output_files = [f for f in os.listdir(analyzer.output_dir) 
                       if f.startswith('stego_') and f.endswith('.png')]
    except:
        pass
    
    if len(output_files) < 1:
        print("⚠️  No stego images found for comparison")
        return False
    
    # Tìm original image
    stego_path = os.path.join(analyzer.output_dir, output_files[0])
    
    # Tìm cover image tương ứng
    cover_candidates = [
        os.path.join(analyzer.test_images_dir, "Lenna_test_image.webp"),
        os.path.join(analyzer.test_images_dir, "Lenna_test_image.png"),
    ]
    
    cover_path = None
    for candidate in cover_candidates:
        if os.path.exists(candidate):
            cover_path = candidate
            break
    
    if not cover_path:
        print("❌ No cover image found for comparison")
        return False
    
    print(f"📷 Cover: {os.path.basename(cover_path)}")
    print(f"🔒 Stego: {os.path.basename(stego_path)}")
    
    try:
        # Create comparison
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(analyzer.doc_dir, f"quick_comparison_{timestamp}.png")
        
        create_custom_histogram(cover_path, stego_path, output_path)
        
        print(f"✅ Comparison chart saved: {os.path.basename(output_path)}")
        return True
        
    except Exception as e:
        print(f"❌ Error creating comparison: {str(e)}")
        return False

def main():
    """Main test function"""
    
    print("🧪 ZK-SNARK STEGANOGRAPHY - HISTOGRAM TEST SUITE")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    success_count = 0
    total_tests = 2
    
    # Test 1: Full analysis
    print("TEST 1: Full Histogram Analysis")
    if test_histogram_analysis():
        success_count += 1
        print("✅ PASSED")
    else:
        print("❌ FAILED")
    
    print("\n" + "-" * 60 + "\n")
    
    # Test 2: Quick comparison
    print("TEST 2: Quick Histogram Comparison")
    if quick_comparison():
        success_count += 1
        print("✅ PASSED")
    else:
        print("❌ FAILED")
    
    # Summary
    print("\n" + "=" * 60)
    print(f"🏁 TEST SUMMARY: {success_count}/{total_tests} tests passed")
    
    if success_count == total_tests:
        print("🎉 ALL TESTS PASSED!")
        return True
    else:
        print("⚠️  Some tests failed")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)