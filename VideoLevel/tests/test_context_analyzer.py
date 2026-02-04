"""
Unit tests for Context Analyzer

Tests:
- Texture analysis (Laplacian, std, combined)
- Motion analysis (optical flow, motion vectors)
- Context scoring
- Region classification
- Frame analysis
- Embedding suitability
"""

import unittest
import numpy as np
from src.zk_mv_stego.preprocessing.context_analyzer import ContextAnalyzer


class TestContextAnalyzerInitialization(unittest.TestCase):
    """Test context analyzer initialization"""
    
    def test_default_initialization(self):
        """Test default parameter values"""
        analyzer = ContextAnalyzer()
        
        self.assertEqual(analyzer.texture_weight, 0.6)
        self.assertEqual(analyzer.motion_weight, 0.4)
        self.assertEqual(analyzer.texture_threshold, 10.0)
        self.assertEqual(analyzer.motion_threshold, 2.0)
    
    def test_custom_weights(self):
        """Test custom weight initialization"""
        analyzer = ContextAnalyzer(
            texture_weight=0.7,
            motion_weight=0.3
        )
        
        self.assertEqual(analyzer.texture_weight, 0.7)
        self.assertEqual(analyzer.motion_weight, 0.3)
    
    def test_invalid_weights_sum(self):
        """Test weights must sum to 1.0"""
        with self.assertRaises(ValueError) as ctx:
            ContextAnalyzer(texture_weight=0.5, motion_weight=0.6)
        
        self.assertIn("sum to 1.0", str(ctx.exception))


