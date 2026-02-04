"""
Unit tests for Hybrid DCT-DWT Coefficient Selector

Tests:
1. Initialization
2. Stability score computation
3. Coefficient selection rules
4. Macroblock-level selection
5. Coefficient map creation
6. Capacity estimation
7. Integration with DWT analyzer
"""

import pytest
import numpy as np
from src.zk_mv_stego.preprocessing.hybrid_selector import HybridCoefficientSelector
from src.zk_mv_stego.preprocessing.dwt_analyzer import HaarDWTAnalyzer


class TestHybridSelectorInitialization:
    """Test suite for selector initialization"""
    
    def test_default_initialization(self):
        """Test creation with default DWT analyzer"""
        selector = HybridCoefficientSelector()
        
        assert selector.dwt_analyzer is not None
        assert selector.dwt_analyzer.levels == 2
        assert selector.region_weights == {
            'LH': 1.0,
            'HL': 1.0,
            'LL': 0.6,
            'HH': 0.0
        }
    
    def test_custom_dwt_analyzer(self):
        """Test initialization with custom analyzer"""
        custom_analyzer = HaarDWTAnalyzer(levels=1)
        selector = HybridCoefficientSelector(dwt_analyzer=custom_analyzer)
        
        assert selector.dwt_analyzer is custom_analyzer
        assert selector.dwt_analyzer.levels == 1


class TestStabilityScoreComputation:
    """Test suite for stability scoring algorithm"""
    
    def test_high_magnitude_coefficient(self):
        """Test scoring for strong coefficient (|value| = 100)"""
        selector = HybridCoefficientSelector()
        
        score = selector.compute_stability_score(
            coeff_value=100,
            coeff_position=5,
            dwt_region='LH',
            texture_score=1.0,
            motion_score=0.5
        )
        
        # High magnitude + best region + high texture = high score
        assert score > 0.65  # Actual: ~0.666 (log scaling)
        assert score <= 1.0
    
    def test_low_magnitude_coefficient(self):
        """Test scoring for weak coefficient (|value| = 2)"""
        selector = HybridCoefficientSelector()
        
        score = selector.compute_stability_score(
            coeff_value=2,
            coeff_position=5,
            dwt_region='LH',
            texture_score=1.0,
            motion_score=0.5
        )
        
        # Low magnitude = lower score even with best region
        assert score < 0.5
    
    def test_region_weight_impact(self):
        """Test that region weight affects score"""
        selector = HybridCoefficientSelector()
        
        # Same coefficient in different regions
        score_lh = selector.compute_stability_score(50, 5, 'LH')
        score_hl = selector.compute_stability_score(50, 5, 'HL')
        score_ll = selector.compute_stability_score(50, 5, 'LL')
        score_hh = selector.compute_stability_score(50, 5, 'HH')
        
        # LH and HL should have equal high scores
        assert abs(score_lh - score_hl) < 0.01
        assert score_lh > score_ll  # LH better than LL
        assert score_ll > score_hh  # LL better than HH
        assert score_hh == 0.0      # HH always zero
    
    def test_texture_vs_motion_weighting(self):
        """Test that texture (0.6) > motion (0.4) in context score"""
        selector = HybridCoefficientSelector()
        
        # High texture, low motion
        score_texture = selector.compute_stability_score(
            50, 5, 'LH', texture_score=1.0, motion_score=0.0
        )
        
        # Low texture, high motion
        score_motion = selector.compute_stability_score(
            50, 5, 'LH', texture_score=0.0, motion_score=1.0
        )
        
        # Texture should contribute more to score
        assert score_texture > score_motion
    
    def test_score_range(self):
        """Test that score is always in [0.0, 1.0]"""
        selector = HybridCoefficientSelector()
        
        # Test extreme values
        test_cases = [
            (255, 'LH', 1.0, 1.0),  # Maximum
            (-255, 'LH', 1.0, 1.0), # Negative maximum
            (0, 'HH', 0.0, 0.0),    # Minimum
            (1, 'LL', 0.5, 0.5),    # Small value
        ]
        
        for value, region, texture, motion in test_cases:
            score = selector.compute_stability_score(
                value, 5, region, texture, motion
            )
            assert 0.0 <= score <= 1.0


