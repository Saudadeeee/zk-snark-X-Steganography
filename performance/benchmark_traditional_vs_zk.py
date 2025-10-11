#!/usr/bin/env python3
"""
Performance Benchmark: ZK-SNARK vs Traditional Steganography
Compares processing time, capacity, and security features
"""

import sys
import time
import json
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import struct
sys.path.append('../src')
from zk_stego.hybrid_proof_artifact import embed_chaos_proof, extract_chaos_proof

class TraditionalSteganography:
    """Traditional LSB steganography implementation for comparison"""
    
    @staticmethod
    def embed_lsb(image_path, message, output_path, password=None):
        """Embed message using simple LSB steganography"""
        start_time = time.perf_counter()
        
        img = Image.open(image_path).convert('RGB')
        pixels = np.array(img)
        
        # Convert message to binary
        message_bytes = message.encode('utf-8')
        message_bits = ''.join(format(byte, '08b') for byte in message_bytes)
        
        # Add length header (32 bits)
        length_bits = format(len(message_bits), '032b')
        full_bits = length_bits + message_bits + '1111111111111110'  # End marker
        
        if len(full_bits) > pixels.size:
            return False, 0
        
        # Simple sequential LSB embedding
        bit_index = 0
        for i in range(pixels.shape[0]):
            for j in range(pixels.shape[1]):
                for k in range(3):  # RGB channels
                    if bit_index < len(full_bits):
                        pixels[i, j, k] = (pixels[i, j, k] & 0xFE) | int(full_bits[bit_index])
                        bit_index += 1
                    else:
                        break
                if bit_index >= len(full_bits):
                    break
            if bit_index >= len(full_bits):
                break
        
        # Save result
        result_img = Image.fromarray(pixels)
        result_img.save(output_path)
        
        end_time = time.perf_counter()
        return True, (end_time - start_time) * 1000
    
    @staticmethod
    def extract_lsb(stego_path, password=None):
        """Extract message using simple LSB steganography"""
        start_time = time.perf_counter()
        
        img = Image.open(stego_path).convert('RGB')
        pixels = np.array(img)
        
        # Extract length (first 32 bits)
        length_bits = ''
        bit_index = 0
        
        for i in range(pixels.shape[0]):
            for j in range(pixels.shape[1]):
                for k in range(3):
                    if bit_index < 32:
                        length_bits += str(pixels[i, j, k] & 1)
                        bit_index += 1
                    else:
                        break
                if bit_index >= 32:
                    break
            if bit_index >= 32:
                break
        
        message_length = int(length_bits, 2)
        
        # Extract message bits
        message_bits = ''
        total_bits_needed = 32 + message_length + 16  # length + message + end marker
        
        bit_index = 0
        for i in range(pixels.shape[0]):
            for j in range(pixels.shape[1]):
                for k in range(3):
                    if bit_index < total_bits_needed:
                        if bit_index >= 32:  # Skip length header
                            message_bits += str(pixels[i, j, k] & 1)
                        bit_index += 1
                    else:
                        break
                if bit_index >= total_bits_needed:
                    break
            if bit_index >= total_bits_needed:
                break
        
        # Convert bits to message
        message_bits = message_bits[:message_length]  # Remove end marker
        message_bytes = bytearray()
        
        for i in range(0, len(message_bits), 8):
            byte_bits = message_bits[i:i+8]
            if len(byte_bits) == 8:
                message_bytes.append(int(byte_bits, 2))
        
        message = message_bytes.decode('utf-8', errors='ignore')
        
        end_time = time.perf_counter()
        return True, message, (end_time - start_time) * 1000