class TestTextureAnalysis(unittest.TestCase):
    """Test texture analysis methods"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.analyzer = ContextAnalyzer()
    
    def test_smooth_block_low_texture(self):
        """Test smooth block has low texture score"""
        # Constant gray block
        smooth_block = np.ones((16, 16), dtype=np.uint8) * 128
        
        score = self.analyzer.analyze_texture(smooth_block, method='laplacian')
        
        # Smooth block should have very low score
        self.assertLess(score, 0.1)
    
    def test_textured_block_high_score(self):
        """Test textured block has high texture score"""
        # Checkerboard pattern (high texture)
        textured_block = np.zeros((16, 16), dtype=np.uint8)
        textured_block[::2, ::2] = 255
        textured_block[1::2, 1::2] = 255
        
        score = self.analyzer.analyze_texture(textured_block, method='laplacian')
        
        # Textured block should have high score
        self.assertGreater(score, 0.5)
    
    def test_edge_block_medium_texture(self):
        """Test edge block has medium texture score"""
        # Vertical edge
        edge_block = np.zeros((16, 16), dtype=np.uint8)
        edge_block[:, 8:] = 255
        
        score = self.analyzer.analyze_texture(edge_block, method='laplacian')
        
        # Edge should have medium-high score
        self.assertGreater(score, 0.2)
    
    def test_std_method(self):
        """Test standard deviation method"""
        # High variance block
        high_var_block = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
        
        score = self.analyzer.analyze_texture(high_var_block, method='std')
        
        # Random block should have high std
        self.assertGreater(score, 0.3)
    
    def test_combined_method(self):
        """Test combined texture analysis"""
        textured_block = np.zeros((16, 16), dtype=np.uint8)
        textured_block[::2, ::2] = 255
        textured_block[1::2, 1::2] = 255
        
        score = self.analyzer.analyze_texture(textured_block, method='combined')
        
        self.assertGreater(score, 0.5)
    
    def test_invalid_block_size(self):
        """Test error on invalid block size"""
        invalid_block = np.zeros((8, 8), dtype=np.uint8)
        
        with self.assertRaises(ValueError) as ctx:
            self.analyzer.analyze_texture(invalid_block)
        
        self.assertIn("16x16", str(ctx.exception))
    
    def test_unknown_method(self):
        """Test error on unknown method"""
        block = np.zeros((16, 16), dtype=np.uint8)
        
        with self.assertRaises(ValueError) as ctx:
            self.analyzer.analyze_texture(block, method='invalid')
        
        self.assertIn("Unknown method", str(ctx.exception))


class TestMotionAnalysis(unittest.TestCase):
    """Test motion analysis methods"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.analyzer = ContextAnalyzer()
    
    def test_motion_vector_input(self):
        """Test motion analysis with H.264 motion vector"""
        current_mb = np.zeros((16, 16), dtype=np.uint8)
        motion_vector = (8.0, 6.0)  # (dx, dy)
        
        score = self.analyzer.analyze_motion(
            current_mb,
            motion_vector=motion_vector
        )
        
        # sqrt(8^2 + 6^2) = 10 → 10/32 = 0.3125
        expected = 10.0 / 32.0
        self.assertAlmostEqual(score, expected, places=2)
    
    def test_large_motion_vector(self):
        """Test large motion vector is capped at 1.0"""
        current_mb = np.zeros((16, 16), dtype=np.uint8)
        motion_vector = (50.0, 50.0)  # Very large motion
        
        score = self.analyzer.analyze_motion(
            current_mb,
            motion_vector=motion_vector
        )
        
        # Should be capped at 1.0
        self.assertEqual(score, 1.0)
    
    def test_optical_flow_static(self):
        """Test optical flow with static blocks"""
        # Same block in both frames
        current = np.ones((16, 16), dtype=np.uint8) * 128
        previous = np.ones((16, 16), dtype=np.uint8) * 128
        
        score = self.analyzer.analyze_motion(
            current,
            previous_mb=previous
        )
        
        # Static blocks should have low motion
        self.assertLess(score, 0.3)
    
    def test_optical_flow_moving(self):
        """Test optical flow with moving pattern"""
        # Create shifted pattern
        previous = np.zeros((16, 16), dtype=np.uint8)
        previous[4:12, 4:12] = 255
        
        current = np.zeros((16, 16), dtype=np.uint8)
        current[6:14, 6:14] = 255  # Shifted by 2 pixels
        
        score = self.analyzer.analyze_motion(
            current,
            previous_mb=previous
        )
        
        # Should detect some motion
        self.assertGreater(score, 0.1)
    
    def test_no_motion_info_neutral_score(self):
        """Test returns neutral score when no motion info"""
        current = np.zeros((16, 16), dtype=np.uint8)
        
        score = self.analyzer.analyze_motion(current)
        
        # Should return neutral score
        self.assertEqual(score, 0.5)


class TestContextScoring(unittest.TestCase):
    """Test context score computation"""
    
    def test_compute_context_score(self):
        """Test weighted combination of texture and motion"""
        analyzer = ContextAnalyzer(texture_weight=0.6, motion_weight=0.4)
        
        texture_score = 0.8
        motion_score = 0.6
        
        context_score = analyzer.compute_context_score(texture_score, motion_score)
        
        # 0.6*0.8 + 0.4*0.6 = 0.48 + 0.24 = 0.72
        expected = 0.72
        self.assertAlmostEqual(context_score, expected, places=5)
    
    def test_high_texture_low_motion(self):
        """Test high texture compensates for low motion"""
        analyzer = ContextAnalyzer()
        
        context_score = analyzer.compute_context_score(
            texture_score=0.9,
            motion_score=0.2
        )
        
        # 0.6*0.9 + 0.4*0.2 = 0.54 + 0.08 = 0.62
        self.assertGreater(context_score, 0.6)
    
    def test_low_texture_high_motion(self):
        """Test high motion compensates for low texture"""
        analyzer = ContextAnalyzer()
        
        context_score = analyzer.compute_context_score(
            texture_score=0.2,
            motion_score=0.9
        )
        
        # 0.6*0.2 + 0.4*0.9 = 0.12 + 0.36 = 0.48
        self.assertGreater(context_score, 0.4)


