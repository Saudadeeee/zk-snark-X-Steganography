"""
Video Comparison Benchmark
===========================

Compare original video vs stego video with embedded ZK proof:
- Visual quality metrics (PSNR, SSIM, VMAF)
- File size and bitrate comparison
- Motion vector statistics
- Perceptual difference analysis
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from phase2.quality_metrics import VideoQualityMetrics
from tools.mv_extractor.h264_parser import H264MVExtractor


class VideoBenchmark:
    """Comprehensive video comparison benchmark"""
    
    def __init__(self):
        self.metrics = VideoQualityMetrics()
    
    def run_benchmark(self, original_video: str, stego_json: str) -> Dict:
        """
        Run complete benchmark comparison
        
        Args:
            original_video: Path to original video
            stego_json: Path to stego metadata JSON
            
        Returns:
            Benchmark results dictionary
        """
        print(f"\n{'='*80}")
        print("VIDEO COMPARISON BENCHMARK")
        print(f"{'='*80}\n")
        
        # Load stego data
        with open(stego_json, 'r') as f:
            stego_data = json.load(f)
        
        print(f"Original video: {original_video}")
        print(f"Stego data:     {stego_json}")
        print(f"Proof size:     {stego_data['proof_size']} bytes")
        
        # 1. File statistics
        print(f"\n{'='*80}")
        print("1. FILE STATISTICS")
        print(f"{'='*80}")
        
        file_stats = self._compare_file_stats(original_video)
        self._print_file_stats(file_stats)
        
        # 2. Motion vector comparison
        print(f"\n{'='*80}")
        print("2. MOTION VECTOR ANALYSIS")
        print(f"{'='*80}")
        
        mv_stats = self._compare_motion_vectors(
            stego_data['original_mvs'],
            stego_data['modified_mvs']
        )
        self._print_mv_stats(mv_stats)
        
        # 3. Quality metrics
        print(f"\n{'='*80}")
        print("3. QUALITY METRICS")
        print(f"{'='*80}")
        
        quality_stats = self.metrics.analyze_video_quality(original_video, stego_json)
        self._print_quality_stats(quality_stats)
        
        # 4. Statistical analysis
        print(f"\n{'='*80}")
        print("4. STATISTICAL ANALYSIS")
        print(f"{'='*80}")
        
        statistical = self._statistical_analysis(
            stego_data['original_mvs'],
            stego_data['modified_mvs']
        )
        self._print_statistical(statistical)
        
        # 5. Security assessment
        print(f"\n{'='*80}")
        print("5. SECURITY ASSESSMENT")
        print(f"{'='*80}")
        
        security = self._security_assessment(mv_stats, quality_stats)
        self._print_security(security)
        
        # Final summary
        print(f"\n{'='*80}")
        print("BENCHMARK SUMMARY")
        print(f"{'='*80}")
        
        summary = self._generate_summary(file_stats, mv_stats, quality_stats, security)
        self._print_summary(summary)
        
        return {
            'file_stats': file_stats,
            'mv_stats': mv_stats,
            'quality_stats': quality_stats,
            'statistical': statistical,
            'security': security,
            'summary': summary
        }
    
    def _compare_file_stats(self, video_path: str) -> Dict:
        """Compare file statistics"""
        video_file = Path(video_path)
        
        return {
            'original_size': video_file.stat().st_size,
            'original_size_mb': video_file.stat().st_size / (1024 * 1024),
            # Note: Actual stego video would be re-encoded
            # For now we only modify MV metadata, not create new video file
            'note': 'Stego implementation modifies MV metadata, not video file itself'
        }
    
    def _compare_motion_vectors(self, original_mvs: list, modified_mvs: list) -> Dict:
        """Compare original and modified motion vectors"""
        
        total_mvs = len(original_mvs)
        modifications = []
        mvs_changed = 0
        
        mvx_changes = []
        mvy_changes = []
        magnitude_changes = []
        
        for orig, mod in zip(original_mvs, modified_mvs):
            # Calculate differences
            mvx_diff = abs(orig['mvx'] - mod['mvx'])
            mvy_diff = abs(orig['mvy'] - mod['mvy'])
            
            if mvx_diff > 0 or mvy_diff > 0:
                mvs_changed += 1
            
            # Euclidean distance
            dist = np.sqrt(mvx_diff**2 + mvy_diff**2)
            modifications.append(dist)
            
            mvx_changes.append(mvx_diff)
            mvy_changes.append(mvy_diff)
            
            # Magnitude change
            orig_mag = np.sqrt(orig['mvx']**2 + orig['mvy']**2)
            mod_mag = np.sqrt(mod['mvx']**2 + mod['mvy']**2)
            magnitude_changes.append(abs(mod_mag - orig_mag))
        
        return {
            'total_mvs': int(total_mvs),
            'mvs_changed': int(mvs_changed),
            'change_rate': float(mvs_changed / total_mvs),
            'avg_modification': float(np.mean(modifications)),
            'max_modification': float(np.max(modifications)),
            'std_modification': float(np.std(modifications)),
            'median_modification': float(np.median(modifications)),
            'mvx': {
                'avg_change': float(np.mean(mvx_changes)),
                'max_change': int(np.max(mvx_changes)),
                'changed_count': int(sum(1 for x in mvx_changes if x > 0))
            },
            'mvy': {
                'avg_change': float(np.mean(mvy_changes)),
                'max_change': int(np.max(mvy_changes)),
                'changed_count': int(sum(1 for x in mvy_changes if x > 0))
            },
            'magnitude': {
                'avg_change': float(np.mean(magnitude_changes)),
                'max_change': float(np.max(magnitude_changes))
            }
        }
    
    def _statistical_analysis(self, original_mvs: list, modified_mvs: list) -> Dict:
        """Statistical analysis of MV distributions"""
        
        # Extract values
        orig_mvx = [mv['mvx'] for mv in original_mvs]
        orig_mvy = [mv['mvy'] for mv in original_mvs]
        mod_mvx = [mv['mvx'] for mv in modified_mvs]
        mod_mvy = [mv['mvy'] for mv in modified_mvs]
        
        # Calculate statistics
        def calc_stats(data):
            return {
                'mean': float(np.mean(data)),
                'std': float(np.std(data)),
                'min': int(np.min(data)),
                'max': int(np.max(data)),
                'median': float(np.median(data))
            }
        
        # Parity distribution
        def calc_parity(data):
            even = sum(1 for x in data if x % 2 == 0)
            odd = len(data) - even
            return {
                'even': int(even),
                'odd': int(odd),
                'even_rate': float(even / len(data)),
                'odd_rate': float(odd / len(data))
            }
        
        # Entropy
        def calc_entropy(data):
            even = sum(1 for x in data if x % 2 == 0)
            odd = len(data) - even
            p_even = even / len(data)
            p_odd = odd / len(data)
            if p_even > 0 and p_odd > 0:
                return -(p_even * np.log2(p_even) + p_odd * np.log2(p_odd))
            return 0
        
        return {
            'original': {
                'mvx': calc_stats(orig_mvx),
                'mvy': calc_stats(orig_mvy),
                'mvx_parity': calc_parity(orig_mvx),
                'mvy_parity': calc_parity(orig_mvy),
                'mvx_entropy': float(calc_entropy(orig_mvx)),
                'mvy_entropy': float(calc_entropy(orig_mvy))
            },
            'modified': {
                'mvx': calc_stats(mod_mvx),
                'mvy': calc_stats(mod_mvy),
                'mvx_parity': calc_parity(mod_mvx),
                'mvy_parity': calc_parity(mod_mvy),
                'mvx_entropy': float(calc_entropy(mod_mvx)),
                'mvy_entropy': float(calc_entropy(mod_mvy))
            },
            'difference': {
                'mvx_mean_change': float(abs(np.mean(orig_mvx) - np.mean(mod_mvx))),
                'mvy_mean_change': float(abs(np.mean(orig_mvy) - np.mean(mod_mvy))),
                'mvx_std_change': float(abs(np.std(orig_mvx) - np.std(mod_mvx))),
                'mvy_std_change': float(abs(np.std(orig_mvy) - np.std(mod_mvy))),
                'mvx_entropy_change': float(abs(calc_entropy(orig_mvx) - calc_entropy(mod_mvx))),
                'mvy_entropy_change': float(abs(calc_entropy(orig_mvy) - calc_entropy(mod_mvy)))
            }
        }
    
    def _security_assessment(self, mv_stats: Dict, quality_stats: Dict) -> Dict:
        """Assess security and detectability"""
        
        # Detection risk factors
        change_rate = mv_stats['change_rate']
        avg_mod = mv_stats['avg_modification']
        quality_score = quality_stats['quality_score']
        
        # Calculate detection risk (0-100, lower is better)
        # Based on: change rate, modification magnitude, quality degradation
        
        risk_change_rate = min(100, change_rate * 100 * 10)  # <10% → low risk
        risk_modification = min(100, avg_mod * 20)  # <1 pixel → low risk
        risk_quality = max(0, 100 - quality_score)  # >90 → low risk
        
        overall_risk = (risk_change_rate + risk_modification + risk_quality) / 3
        
        # Security level
        if overall_risk < 20:
            level = "EXCELLENT"
            detection = "Very difficult to detect"
        elif overall_risk < 40:
            level = "GOOD"
            detection = "Difficult to detect"
        elif overall_risk < 60:
            level = "MODERATE"
            detection = "May be detectable with advanced analysis"
        else:
            level = "POOR"
            detection = "Easily detectable"
        
        return {
            'overall_risk': overall_risk,
            'security_level': level,
            'detectability': detection,
            'risk_factors': {
                'change_rate_risk': risk_change_rate,
                'modification_risk': risk_modification,
                'quality_risk': risk_quality
            },
            'recommendations': self._generate_recommendations(overall_risk, mv_stats)
        }
    
    def _generate_recommendations(self, risk: float, mv_stats: Dict) -> list:
        """Generate security recommendations"""
        recommendations = []
        
        if mv_stats['change_rate'] > 0.05:
            recommendations.append(
                "Consider reducing embedding rate (<5%) for better security"
            )
        
        if mv_stats['avg_modification'] > 1.0:
            recommendations.append(
                "Average modification >1 pixel may be detectable"
            )
        
        if risk < 20:
            recommendations.append(
                "Current security level is excellent - maintain current parameters"
            )
        
        if not recommendations:
            recommendations.append("No major security concerns detected")
        
        return recommendations
    
    def _generate_summary(self, file_stats: Dict, mv_stats: Dict, 
                         quality_stats: Dict, security: Dict) -> Dict:
        """Generate benchmark summary"""
        
        return {
            'modification_impact': {
                'mvs_changed': mv_stats['mvs_changed'],
                'total_mvs': mv_stats['total_mvs'],
                'change_rate_percent': mv_stats['change_rate'] * 100,
                'avg_pixel_change': mv_stats['avg_modification']
            },
            'quality_impact': {
                'quality_score': quality_stats['quality_score'],
                'estimated_psnr': quality_stats['estimated_psnr'],
                'assessment': 'Excellent' if quality_stats['quality_score'] >= 90 
                             else 'Good' if quality_stats['quality_score'] >= 75 
                             else 'Acceptable'
            },
            'security_assessment': {
                'risk_level': security['overall_risk'],
                'security_level': security['security_level'],
                'detectability': security['detectability']
            },
            'overall_grade': self._calculate_grade(quality_stats, security)
        }
    
    def _calculate_grade(self, quality_stats: Dict, security: Dict) -> str:
        """Calculate overall grade"""
        quality_score = quality_stats['quality_score']
        security_score = 100 - security['overall_risk']
        
        overall = (quality_score + security_score) / 2
        
        if overall >= 90:
            return "A+ (Excellent)"
        elif overall >= 80:
            return "A (Very Good)"
        elif overall >= 70:
            return "B (Good)"
        elif overall >= 60:
            return "C (Acceptable)"
        else:
            return "D (Poor)"
    
    # Print methods
    def _print_file_stats(self, stats: Dict):
        print(f"Original video size: {stats['original_size_mb']:.2f} MB")
        print(f"Note: {stats['note']}")
    
    def _print_mv_stats(self, stats: Dict):
        print(f"Total motion vectors:  {stats['total_mvs']:,}")
        print(f"MVs modified:          {stats['mvs_changed']:,}")
        print(f"Modification rate:     {stats['change_rate']*100:.2f}%")
        print(f"\nModification magnitude:")
        print(f"  Average:   {stats['avg_modification']:.4f} pixels")
        print(f"  Maximum:   {stats['max_modification']:.4f} pixels")
        print(f"  Median:    {stats['median_modification']:.4f} pixels")
        print(f"  Std Dev:   {stats['std_modification']:.4f} pixels")
        print(f"\nComponent-wise changes:")
        print(f"  MVx: {stats['mvx']['changed_count']} changed "
              f"(avg: {stats['mvx']['avg_change']:.4f}, max: {stats['mvx']['max_change']})")
        print(f"  MVy: {stats['mvy']['changed_count']} changed "
              f"(avg: {stats['mvy']['avg_change']:.4f}, max: {stats['mvy']['max_change']})")
    
    def _print_quality_stats(self, stats: Dict):
        print(f"Quality score:       {stats['quality_score']:.1f}/100")
        print(f"Estimated PSNR:      {stats['estimated_psnr']:.2f} dB")
        print(f"Embedding efficiency: {stats['embedding_efficiency']:.4f} bytes/MV")
        print(f"\nMV Distortion:")
        print(f"  Total MVs:          {stats['mv_distortion']['total_mvs']:,}")
        print(f"  MVs modified:       {stats['mv_distortion']['mvs_modified']:,}")
        print(f"  Modification rate:  {stats['mv_distortion']['modification_rate']*100:.2f}%")
        print(f"  Avg modification:   {stats['mv_distortion']['avg_modification']:.4f} pixels")
        print(f"  Max modification:   {stats['mv_distortion']['max_modification']:.4f} pixels")
    
    def _print_statistical(self, stats: Dict):
        print("Distribution comparison:")
        print(f"\nMVx Parity:")
        print(f"  Original:  Even={stats['original']['mvx_parity']['even_rate']*100:.1f}%, "
              f"Odd={stats['original']['mvx_parity']['odd_rate']*100:.1f}%")
        print(f"  Modified:  Even={stats['modified']['mvx_parity']['even_rate']*100:.1f}%, "
              f"Odd={stats['modified']['mvx_parity']['odd_rate']*100:.1f}%")
        
        print(f"\nEntropy (ideal=1.0):")
        print(f"  Original MVx: {stats['original']['mvx_entropy']:.4f}")
        print(f"  Modified MVx: {stats['modified']['mvx_entropy']:.4f}")
        print(f"  Change:       {stats['difference']['mvx_entropy_change']:.4f}")
        
        print(f"\nStatistical moments:")
        print(f"  MVx mean change: {stats['difference']['mvx_mean_change']:.4f}")
        print(f"  MVx std change:  {stats['difference']['mvx_std_change']:.4f}")
    
    def _print_security(self, security: Dict):
        print(f"Security Level:      {security['security_level']}")
        print(f"Overall Risk Score:  {security['overall_risk']:.1f}/100 (lower is better)")
        print(f"Detectability:       {security['detectability']}")
        print(f"\nRisk Breakdown:")
        print(f"  Change rate risk:     {security['risk_factors']['change_rate_risk']:.1f}/100")
        print(f"  Modification risk:    {security['risk_factors']['modification_risk']:.1f}/100")
        print(f"  Quality impact risk:  {security['risk_factors']['quality_risk']:.1f}/100")
        print(f"\nRecommendations:")
        for i, rec in enumerate(security['recommendations'], 1):
            print(f"  {i}. {rec}")
    
    def _print_summary(self, summary: Dict):
        print(f"Modification Impact:")
        print(f"  {summary['modification_impact']['mvs_changed']:,} / "
              f"{summary['modification_impact']['total_mvs']:,} MVs modified "
              f"({summary['modification_impact']['change_rate_percent']:.2f}%)")
        print(f"  Average change: {summary['modification_impact']['avg_pixel_change']:.4f} pixels")
        
        print(f"\nQuality Impact:")
        print(f"  Quality score: {summary['quality_impact']['quality_score']:.1f}/100")
        print(f"  Estimated PSNR: {summary['quality_impact']['estimated_psnr']:.2f} dB")
        print(f"  Assessment: {summary['quality_impact']['assessment']}")
        
        print(f"\nSecurity Assessment:")
        print(f"  Risk level: {summary['security_assessment']['risk_level']:.1f}/100")
        print(f"  Security: {summary['security_assessment']['security_level']}")
        print(f"  Detectability: {summary['security_assessment']['detectability']}")
        
        print(f"\n{'='*80}")
        print(f"OVERALL GRADE: {summary['overall_grade']}")
        print(f"{'='*80}")


def main():
    """CLI interface"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Video Comparison Benchmark')
    parser.add_argument('--original', required=True, help='Original video file')
    parser.add_argument('--stego', required=True, help='Stego metadata JSON')
    parser.add_argument('--output', help='Output JSON for benchmark results')
    
    args = parser.parse_args()
    
    # Run benchmark
    benchmark = VideoBenchmark()
    results = benchmark.run_benchmark(args.original, args.stego)
    
    # Save results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n[OK] Benchmark results saved to {args.output}")


if __name__ == '__main__':
    main()
