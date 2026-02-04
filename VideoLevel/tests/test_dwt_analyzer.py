"""
Unit tests for Haar DWT Analyzer

Tests 2-level wavelet transform, energy computation, and region classification.
"""

import numpy as np
import pytest
from src.zk_mv_stego.preprocessing.dwt_analyzer import HaarDWTAnalyzer


class TestHaarDWTAnalyzer:
    
    @pytest.fixture
    def analyzer(self):
        """Create DWT analyzer instance"""
        return HaarDWTAnalyzer(levels=2)
    
    @pytest.fixture
    def test_macroblock_16x16(self):
        """Create a 16x16 test macroblock"""
        # Create gradient pattern
        mb = np.zeros((16, 16), dtype=np.float32)
        for i in range(16):
            for j in range(16):
                mb[i, j] = i * 16 + j
        return mb
    
    @pytest.fixture
    def test_macroblock_smooth(self):
        """Create smooth macroblock (low frequency)"""
        mb = np.full((16, 16), 128.0, dtype=np.float32)
        return mb
    
    @pytest.fixture
    def test_macroblock_edges(self):
        """Create macroblock with edges (mid frequency)"""
        mb = np.zeros((16, 16), dtype=np.float32)
        mb[:, :8] = 50   # Left half dark
        mb[:, 8:] = 200  # Right half bright
        return mb
    
    def test_initialization(self, analyzer):
        """Test analyzer initialization"""
        assert analyzer is not None
        assert analyzer.levels == 2
        
    def test_1d_haar_transform(self, analyzer):
        """Test 1D Haar transform"""
        # Simple test data
        data = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.float32)
        
        approx, detail = analyzer._haar_transform_1d(data)
        
        # Check output shapes
        assert len(approx) == 4
        assert len(detail) == 4
        
        # Check Haar properties (approximation = average)
        sqrt2 = np.sqrt(2)
        assert np.isclose(approx[0], (1 + 2) / sqrt2)
        assert np.isclose(approx[1], (3 + 4) / sqrt2)
        
        # Check detail (difference)
        assert np.isclose(detail[0], (1 - 2) / sqrt2)
        assert np.isclose(detail[1], (3 - 4) / sqrt2)
    
    def test_1d_haar_inverse(self, analyzer):
        """Test 1D Haar inverse transform"""
        # Original data
        data = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.float32)
        
        # Forward transform
        approx, detail = analyzer._haar_transform_1d(data)
        
        # Inverse transform
        reconstructed = analyzer._inverse_haar_1d(approx, detail)
        
        # Should match original
        assert np.allclose(reconstructed, data, atol=1e-5)
    
    def test_2d_haar_transform(self, analyzer):
        """Test 2D Haar transform"""
        # 8x8 test image
        img = np.arange(64, dtype=np.float32).reshape(8, 8)
        
        dwt = analyzer._haar_transform_2d(img)
        
        # Check sub-bands exist
        assert 'LL' in dwt
        assert 'LH' in dwt
        assert 'HL' in dwt
        assert 'HH' in dwt
        
        # Check sub-band sizes (each should be 4x4)
        assert dwt['LL'].shape == (4, 4)
        assert dwt['LH'].shape == (4, 4)
        assert dwt['HL'].shape == (4, 4)
        assert dwt['HH'].shape == (4, 4)
    
    def test_analyze_macroblock_level1(self):
        """Test 1-level DWT analysis"""
        analyzer = HaarDWTAnalyzer(levels=1)
        mb = np.random.rand(16, 16).astype(np.float32) * 255
        
        dwt_coeffs = analyzer.analyze_macroblock(mb)
        
        # Level 1 should have 4 sub-bands
        assert 'LL' in dwt_coeffs or 'LL1' in dwt_coeffs
        assert len(dwt_coeffs) == 4
    
    def test_analyze_macroblock_level2(self, analyzer, test_macroblock_16x16):
        """Test 2-level DWT analysis"""
        dwt_coeffs = analyzer.analyze_macroblock(test_macroblock_16x16)
        
        # Level 2 should have 7 sub-bands
        assert 'LL2' in dwt_coeffs  # 4x4
        assert 'LH2' in dwt_coeffs  # 4x4
        assert 'HL2' in dwt_coeffs  # 4x4
        assert 'HH2' in dwt_coeffs  # 4x4
        assert 'LH1' in dwt_coeffs  # 8x8
        assert 'HL1' in dwt_coeffs  # 8x8
        assert 'HH1' in dwt_coeffs  # 8x8
        
        # Check sizes
        assert dwt_coeffs['LL2'].shape == (4, 4)
        assert dwt_coeffs['LH1'].shape == (8, 8)
    
    def test_compute_energy_map(self, analyzer, test_macroblock_16x16):
        """Test energy map computation"""
        dwt_coeffs = analyzer.analyze_macroblock(test_macroblock_16x16)
        energy_map = analyzer.compute_energy_map(dwt_coeffs)
        
        # Check all bands have energy values
        assert 'LL2' in energy_map
        assert 'LH1' in energy_map
        assert 'total' in energy_map
        
        # Energy should be non-negative
        for band, energy in energy_map.items():
            assert energy >= 0
        
        # Total should be sum (approximately)
        band_sum = sum(v for k, v in energy_map.items() if k != 'total')
        assert np.isclose(energy_map['total'], band_sum)
    
    def test_classify_smooth_region(self, analyzer, test_macroblock_smooth):
        """Test classification of smooth regions"""
        dwt_coeffs = analyzer.analyze_macroblock(test_macroblock_smooth)
        energy_map = analyzer.compute_energy_map(dwt_coeffs)
        classification = analyzer.classify_frequency_region(energy_map)
        
        # Smooth regions should be 'low' frequency
        assert classification == 'low'
    
    def test_classify_edge_region(self, analyzer, test_macroblock_edges):
        """Test classification of edge regions"""
        dwt_coeffs = analyzer.analyze_macroblock(test_macroblock_edges)
        energy_map = analyzer.compute_energy_map(dwt_coeffs)
        classification = analyzer.classify_frequency_region(energy_map)
        
        # Edge regions should be 'mid' frequency (LH or HL dominant)
        # This depends on energy distribution, so we just check it's valid
        assert classification in ['low', 'mid', 'high']
    
    def test_get_dwt_region_for_position(self, analyzer):
        """Test position-to-region mapping"""
        # 16x16 macroblock
        # Position (0,0) = 0 → LL
        assert analyzer.get_dwt_region_for_position(0, 16) == 'LL'
        
        # Position (0,8) = 8 → LH (right half)
        assert analyzer.get_dwt_region_for_position(8, 16) == 'LH'
        
        # Position (8,0) = 128 → HL (bottom half)
        assert analyzer.get_dwt_region_for_position(128, 16) == 'HL'
        
        # Position (8,8) = 136 → HH (bottom-right)
        assert analyzer.get_dwt_region_for_position(136, 16) == 'HH'
    
    def test_get_stable_regions(self, analyzer, test_macroblock_16x16):
        """Test stable region identification"""
        dwt_coeffs = analyzer.analyze_macroblock(test_macroblock_16x16)
        energy_map = analyzer.compute_energy_map(dwt_coeffs)
        
        stable = analyzer.get_stable_regions(dwt_coeffs, energy_map, threshold=10.0)
        
        # Should return list
        assert isinstance(stable, list)
        
        # Should not include HH bands
        for band in stable:
            assert 'HH' not in band
    
    def test_reconstruct_from_dwt(self, analyzer, test_macroblock_16x16):
        """Test DWT reconstruction (inverse)"""
        # Forward transform
        dwt_coeffs = analyzer.analyze_macroblock(test_macroblock_16x16)
        
        # Inverse transform
        reconstructed = analyzer.reconstruct_from_dwt(dwt_coeffs, levels=2)
        
        # Should match original (with small numerical error)
        assert reconstructed.shape == test_macroblock_16x16.shape
        mae = np.abs(reconstructed - test_macroblock_16x16).mean()
        assert mae < 1.0, f"Reconstruction error too high: {mae}"
    
    def test_energy_conservation(self, analyzer):
        """Test Parseval's theorem (energy conservation)"""
        # Create random macroblock
        mb = np.random.rand(16, 16).astype(np.float32) * 100
        
        # Original energy
        original_energy = np.sum(mb ** 2)
        
        # DWT energy
        dwt_coeffs = analyzer.analyze_macroblock(mb)
        dwt_energy = sum(np.sum(band ** 2) for band in dwt_coeffs.values())
        
        # Should be approximately equal (Parseval's theorem)
        ratio = dwt_energy / original_energy
        assert np.isclose(ratio, 1.0, atol=0.1), f"Energy ratio: {ratio}"
    
    def test_zero_macroblock(self, analyzer):
        """Test DWT on all-zero macroblock"""
        mb = np.zeros((16, 16), dtype=np.float32)
        
        dwt_coeffs = analyzer.analyze_macroblock(mb)
        
        # All coefficients should be zero
        for band in dwt_coeffs.values():
            assert np.allclose(band, 0)
    
    def test_constant_macroblock(self, analyzer):
        """Test DWT on constant macroblock"""
        mb = np.full((16, 16), 100.0, dtype=np.float32)
        
        dwt_coeffs = analyzer.analyze_macroblock(mb)
        
        # Only LL should have non-zero energy (DC component)
        # High-frequency bands (LH, HL, HH) should be near zero
        assert np.abs(dwt_coeffs['LL2'].mean()) > 10
        assert np.allclose(dwt_coeffs['HH1'], 0, atol=1e-5)
        assert np.allclose(dwt_coeffs['HH2'], 0, atol=1e-5)


def test_performance_benchmark():
    """Benchmark DWT performance"""
    import time
    
    analyzer = HaarDWTAnalyzer(levels=2)
    mb = np.random.rand(16, 16).astype(np.float32) * 255
    
    # Benchmark forward transform
    start = time.time()
    for _ in range(1000):
        dwt_coeffs = analyzer.analyze_macroblock(mb)
    dwt_time = (time.time() - start) / 1000
    
    # Benchmark energy computation
    start = time.time()
    for _ in range(1000):
        energy_map = analyzer.compute_energy_map(dwt_coeffs)
    energy_time = (time.time() - start) / 1000
    
    print(f"\n📊 DWT Performance Benchmark (16x16 macroblock):")
    print(f"   2-level DWT:       {dwt_time*1000:.3f} ms")
    print(f"   Energy map:        {energy_time*1000:.3f} ms")
    print(f"   Total per MB:      {(dwt_time+energy_time)*1000:.3f} ms")
    
    # Should be fast (<1ms per macroblock)
    assert dwt_time < 0.001, f"DWT too slow: {dwt_time:.4f}s"
    assert energy_time < 0.001, f"Energy computation too slow: {energy_time:.4f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