class TestRegionClassification(unittest.TestCase):
    """Test region classification"""
    
    def setUp(self):
        """Initialize analyzer"""
        self.analyzer = ContextAnalyzer()
    
    def test_high_complexity_high_texture(self):
        """Test high texture → high complexity"""
        classification = self.analyzer.classify_region(
            texture_score=0.8,
            motion_score=0.5
        )
        
        self.assertEqual(classification, 'high-complexity')
    
    def test_high_complexity_high_motion(self):
        """Test high motion → high complexity"""
        classification = self.analyzer.classify_region(
            texture_score=0.5,
            motion_score=0.8
        )
        
        self.assertEqual(classification, 'high-complexity')
    
    def test_medium_complexity(self):
        """Test medium texture + motion → medium complexity"""
        classification = self.analyzer.classify_region(
            texture_score=0.5,
            motion_score=0.5
        )
        
        self.assertEqual(classification, 'medium-complexity')
    
    def test_smooth_static(self):
        """Test low texture + motion → smooth-static"""
        classification = self.analyzer.classify_region(
            texture_score=0.2,
            motion_score=0.2
        )
        
        self.assertEqual(classification, 'smooth-static')
    
    def test_low_complexity(self):
        """Test borderline → low-complexity"""
        classification = self.analyzer.classify_region(
            texture_score=0.35,
            motion_score=0.35
        )
        
        self.assertEqual(classification, 'low-complexity')


class TestEmbeddingSuitability(unittest.TestCase):
    """Test embedding suitability assessment"""
    
    def setUp(self):
        """Initialize analyzer"""
        self.analyzer = ContextAnalyzer()
    
    def test_excellent_quality_textured_block(self):
        """Test textured block gets excellent quality"""
        # Checkerboard pattern
        textured = np.zeros((16, 16), dtype=np.uint8)
        textured[::2, ::2] = 255
        textured[1::2, 1::2] = 255
        
        result = self.analyzer.get_embedding_suitability(textured)
        
        self.assertIn('texture_score', result)
        self.assertIn('motion_score', result)
        self.assertIn('context_score', result)
        self.assertIn('classification', result)
        self.assertIn('embedding_quality', result)
        
        # High texture should give excellent quality
        self.assertGreater(result['texture_score'], 0.5)
        self.assertIn(result['embedding_quality'], ['good', 'excellent'])
    
    def test_poor_quality_smooth_block(self):
        """Test smooth block gets poor quality"""
        smooth = np.ones((16, 16), dtype=np.uint8) * 128
        
        result = self.analyzer.get_embedding_suitability(smooth)
        
        # Smooth block should have low score
        self.assertLess(result['texture_score'], 0.3)
        self.assertEqual(result['embedding_quality'], 'poor')
    
    def test_with_motion_vector(self):
        """Test suitability with motion vector"""
        block = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
        mv = (10.0, 10.0)
        
        result = self.analyzer.get_embedding_suitability(
            block,
            motion_vector=mv
        )
        
        # Motion vector should be used
        expected_motion = np.sqrt(10**2 + 10**2) / 32.0
        self.assertAlmostEqual(result['motion_score'], expected_motion, places=2)