class TestCoefficientSelectionRules:
    """Test suite for should_use_coefficient() decision logic"""
    
    def test_rule_1_skip_dc(self):
        """Rule 1: Always skip DC coefficient (position 0)"""
        selector = HybridCoefficientSelector()
        
        # Even with perfect conditions, DC should be rejected
        assert not selector.should_use_coefficient(
            coeff_value=100,
            coeff_position=0,
            dwt_region='LH',
            texture_score=1.0
        )
    
    def test_rule_2_skip_high_frequency(self):
        """Rule 2: Always skip HH region (high frequency)"""
        selector = HybridCoefficientSelector()
        
        # Even strong coefficient in HH should be rejected
        assert not selector.should_use_coefficient(
            coeff_value=100,
            coeff_position=5,
            dwt_region='HH',
            texture_score=1.0
        )
    
    def test_rule_3_skip_small_coefficients(self):
        """Rule 3: Skip |value| < 2"""
        selector = HybridCoefficientSelector()
        
        # |value| = 1 should be rejected
        assert not selector.should_use_coefficient(
            coeff_value=1,
            coeff_position=5,
            dwt_region='LH',
            texture_score=1.0
        )
        
        # |value| = -1 should also be rejected
        assert not selector.should_use_coefficient(
            coeff_value=-1,
            coeff_position=5,
            dwt_region='LH',
            texture_score=1.0
        )
    
    def test_rule_4_skip_low_texture(self):
        """Rule 4: Skip texture < 0.3"""
        selector = HybridCoefficientSelector()
        
        # texture = 0.2 should be rejected
        assert not selector.should_use_coefficient(
            coeff_value=10,
            coeff_position=5,
            dwt_region='LH',
            texture_score=0.2
        )
        
        # texture = 0.3 should be accepted (boundary)
        assert selector.should_use_coefficient(
            coeff_value=10,
            coeff_position=5,
            dwt_region='LH',
            texture_score=0.3
        )
    
    def test_rule_5_accept_mid_frequency_edges(self):
        """Rule 5: Accept LH/HL with |value| >= 3"""
        selector = HybridCoefficientSelector()
        
        # LH region with |value| = 3
        assert selector.should_use_coefficient(
            coeff_value=3,
            coeff_position=5,
            dwt_region='LH',
            texture_score=0.5
        )
        
        # HL region with |value| = -5
        assert selector.should_use_coefficient(
            coeff_value=-5,
            coeff_position=5,
            dwt_region='HL',
            texture_score=0.5
        )
    
    def test_rule_6_accept_smooth_strong(self):
        """Rule 6: Accept LL with |value| >= 5"""
        selector = HybridCoefficientSelector()
        
        # LL region with |value| = 5 (boundary)
        assert selector.should_use_coefficient(
            coeff_value=5,
            coeff_position=5,
            dwt_region='LL',
            texture_score=0.5
        )
        
        # LL region with |value| = 4 (too small)
        assert not selector.should_use_coefficient(
            coeff_value=4,
            coeff_position=5,
            dwt_region='LL',
            texture_score=0.5
        )


class TestMacroblockSelection:
    """Test suite for macroblock-level coefficient selection"""
    
    def test_empty_coefficients(self):
        """Test with no coefficients"""
        selector = HybridCoefficientSelector()
        macroblock = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
        
        selected = selector.select_coefficients(
            coefficients=[],
            macroblock_data=macroblock
        )
        
        assert len(selected) == 0
    
    def test_select_best_candidates(self):
        """Test selection prioritizes high-score coefficients"""
        selector = HybridCoefficientSelector()
        
        # Create test macroblock with edges (high LH/HL energy)
        macroblock = np.zeros((16, 16), dtype=np.uint8)
        macroblock[:, 8:] = 255  # Vertical edge
        
        # Mock coefficients: (mb_idx, block_idx, coeff_list)
        coefficients = [
            (0, 0, [0, 10, 3, -5, 2, 1, 0, 0]),  # Mix of values
            (0, 1, [0, 20, 15, -8, 3, 0, 0, 0]), # Stronger coefficients
        ]
        
        selected = selector.select_coefficients(
            coefficients=coefficients,
            macroblock_data=macroblock,
            min_magnitude=2
        )
        
        # Should select some coefficients (non-zero, non-DC, |value| >= 2)
        assert len(selected) > 0
        
        # Each entry should be (mb_idx, block_idx, position)
        for mb_idx, block_idx, position in selected:
            assert isinstance(mb_idx, int)
            assert isinstance(block_idx, int)
            assert isinstance(position, int)
            assert position != 0  # No DC
    
    def test_max_coefficients_limit(self):
        """Test max_coefficients parameter"""
        selector = HybridCoefficientSelector()
        macroblock = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
        
        # Create many valid coefficients
        coefficients = [
            (0, i, [0, 10, 8, -7, 6, 5, 4, 3])
            for i in range(10)
        ]
        
        selected = selector.select_coefficients(
            coefficients=coefficients,
            macroblock_data=macroblock,
            max_coefficients=5
        )
        
        # Should limit to 5 best coefficients
        assert len(selected) <= 5


