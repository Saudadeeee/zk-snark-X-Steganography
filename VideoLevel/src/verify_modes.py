"""
verify_modes.py — Explicit verifier mode selection.

Provides clear mode naming for verification:
- strict_nonblind_verify: Full cover analysis, highest integrity
- nearblind_verify: Manifest-driven, no cover video needed
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

    # Near-blind mode (manifest only, no original video)
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
) -> VerifyResult:
    """
    Near-blind verification using manifest-driven extraction.

    **Requirements:**
    - manifest.json must exist alongside stego video
    - positions.json must exist (from embedding)
    - No original video required
    - Suitable for: production deployment, verification at scale

    **Runtime:** ~10s per verification (no full analysis)
    **Trade-off:** Requires manifest.json (but no original video)

    **Missing requirements:**
    - If manifest.json is missing, falls back to verify() with original video
    """
    try:
        return _verify_near_blind(
            stego_video_path=stego_video_path,
            circuits_dir=circuits_dir,
            secret_key=secret_key,
            message_length=message_length,
            max_modifications_per_block=max_modifications_per_block,
            chaos_key=chaos_key,
        )
    except RuntimeError as e:
        # Fallback to standard verification if manifest missing
        print(f"[verify_modes] Manifest not found: {e}")
        print("[verify_modes] Falling back to standard verification (requires original video)")
        raise RuntimeError(
            "Near-blind verification requires manifest.json and original_video_path "
            "was not provided. Either ensure manifest.json exists or use verify_strict()."
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
        return verify_nearblind(
            stego_video_path=stego_video_path,
            circuits_dir=circuits_dir,
            secret_key=secret_key,
            message_length=message_length,
            max_modifications_per_block=max_modifications_per_block,
            chaos_key=chaos_key,
        )
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
    else:
        raise RuntimeError(
            "verify_auto() requires either manifest.json or original_video_path. "
            "Neither was provided."
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