class TestFrameAnalysis(unittest.TestCase):
    """Test full frame analysis"""
    
    def setUp(self):
        """Initialize analyzer"""
        self.analyzer = ContextAnalyzer()
    
    def test_analyze_small_frame(self):
        """Test analyzing 32x32 frame (2x2 macroblocks)"""
        luma = np.random.randint(0, 256, (32, 32), dtype=np.uint8)
        
        results = self.analyzer.analyze_frame(luma)
        
        # Should have 4 macroblocks (2x2)
        self.assertEqual(len(results), 4)
        
        # Check all indices present
        for i in range(4):
            self.assertIn(i, results)
            self.assertIn('texture_score', results[i])
            self.assertIn('context_score', results[i])
    
    def test_analyze_with_previous_frame(self):
        """Test frame analysis with previous frame"""
        current = np.random.randint(0, 256, (32, 32), dtype=np.uint8)
        previous = np.random.randint(0, 256, (32, 32), dtype=np.uint8)
        
        results = self.analyzer.analyze_frame(current, previous_luma=previous)
        
        # All macroblocks should have motion scores
        for mb_idx, data in results.items():
            self.assertIsNotNone(data['motion_score'])
            self.assertGreater(data['motion_score'], 0.0)
    
    def test_analyze_with_motion_vectors(self):
        """Test frame analysis with motion vectors"""
        luma = np.random.randint(0, 256, (32, 32), dtype=np.uint8)
        motion_vectors = {
            0: (5.0, 3.0),
            1: (2.0, 8.0),
            2: (0.0, 0.0),
            3: (10.0, 10.0)
        }
        
        results = self.analyzer.analyze_frame(luma, motion_vectors=motion_vectors)
        
        # Check motion vectors were used
        for mb_idx in range(4):
            mv = motion_vectors[mb_idx]
            expected = min(np.sqrt(mv[0]**2 + mv[1]**2) / 32.0, 1.0)
            self.assertAlmostEqual(
                results[mb_idx]['motion_score'],
                expected,
                places=2
            )
    
    def test_invalid_frame_size(self):
        """Test error on non-16-multiple frame size"""
        invalid_luma = np.zeros((30, 30), dtype=np.uint8)
        
        with self.assertRaises(ValueError) as ctx:
            self.analyzer.analyze_frame(invalid_luma)
        
        self.assertIn("multiple of 16", str(ctx.exception))


class TestBestMacroblocks(unittest.TestCase):
    """Test best macroblock selection"""
    
    def setUp(self):
        """Create test frame analysis"""
        self.analyzer = ContextAnalyzer()
        
        # Mock analysis results
        self.analysis = {
            0: {'context_score': 0.9, 'embedding_quality': 'excellent'},
            1: {'context_score': 0.7, 'embedding_quality': 'good'},
            2: {'context_score': 0.5, 'embedding_quality': 'good'},
            3: {'context_score': 0.3, 'embedding_quality': 'fair'},
            4: {'context_score': 0.2, 'embedding_quality': 'poor'},
            5: {'context_score': 0.8, 'embedding_quality': 'excellent'},
        }
    
    def test_get_top_n_macroblocks(self):
        """Test getting top N macroblocks"""
        best = self.analyzer.get_best_macroblocks(self.analysis, top_n=3)
        
        # Should return top 3 by score
        self.assertEqual(len(best), 3)
        self.assertEqual(best[0], 0)  # 0.9
        self.assertEqual(best[1], 5)  # 0.8
        self.assertEqual(best[2], 1)  # 0.7
    
    def test_filter_by_min_quality(self):
        """Test filtering by minimum quality"""
        best = self.analyzer.get_best_macroblocks(
            self.analysis,
            top_n=10,
            min_quality='good'
        )
        
        # Should exclude 'fair' and 'poor'
        self.assertEqual(len(best), 4)  # 0, 1, 2, 5
        self.assertNotIn(3, best)  # fair
        self.assertNotIn(4, best)  # poor


class TestCachingAndUtilities(unittest.TestCase):
    """Test caching and utility methods"""
    
    def test_clear_cache(self):
        """Test cache clearing"""
        analyzer = ContextAnalyzer()
        
        # Populate cache (manually for testing)
        analyzer._texture_cache[0] = 0.5
        analyzer._motion_cache[0] = 0.3
        
        self.assertEqual(len(analyzer._texture_cache), 1)
        self.assertEqual(len(analyzer._motion_cache), 1)
        
        # Clear cache
        analyzer.clear_cache()
        
        self.assertEqual(len(analyzer._texture_cache), 0)
        self.assertEqual(len(analyzer._motion_cache), 0)


if __name__ == '__main__':
    unittest.main()