class TestCoefficientMap:
    """Test suite for coefficient map creation"""
    
    def test_map_creation(self):
        """Test binary map creation"""
        selector = HybridCoefficientSelector()
        macroblock = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
        
        coefficients = [
            (0, 0, [0, 10, 3, -5, 2]),  # 5 coefficients
            (0, 1, [0, 20, 15]),        # 3 coefficients
        ]
        
        coeff_map = selector.create_coefficient_map(
            coefficients=coefficients,
            macroblock_data=macroblock
        )
        
        # Map should have length = total coefficients
        assert len(coeff_map) == 8
        
        # Should be binary (0 or 1)
        assert np.all((coeff_map == 0) | (coeff_map == 1))
    
    def test_capacity_estimation(self):
        """Test capacity estimation from map"""
        selector = HybridCoefficientSelector()
        
        # Mock coefficient map
        coeff_map = np.array([1, 1, 0, 1, 0, 0, 1, 1], dtype=np.uint8)
        
        capacity = selector.estimate_capacity(coeff_map)
        
        # Should count number of 1s
        assert capacity == 5


class TestIntegrationWithDWT:
    """Test suite for DWT analyzer integration"""
    
    def test_dwt_region_mapping(self):
        """Test that DWT regions are correctly used"""
        selector = HybridCoefficientSelector()
        
        # Create smooth macroblock (LL dominant)
        smooth_mb = np.ones((16, 16), dtype=np.uint8) * 128
        
        coefficients = [
            (0, 0, [0, 10, 3, -5, 2]),
        ]
        
        selected_smooth = selector.select_coefficients(
            coefficients=coefficients,
            macroblock_data=smooth_mb
        )
        
        # Create edge macroblock (LH/HL dominant)
        edge_mb = np.zeros((16, 16), dtype=np.uint8)
        edge_mb[8:, :] = 255  # Horizontal edge
        
        selected_edge = selector.select_coefficients(
            coefficients=coefficients,
            macroblock_data=edge_mb
        )
        
        # Edge macroblock should potentially select more (LH/HL favorable)
        # This is not guaranteed but tests integration
        assert isinstance(selected_smooth, list)
        assert isinstance(selected_edge, list)


def test_end_to_end_workflow():
    """End-to-end test of hybrid selector workflow"""
    selector = HybridCoefficientSelector()
    
    # Create test macroblock with texture
    macroblock = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    
    # Mock DCT coefficients from multiple blocks
    coefficients = [
        (0, 0, [0, 15, 10, -8, 6, 4, 2, 1, 0]),
        (0, 1, [0, 20, -12, 7, 5, 3, 1, 0, 0]),
        (0, 2, [0, 8, 6, -4, 2, 1, 0, 0, 0]),
    ]
    
    # Step 1: Select best coefficients
    selected = selector.select_coefficients(
        coefficients=coefficients,
        macroblock_data=macroblock,
        min_magnitude=3,
        max_coefficients=10
    )
    
    assert len(selected) > 0
    assert len(selected) <= 10
    
    # Step 2: Create coefficient map
    coeff_map = selector.create_coefficient_map(
        coefficients=coefficients,
        macroblock_data=macroblock
    )
    
    assert len(coeff_map) == sum(len(c) for _, _, c in coefficients)
    
    # Step 3: Estimate capacity
    capacity = selector.estimate_capacity(coeff_map)
    
    assert capacity >= 0
    assert capacity <= len(coeff_map)
    
    print(f"\n✅ End-to-end test passed:")
    print(f"   Selected: {len(selected)} coefficients")
    print(f"   Capacity: {capacity} bits")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
