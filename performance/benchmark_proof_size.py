#!/usr/bin/env python3
"""
Performance Benchmark: Proof Size vs Processing Time
Analyzes how ZK proof size affects embedding and extraction performance
"""

import sys
import time
import json
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
sys.path.append('../src')
from zk_stego.hybrid_proof_artifact import embed_chaos_proof, extract_chaos_proof

def generate_test_proofs():
    """Generate ZK proofs of different sizes"""
    print("Generating test proofs of various sizes...")
    
    proof_configs = [
        {"name": "Small", "elements": 2, "size_factor": 1},
        {"name": "Medium", "elements": 4, "size_factor": 2}, 
        {"name": "Large", "elements": 8, "size_factor": 4},
        {"name": "Extra Large", "elements": 16, "size_factor": 8},
        {"name": "Huge", "elements": 32, "size_factor": 16}
    ]
    
    proofs = []
    
    for config in proof_configs:
        # Generate realistic proof structure
        pi_a_elements = ["0x" + "".join([f"{i:02x}" for i in range(20*config['size_factor'])]) 
                        for _ in range(config['elements']//2 or 1)]
        
        pi_b_elements = [["0x" + "".join([f"{i:02x}" for i in range(30*config['size_factor'])]),
                         "0x" + "".join([f"{i:02x}" for i in range(35*config['size_factor'])])]
                        for _ in range(config['elements']//2 or 1)]
        
        pi_c_elements = ["0x" + "".join([f"{i:02x}" for i in range(25*config['size_factor'])]) 
                        for _ in range(config['elements']//2 or 1)]
        
        # Add additional fields for larger proofs
        proof = {
            "pi_a": pi_a_elements,
            "pi_b": pi_b_elements,
            "pi_c": pi_c_elements,
            "protocol": "groth16",
            "curve": "bn128"
        }
        
        # Add extra fields for larger proofs
        if config['size_factor'] >= 2:
            proof["metadata"] = {
                "circuit_name": f"large_circuit_{config['size_factor']}",
                "constraints": config['size_factor'] * 1000,
                "variables": config['size_factor'] * 500
            }
        
        if config['size_factor'] >= 4:
            proof["auxiliary_data"] = [
                f"aux_field_{i}_{j}" for i in range(config['size_factor']) 
                for j in range(config['size_factor'])
            ]
        
        # Calculate proof size
        proof_json = json.dumps(proof, separators=(',', ':'))
        proof_size = len(proof_json.encode('utf-8'))
        
        filename = f"test_proof_{config['name'].lower().replace(' ', '_')}.json"
        with open(filename, 'w') as f:
            json.dump(proof, f, indent=2)
        
        proofs.append({
            'name': config['name'],
            'filename': filename,
            'size_bytes': proof_size,
            'size_bits': proof_size * 8,
            'elements': config['elements'],
            'proof_data': proof
        })
        
        print(f"   {config['name']}: {proof_size} bytes ({proof_size * 8} bits)")
    
    return proofs

def create_test_image():
    """Create a single test image for consistent testing"""
    size = 256
    img = np.random.randint(80, 180, (size, size, 3), dtype=np.uint8)
    
    # Add texture patterns
    for i in range(0, size, 32):
        for j in range(0, size, 32):
            if (i//32 + j//32) % 2 == 0:
                img[i:i+16, j:j+16] = [255, 255, 255]
            else:
                img[i:i+16, j:j+16] = [0, 0, 0]
    
    Image.fromarray(img).save('test_image_256.png')
    print("Created test image (256×256)")
    return 'test_image_256.png'

def benchmark_embedding_performance(proofs, test_image):
    """Benchmark embedding performance vs proof size"""
    print("\nBenchmarking embedding performance...")
    
    results = []
    
    for proof_info in proofs:
        print(f"   Testing {proof_info['name']} proof ({proof_info['size_bytes']} bytes)...")
        
        # Create public inputs
        public = {
            'inputs': ['1', '42', '123'],
            'proof_length': proof_info['size_bits'],
            'positions': []
        }
        
        public_filename = f"test_public_{proof_info['name'].lower().replace(' ', '_')}.json"
        with open(public_filename, 'w') as f:
            json.dump(public, f)
        
        # Benchmark embedding
        embedding_times = []
        embedding_success = 0
        
        for run in range(3):  # 3 runs for averaging
            stego_filename = f"stego_{proof_info['name'].lower().replace(' ', '_')}_{run}.png"
            
            start_time = time.perf_counter()
            success = embed_chaos_proof(
                test_image,
                stego_filename,
                proof_info['filename'],
                public_filename,
                f"secret_key_{proof_info['name']}"
            )
            end_time = time.perf_counter()
            
            if success:
                embedding_times.append(end_time - start_time)
                embedding_success += 1
            
            # Clean up
            try:
                import os
                os.remove(stego_filename)
            except:
                pass
        
        avg_embedding_time = np.mean(embedding_times) * 1000 if embedding_times else 0
        std_embedding_time = np.std(embedding_times) * 1000 if len(embedding_times) > 1 else 0
        
        results.append({
            'name': proof_info['name'],
            'size_bytes': proof_info['size_bytes'],
            'size_bits': proof_info['size_bits'],
            'embedding_time_ms': avg_embedding_time,
            'embedding_time_std': std_embedding_time,
            'embedding_success_rate': embedding_success / 3 * 100,
            'elements': proof_info['elements']
        })
        
        if embedding_times:
            print(f"     Embedding: {avg_embedding_time:.2f}±{std_embedding_time:.2f} ms")
        else:
            print(f"     Embedding: FAILED")
        
        # Clean up
        try:
            import os
            os.remove(public_filename)
        except:
            pass
    
    return results

def create_proof_size_plots(embedding_results):
    """Create performance plots for proof size analysis"""
    print("\nCreating proof size performance plots...")
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Extract data
    sizes_bytes = [r['size_bytes'] for r in embedding_results]
    names = [r['name'] for r in embedding_results]
    
    # Plot 1: Embedding Time vs Proof Size
    embedding_times = [r['embedding_time_ms'] for r in embedding_results]
    embedding_stds = [r['embedding_time_std'] for r in embedding_results]
    
    ax1.errorbar(sizes_bytes, embedding_times, yerr=embedding_stds, 
                marker='o', linewidth=2, markersize=8, capsize=5)
    ax1.set_xlabel('Proof Size (bytes)')
    ax1.set_ylabel('Embedding Time (ms)')
    ax1.set_title('Embedding Performance vs Proof Size')
    ax1.grid(True, alpha=0.3)
    ax1.set_xscale('log')
    
    # Plot 2: Success Rate vs Proof Size
    embedding_success = [r['embedding_success_rate'] for r in embedding_results]
    
    ax2.plot(sizes_bytes, embedding_success, 'b-o', label='Embedding Success', linewidth=2, markersize=8)
    ax2.set_xlabel('Proof Size (bytes)')
    ax2.set_ylabel('Success Rate (%)')
    ax2.set_title('Success Rate vs Proof Size')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_xscale('log')
    ax2.set_ylim(0, 105)
    
    plt.tight_layout()
    plt.savefig('proof_size_performance.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("Saved proof_size_performance.png")

def generate_proof_size_report(proofs, embedding_results):
    """Generate detailed proof size performance report"""
    print("\nGenerating proof size performance report...")
    
    report = {
        'benchmark_info': {
            'date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'test_type': 'Proof Size Performance Analysis',
            'description': 'Performance analysis of ZK-SNARK chaos steganography across different proof sizes'
        },
        'proof_configurations': proofs,
        'embedding_performance': embedding_results,
        'summary': {
            'size_range': f"{min(r['size_bytes'] for r in embedding_results)} - {max(r['size_bytes'] for r in embedding_results)} bytes",
            'embedding_time_range': f"{min(r['embedding_time_ms'] for r in embedding_results if r['embedding_time_ms'] > 0):.2f} - {max(r['embedding_time_ms'] for r in embedding_results):.2f} ms",
            'max_successful_size': max([r['size_bytes'] for r in embedding_results if r['embedding_success_rate'] > 0], default=0)
        }
    }
    
    with open('proof_size_benchmark_results.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print("Saved proof_size_benchmark_results.json")
    
    # Create markdown report
    with open('PROOF_SIZE_PERFORMANCE.md', 'w') as f:
        f.write("# Proof Size Performance Analysis\n\n")
        f.write("## Overview\n")
        f.write("Performance analysis of ZK-SNARK chaos steganography across different proof sizes.\n\n")
        
        f.write("## Test Configuration\n")
        f.write(f"- **Date**: {report['benchmark_info']['date']}\n")
        f.write(f"- **Image Size**: 256×256 pixels\n")
        f.write(f"- **Proof Size Range**: {report['summary']['size_range']}\n")
        f.write(f"- **Test Iterations**: 3 embedding runs (averaged)\n\n")
        
        f.write("## Results Summary\n")
        f.write(f"- **Embedding Time Range**: {report['summary']['embedding_time_range']}\n")
        f.write(f"- **Maximum Successful Size**: {report['summary']['max_successful_size']} bytes\n\n")
        
        f.write("## Detailed Results\n")
        f.write("| Proof Type | Size (bytes) | Size (bits) | Embed Time (ms) | Embed Success |\n")
        f.write("|------------|-------------|-------------|----------------|---------------|\n")
        
        for i, proof in enumerate(proofs):
            embed_result = embedding_results[i]
            
            f.write(f"| {proof['name']} | {proof['size_bytes']} | {proof['size_bits']} | ")
            f.write(f"{embed_result['embedding_time_ms']:.2f}±{embed_result['embedding_time_std']:.2f} | ")
            f.write(f"{embed_result['embedding_success_rate']:.0f}% |\n")
        
        f.write("\n## Observations\n")
        f.write("- Embedding time scales with proof size\n")
        f.write("- Success rate depends on image capacity vs proof size\n")
        f.write("- Larger proofs may fail due to insufficient embedding positions\n")
    
    print("Saved PROOF_SIZE_PERFORMANCE.md")

def cleanup_test_files():
    """Clean up test files"""
    import os
    for f in os.listdir('.'):
        if (f.startswith('test_proof_') or f.startswith('test_public_') or 
            f.startswith('stego_') or f == 'test_image_256.png'):
            try:
                os.remove(f)
            except:
                pass

def main():
    """Main benchmark function"""
    print("ZK-SNARK Chaos Steganography - Proof Size Performance Benchmark")
    print("=" * 80)
    
    try:
        # Generate test proofs
        proofs = generate_test_proofs()
        
        # Create test image
        test_image = create_test_image()
        
        # Run benchmarks
        embedding_results = benchmark_embedding_performance(proofs, test_image)
        
        # Create visualizations
        create_proof_size_plots(embedding_results)
        
        # Generate report
        generate_proof_size_report(proofs, embedding_results)
        
        print("\nProof size performance benchmark complete!")
        print("Files generated:")
        print("   - proof_size_performance.png")
        print("   - proof_size_benchmark_results.json")
        print("   - PROOF_SIZE_PERFORMANCE.md")
        
    finally:
        # Cleanup
        cleanup_test_files()

if __name__ == "__main__":
    main()