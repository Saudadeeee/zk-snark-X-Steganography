"""Shared Utilities"""
from .quality_metrics import VideoQualityMetrics as QualityMetrics

# Export static methods as module-level functions
calculate_psnr = QualityMetrics.calculate_psnr
calculate_ssim = QualityMetrics.calculate_ssim

__all__ = ["QualityMetrics", "calculate_psnr", "calculate_ssim"]