def create_test_images():
    """Create test images of different sizes"""
    print("Creating test images...")
    
    sizes = [64, 128, 256, 512]
    image_files = []
    
    for size in sizes:
        # Create diverse test pattern
        img = np.random.randint(50, 200, (size, size, 3), dtype=np.uint8)
        
        # Add structured patterns for realism
        block_size = max(4, size // 32)
        for i in range(0, size, block_size*2):
            for j in range(0, size, block_size*2):
                # Create checkerboard-like pattern
                if (i//block_size + j//block_size) % 3 == 0:
                    img[i:i+block_size, j:j+block_size] = [200, 150, 100]
                elif (i//block_size + j//block_size) % 3 == 1:
                    img[i:i+block_size, j:j+block_size] = [100, 150, 200]
        
        filename = f'test_image_{size}x{size}.png'
        Image.fromarray(img).save(filename)
        image_files.append((filename, size))
        print(f"   Created {filename}")
    
    return image_files

def create_test_messages():
    """Create test messages of different sizes"""
    messages = [
        {"name": "Short", "content": "Hello World", "length": 11},
        {"name": "Medium", "content": "This is a medium length message for testing steganography performance." * 2, "length": 0},
        {"name": "Long", "content": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10, "length": 0},
        {"name": "Very Long", "content": "A" * 1000 + "B" * 1000 + "C" * 1000, "length": 3000}
    ]
    
    for msg in messages:
        if msg["length"] == 0:
            msg["length"] = len(msg["content"])
    
    return messages

def benchmark_traditional_performance(test_images, test_messages):
    """Benchmark traditional LSB steganography"""
    print("\nBenchmarking traditional LSB steganography...")
    
    results = []
    
    for img_file, img_size in test_images:
        for msg_info in test_messages:
            print(f"   Testing {img_size}x{img_size} with {msg_info['name']} message...")
            
            # Test embedding
            embedding_times = []
            extraction_times = []
            success_count = 0
            
            for run in range(3):
                stego_file = f"traditional_stego_{img_size}_{msg_info['name']}_{run}.png"
                
                # Embed
                embed_success, embed_time = TraditionalSteganography.embed_lsb(
                    img_file, msg_info['content'], stego_file
                )
                
                if embed_success:
                    embedding_times.append(embed_time)
                    
                    # Extract
                    extract_success, extracted_msg, extract_time = TraditionalSteganography.extract_lsb(stego_file)
                    
                    if extract_success and extracted_msg == msg_info['content']:
                        extraction_times.append(extract_time)
                        success_count += 1
                
                # Cleanup
                try:
                    import os
                    os.remove(stego_file)
                except:
                    pass
            
            avg_embed_time = np.mean(embedding_times) if embedding_times else 0
            avg_extract_time = np.mean(extraction_times) if extraction_times else 0
            success_rate = success_count / 3 * 100
            
            results.append({
                'method': 'Traditional LSB',
                'image_size': img_size,
                'message_type': msg_info['name'],
                'message_length': msg_info['length'],
                'embedding_time_ms': avg_embed_time,
                'extraction_time_ms': avg_extract_time,
                'total_time_ms': avg_embed_time + avg_extract_time,
                'success_rate': success_rate,
                'capacity_efficiency': msg_info['length'] / (img_size * img_size * 3) * 100
            })
            
            print(f"     Embed: {avg_embed_time:.2f}ms, Extract: {avg_extract_time:.2f}ms, Success: {success_rate:.0f}%")
    
    return results

def benchmark_zk_performance(test_images, test_messages):
    """Benchmark ZK-SNARK chaos steganography"""
    print("\nBenchmarking ZK-SNARK chaos steganography...")
    
    results = []
    
    # Create test proof
    test_proof = {
        "pi_a": ["0x1234567890abcdef"] * 4,
        "pi_b": [["0xabcdef1234567890", "0xfedcba0987654321"]] * 4,
        "pi_c": ["0x987654321fedcba0"] * 4,
        "protocol": "groth16",
        "curve": "bn128"
    }
    
    with open('test_proof_comparison.json', 'w') as f:
        json.dump(test_proof, f)
    
    for img_file, img_size in test_images:
        for msg_info in test_messages:
            if msg_info['length'] > 500:  # Skip very long messages for ZK (capacity constraint)
                continue
                
            print(f"   Testing {img_size}x{img_size} with {msg_info['name']} message...")
            
            # Create public inputs
            public = {
                'inputs': ['1', '42', str(msg_info['length'])],
                'proof_length': len(json.dumps(test_proof)) * 8,
                'positions': []
            }
            
            with open('test_public_comparison.json', 'w') as f:
                json.dump(public, f)
            
            embedding_times = []
            extraction_times = []
            success_count = 0
            
            for run in range(3):
                stego_file = f"zk_stego_{img_size}_{msg_info['name']}_{run}.png"
                
                # Embed
                start_time = time.perf_counter()
                embed_success = embed_chaos_proof(
                    img_file, stego_file, 'test_proof_comparison.json', 
                    'test_public_comparison.json', f"secret_{msg_info['name']}"
                )
                end_time = time.perf_counter()
                
                if embed_success:
                    embed_time = (end_time - start_time) * 1000
                    embedding_times.append(embed_time)
                    
                    # Extract
                    start_time = time.perf_counter()
                    extracted_artifact = extract_chaos_proof(stego_file)
                    end_time = time.perf_counter()
                    
                    extract_success = extracted_artifact is not None
                    
                    if extract_success:
                        extract_time = (end_time - start_time) * 1000
                        extraction_times.append(extract_time)
                        success_count += 1
                
                # Cleanup
                try:
                    import os
                    os.remove(stego_file)
                except:
                    pass
            
            avg_embed_time = np.mean(embedding_times) if embedding_times else 0
            avg_extract_time = np.mean(extraction_times) if extraction_times else 0
            success_rate = success_count / 3 * 100
            
            results.append({
                'method': 'ZK-SNARK Chaos',
                'image_size': img_size,
                'message_type': msg_info['name'],
                'message_length': len(json.dumps(test_proof)),
                'embedding_time_ms': avg_embed_time,
                'extraction_time_ms': avg_extract_time,
                'total_time_ms': avg_embed_time + avg_extract_time,
                'success_rate': success_rate,
                'capacity_efficiency': len(json.dumps(test_proof)) / (img_size * img_size * 3) * 100
            })
            
            print(f"     Embed: {avg_embed_time:.2f}ms, Extract: {avg_extract_time:.2f}ms, Success: {success_rate:.0f}%")
    
    # Cleanup
    try:
        import os
        os.remove('test_proof_comparison.json')
        os.remove('test_public_comparison.json')
    except:
        pass
    
    return results

def create_comparison_plots(traditional_results, zk_results):
    """Create comparison plots"""
    print("\nCreating comparison plots...")
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
    
    # Plot 1: Embedding Time Comparison
    trad_embed_times = [r['embedding_time_ms'] for r in traditional_results]
    trad_image_sizes = [r['image_size'] for r in traditional_results]
    zk_embed_times = [r['embedding_time_ms'] for r in zk_results if r['embedding_time_ms'] > 0]
    zk_image_sizes = [r['image_size'] for r in zk_results if r['embedding_time_ms'] > 0]
    
    ax1.scatter(trad_image_sizes, trad_embed_times, alpha=0.7, label='Traditional LSB', color='blue')
    ax1.scatter(zk_image_sizes, zk_embed_times, alpha=0.7, label='ZK-SNARK Chaos', color='red')
    ax1.set_xlabel('Image Size (pixels)')
    ax1.set_ylabel('Embedding Time (ms)')
    ax1.set_title('Embedding Performance Comparison')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Extraction Time Comparison
    trad_extract_times = [r['extraction_time_ms'] for r in traditional_results]
    zk_extract_times = [r['extraction_time_ms'] for r in zk_results if r['extraction_time_ms'] > 0]
    
    ax2.scatter(trad_image_sizes, trad_extract_times, alpha=0.7, label='Traditional LSB', color='blue')
    ax2.scatter(zk_image_sizes, zk_extract_times, alpha=0.7, label='ZK-SNARK Chaos', color='red')
    ax2.set_xlabel('Image Size (pixels)')
    ax2.set_ylabel('Extraction Time (ms)')
    ax2.set_title('Extraction Performance Comparison')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Total Time Comparison
    trad_total_times = [r['total_time_ms'] for r in traditional_results]
    zk_total_times = [r['total_time_ms'] for r in zk_results if r['total_time_ms'] > 0]
    
    ax3.scatter(trad_image_sizes, trad_total_times, alpha=0.7, label='Traditional LSB', color='blue')
    ax3.scatter(zk_image_sizes, zk_total_times, alpha=0.7, label='ZK-SNARK Chaos', color='red')
    ax3.set_xlabel('Image Size (pixels)')
    ax3.set_ylabel('Total Time (ms)')
    ax3.set_title('Total Processing Time Comparison')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # Plot 4: Success Rate Comparison
    trad_success = [r['success_rate'] for r in traditional_results]
    zk_success = [r['success_rate'] for r in zk_results]
    
    ax4.scatter(trad_image_sizes, trad_success, alpha=0.7, label='Traditional LSB', color='blue')
    ax4.scatter(zk_image_sizes, zk_success, alpha=0.7, label='ZK-SNARK Chaos', color='red')
    ax4.set_xlabel('Image Size (pixels)')
    ax4.set_ylabel('Success Rate (%)')
    ax4.set_title('Success Rate Comparison')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim(0, 105)
    
    plt.tight_layout()
    plt.savefig('traditional_vs_zk_performance.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("Saved traditional_vs_zk_performance.png")

def generate_comparison_report(traditional_results, zk_results):
    """Generate comparison report"""
    print("\nGenerating comparison report...")
    
    report = {
        'benchmark_info': {
            'date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'test_type': 'Traditional vs ZK-SNARK Comparison',
            'description': 'Performance comparison between traditional LSB and ZK-SNARK chaos steganography'
        },
        'traditional_results': traditional_results,
        'zk_results': zk_results,
        'summary': {
            'traditional_avg_embed': np.mean([r['embedding_time_ms'] for r in traditional_results if r['embedding_time_ms'] > 0]),
            'zk_avg_embed': np.mean([r['embedding_time_ms'] for r in zk_results if r['embedding_time_ms'] > 0]),
            'traditional_avg_extract': np.mean([r['extraction_time_ms'] for r in traditional_results if r['extraction_time_ms'] > 0]),
            'zk_avg_extract': np.mean([r['extraction_time_ms'] for r in zk_results if r['extraction_time_ms'] > 0])
        }
    }
    
    with open('traditional_vs_zk_results.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print("Saved traditional_vs_zk_results.json")
    
    # Create markdown report
    with open('TRADITIONAL_VS_ZK_PERFORMANCE.md', 'w') as f:
        f.write("# Traditional vs ZK-SNARK Performance Comparison\n\n")
        f.write("## Overview\n")
        f.write("Performance comparison between traditional LSB steganography and ZK-SNARK chaos steganography.\n\n")
        
        f.write("## Summary Statistics\n")
        f.write(f"- **Traditional Avg Embedding**: {report['summary']['traditional_avg_embed']:.2f} ms\n")
        f.write(f"- **ZK-SNARK Avg Embedding**: {report['summary']['zk_avg_embed']:.2f} ms\n")
        f.write(f"- **Traditional Avg Extraction**: {report['summary']['traditional_avg_extract']:.2f} ms\n")
        f.write(f"- **ZK-SNARK Avg Extraction**: {report['summary']['zk_avg_extract']:.2f} ms\n\n")
        
        f.write("## Key Differences\n")
        f.write("- **Security**: ZK-SNARK provides cryptographic proof verification\n")
        f.write("- **Capacity**: Traditional LSB has higher capacity for large messages\n")
        f.write("- **Performance**: Traditional LSB is faster for simple embedding\n")
        f.write("- **Robustness**: ZK-SNARK provides better security guarantees\n")
    
    print("Saved TRADITIONAL_VS_ZK_PERFORMANCE.md")

def cleanup_test_files():
    """Clean up test files"""
    import os
    for f in os.listdir('.'):
        if (f.startswith('test_image_') or f.startswith('traditional_stego_') or 
            f.startswith('zk_stego_') or f.startswith('test_proof_') or 
            f.startswith('test_public_')):
            try:
                os.remove(f)
            except:
                pass

def main():
    """Main benchmark function"""
    print("ZK-SNARK Chaos Steganography - Traditional vs ZK Performance Comparison")
    print("=" * 80)
    
    try:
        # Create test data
        test_images = create_test_images()
        test_messages = create_test_messages()
        
        # Run benchmarks
        traditional_results = benchmark_traditional_performance(test_images, test_messages)
        zk_results = benchmark_zk_performance(test_images, test_messages)
        
        # Create visualizations
        create_comparison_plots(traditional_results, zk_results)
        
        # Generate report
        generate_comparison_report(traditional_results, zk_results)
        
        print("\nTraditional vs ZK-SNARK comparison complete!")
        print("Files generated:")
        print("   - traditional_vs_zk_performance.png")
        print("   - traditional_vs_zk_results.json")
        print("   - TRADITIONAL_VS_ZK_PERFORMANCE.md")
        
    finally:
        # Cleanup
        cleanup_test_files()

if __name__ == "__main__":
    main()