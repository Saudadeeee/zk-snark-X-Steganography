"""
verify_modes.py — Explicit verifier mode selection.

Provides clear mode naming for verification:
- strict_nonblind_verify: Full cover analysis, highest integrity
- nearblind_verify: Sidecar-assisted, no cover video needed
- benchmark_verify: Optimized for benchmark runs

Usage:
    from verify_modes import verify_strict, verify_nearblind, verify_benchmark

    # Strict mode (default, requires original video)
    result = verify_strict(
        stego_video_path="stego.h264",
        original_video_path="original.h264",
        circuits_dir="circuits/",
        secret_key=secret_key,
        message_length=len(message),
    )

    # Sidecar-assisted near-blind mode (no original video)
    result = verify_nearblind(
        stego_video_path="stego.h264",
        circuits_dir="circuits/",
        secret_key=secret_key,
        message_length=len(message),
    )

    # Benchmark mode (cached, fast)
    result = verify_benchmark(
        stego_video_path="stego.h264",
        original_video_path="original.h264",
        circuits_dir="circuits/",
        secret_key=secret_key,
        message_length=len(message),
    )
"""

from typing import Optional, List
from .verifier import verify, VerifyResult
from .verifier_blind import verify_near_blind as _verify_near_blind


def verify_strict(
    stego_video_path: str,
    original_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    max_modifications_per_block: int = 1,
    chaos_key: Optional[bytes] = None,
    precomputed_positions: Optional[List[tuple[int, int, int]]] = None,
    precomputed_payload_bits: Optional[int] = None,
) -> VerifyResult:
    """
    Strict non-blind verification with full cover analysis.

    **Requirements:**
    - original_video_path must be provided
    - Performs full IDR extraction from original video
    - Highest integrity verification path
    - Suitable for: final verification, security-critical applications

    **Runtime:** ~57s (cached) per embed
    """
    return verify(
        stego_video_path=stego_video_path,
        original_video_path=original_video_path,
        circuits_dir=circuits_dir,
        secret_key=secret_key,
        message_length=message_length,
        max_modifications_per_block=max_modifications_per_block,
        chaos_key=chaos_key,
        precomputed_positions=precomputed_positions,
        precomputed_payload_bits=precomputed_payload_bits,
        use_analysis_cache=True,
        force_analysis_refresh=False,
    )


def verify_nearblind(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    max_modifications_per_block: int = 1,
    chaos_key: Optional[bytes] = None,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
    manifest_signing_key: Optional[bytes] = None,
) -> VerifyResult:
    """
    Sidecar-assisted near-blind verification using manifest-driven extraction.

    **Requirements:**
    - manifest.json must exist alongside stego video
    - positions.json must exist (from embedding)
    - No original video required
    - Suitable for: sidecar-assisted verification at scale

    **Runtime:** ~10s per verification (no full analysis)
    **Trade-off:** Requires sidecar metadata (but no original video)

    **Missing requirements:**
    - If manifest.json or positions.json is missing, this mode fails explicitly
    """
    return _verify_near_blind(
        stego_video_path=stego_video_path,
        circuits_dir=circuits_dir,
        secret_key=secret_key,
        message_length=message_length,
        max_modifications_per_block=max_modifications_per_block,
        chaos_key=chaos_key,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
        manifest_signing_key=manifest_signing_key,
    )


def verify_benchmark(
    stego_video_path: str,
    original_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    max_modifications_per_block: int = 1,
    chaos_key: Optional[bytes] = None,
    use_cache: bool = True,
) -> VerifyResult:
    """
    Benchmark-optimized verification mode.

    **Optimizations:**
    - Aggressive caching enabled
    - Reuses cover analysis across multiple runs
    - Suitable for: benchmark iterations, repeated testing

    **Runtime:** ~7s (warm cache) per verification

    **Note:** This is a thin wrapper around verify() with cache defaults.
    For final paper numbers, use verify_strict().
    """
    return verify(
        stego_video_path=stego_video_path,
        original_video_path=original_video_path,
        circuits_dir=circuits_dir,
        secret_key=secret_key,
        message_length=message_length,
        max_modifications_per_block=max_modifications_per_block,
        chaos_key=chaos_key,
        use_analysis_cache=use_cache,
        force_analysis_refresh=False,
    )


def verify_auto(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    original_video_path: Optional[str] = None,
    max_modifications_per_block: int = 1,
    chaos_key: Optional[bytes] = None,
    manifest_signing_key: Optional[bytes] = None,
) -> VerifyResult:
    """
    Auto-select verification mode based on available files.

    **Priority:**
    1. Near-blind (if manifest.json exists) — fastest
    2. Strict (if original_video_path provided) — fallback
    3. Error (if neither available)

    **Use case:** Applications where mode should be transparently selected.
    """
    manifest_path = f"{stego_video_path}.manifest.json"

    if __import__("os").path.isfile(manifest_path):
        # Use near-blind if manifest exists
        try:
            return verify_nearblind(
                stego_video_path=stego_video_path,
                circuits_dir=circuits_dir,
                secret_key=secret_key,
                message_length=message_length,
                max_modifications_per_block=max_modifications_per_block,
                chaos_key=chaos_key,
                manifest_signing_key=manifest_signing_key,
            )
        except RuntimeError:
            if not original_video_path:
                raise
    elif original_video_path:
        # Use strict if original video provided
        return verify_strict(
            stego_video_path=stego_video_path,
            original_video_path=original_video_path,
            circuits_dir=circuits_dir,
            secret_key=secret_key,
            message_length=message_length,
            max_modifications_per_block=max_modifications_per_block,
            chaos_key=chaos_key,
        )

    raise RuntimeError(
        "verify_auto() requires a usable near-blind sidecar set or original_video_path. "
        "Neither was available."
    )


# Export for backward compatibility
__all__ = [
    "verify_strict",
    "verify_nearblind",
    "verify_benchmark",
    "verify_auto",
    "verify",  # For direct import from verify_modes
    "VerifyResult",
]
