"""
SEC1 Auditability — Quality guard details and reason logs.

Extends SEC1 with per-sequence reason logs for:
- Why positions were pruned
- Quality guard threshold history
- Headroom margin tracking

Integrate with sec1_quality.py by importing and calling:
    from benchmark.sec1_audit import AuditLogger

    audit = AuditLogger(sequence_name, validation_threshold_db)
    audit.record_pruned_position(mb, blk, cidx, reason="ffmpeg_validation_failed")
    audit.record_quality_gate(threshold_db, effective_threshold_db, margin_db)
    audit.save(RESULTS_DIR / f"audit_{sequence_name}.json")
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class PrunedPosition:
    """Record of a position that was pruned during safety filtering."""

    mb_idx: int
    blk_idx: int
    cidx: int
    reason: str  # e.g., "ffmpeg_validation_failed", "patchable_check_failed"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class QualityGateRecord:
    """Record of a quality gate evaluation."""

    iteration: int
    threshold_db: float
    effective_threshold_db: Optional[float]
    positions_before: int
    positions_after: int
    modified_frame_count: int
    min_psnr_db: float
    passed: bool
    reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AuditLog:
    """Complete audit log for a sequence run."""

    sequence_name: str
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None

    # Configuration
    target_psnr_full_db: Optional[float] = None
    validation_threshold_db: Optional[float] = None
    validation_threshold_effective: Optional[float] = None

    # Position tracking
    raw_t1_positions: int = 0
    safe_positions_after_filter: int = 0
    final_used_positions: int = 0

    # Quality tracking
    frame_count: int = 0
    modified_frame_count: int = 0
    psnr_inf_frame_count: int = 0

    # Detailed records
    pruned_positions: List[PrunedPosition] = field(default_factory=list)
    quality_gates: List[QualityGateRecord] = field(default_factory=list)

    # Headroom tracking
    headroom_margin_db: Optional[float] = None  # Margin above threshold for closest frame
    min_modified_frame_psnr: Optional[float] = None

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "sequence_name": self.sequence_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "configuration": {
                "target_psnr_full_db": self.target_psnr_full_db,
                "validation_threshold_db": self.validation_threshold_db,
                "validation_threshold_effective": self.validation_threshold_effective,
            },
            "position_counts": {
                "raw_t1_positions": self.raw_t1_positions,
                "safe_positions_after_filter": self.safe_positions_after_filter,
                "final_used_positions": self.final_used_positions,
            },
            "quality_metrics": {
                "frame_count": self.frame_count,
                "modified_frame_count": self.modified_frame_count,
                "psnr_inf_frame_count": self.psnr_inf_frame_count,
                "headroom_margin_db": self.headroom_margin_db,
                "min_modified_frame_psnr": self.min_modified_frame_psnr,
            },
            "pruned_positions": [
                {
                    "mb_idx": p.mb_idx,
                    "blk_idx": p.blk_idx,
                    "cidx": p.cidx,
                    "reason": p.reason,
                    "timestamp": p.timestamp,
                }
                for p in self.pruned_positions
            ],
            "quality_gates": [
                {
                    "iteration": q.iteration,
                    "threshold_db": q.threshold_db,
                    "effective_threshold_db": q.effective_threshold_db,
                    "positions_before": q.positions_before,
                    "positions_after": q.positions_after,
                    "modified_frame_count": q.modified_frame_count,
                    "min_psnr_db": q.min_psnr_db,
                    "passed": q.passed,
                    "reason": q.reason,
                    "timestamp": q.timestamp,
                }
                for q in self.quality_gates
            ],
        }


class AuditLogger:
    """Logger for SEC1 auditability tracking."""

    def __init__(self, sequence_name: str, validation_threshold_db: Optional[float] = None):
        self.sequence_name = sequence_name
        self.log = AuditLog(
            sequence_name=sequence_name,
            validation_threshold_db=validation_threshold_db,
        )

    def set_raw_t1_positions(self, count: int) -> None:
        self.log.raw_t1_positions = count

    def set_safe_positions(self, count: int) -> None:
        self.log.safe_positions_after_filter = count

    def set_final_positions(self, count: int) -> None:
        self.log.final_used_positions = count

    def set_frame_count(self, count: int) -> None:
        self.log.frame_count = count

    def set_modified_frame_count(self, count: int) -> None:
        self.log.modified_frame_count = count

    def set_psnr_inf_frame_count(self, count: int) -> None:
        self.log.psnr_inf_frame_count = count

    def set_headroom_margin(self, margin_db: float) -> None:
        self.log.headroom_margin_db = margin_db

    def set_min_modified_frame_psnr(self, psnr_db: float) -> None:
        self.log.min_modified_frame_psnr = psnr_db

    def record_pruned_position(
        self, mb_idx: int, blk_idx: int, cidx: int, reason: str
    ) -> None:
        """Record a position that was pruned during safety filtering."""
        # Limit sample size to avoid huge logs (max 1000 pruned records)
        if len(self.log.pruned_positions) < 1000:
            self.log.pruned_positions.append(
                PrunedPosition(mb_idx=mb_idx, blk_idx=blk_idx, cidx=cidx, reason=reason)
            )

    def record_quality_gate(
        self,
        iteration: int,
        threshold_db: float,
        effective_threshold_db: Optional[float],
        positions_before: int,
        positions_after: int,
        modified_frame_count: int,
        min_psnr_db: float,
        passed: bool,
        reason: Optional[str] = None,
    ) -> None:
        """Record a quality gate evaluation."""
        self.log.quality_gates.append(
            QualityGateRecord(
                iteration=iteration,
                threshold_db=threshold_db,
                effective_threshold_db=effective_threshold_db,
                positions_before=positions_before,
                positions_after=positions_after,
                modified_frame_count=modified_frame_count,
                min_psnr_db=min_psnr_db,
                passed=passed,
                reason=reason,
            )
        )

    def finalize(self) -> None:
        """Mark the audit log as finished."""
        self.log.finished_at = datetime.now().isoformat()

    def save(self, output_path: Path) -> None:
        """Save audit log to JSON file."""
        self.finalize()
        output_path.write_text(json.dumps(self.log.to_dict(), indent=2))

    @classmethod
    def load(cls, input_path: Path) -> "AuditLogger":
        """Load audit log from JSON file."""
        data = json.loads(input_path.read_text())
        logger = cls(
            sequence_name=data["sequence_name"],
            validation_threshold_db=data["configuration"]["validation_threshold_db"],
        )
        logger.log = AuditLog(
            sequence_name=data["sequence_name"],
            started_at=data["started_at"],
            finished_at=data["finished_at"],
            target_psnr_full_db=data["configuration"]["target_psnr_full_db"],
            validation_threshold_db=data["configuration"]["validation_threshold_db"],
            validation_threshold_effective=data["configuration"]["validation_threshold_effective"],
            raw_t1_positions=data["position_counts"]["raw_t1_positions"],
            safe_positions_after_filter=data["position_counts"]["safe_positions_after_filter"],
            final_used_positions=data["position_counts"]["final_used_positions"],
            frame_count=data["quality_metrics"]["frame_count"],
            modified_frame_count=data["quality_metrics"]["modified_frame_count"],
            psnr_inf_frame_count=data["quality_metrics"]["psnr_inf_frame_count"],
            headroom_margin_db=data["quality_metrics"]["headroom_margin_db"],
            min_modified_frame_psnr=data["quality_metrics"]["min_modified_frame_psnr"],
        )
        return logger


def merge_audit_logs(
    output_dir: Path,
    pattern: str = "audit_*.json",
    output_file: str = "sec1_audit_aggregated.json",
) -> None:
    """Merge individual sequence audit logs into aggregated summary."""
    logs = {}
    for audit_file in sorted(output_dir.glob(pattern)):
        data = json.loads(audit_file.read_text())
        seq_name = data["sequence_name"]
        logs[seq_name] = data

    # Create aggregated summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "sequence_count": len(logs),
        "sequences": {},
    }

    for seq_name, log_data in logs.items():
        summary["sequences"][seq_name] = {
            "configuration": log_data["configuration"],
            "position_counts": log_data["position_counts"],
            "quality_metrics": log_data["quality_metrics"],
            "quality_gate_iterations": len(log_data["quality_gates"]),
            "pruned_sample_size": len(log_data["pruned_positions"]),
        }

    output_dir.joinpath(output_file).write_text(json.dumps(summary, indent=2))