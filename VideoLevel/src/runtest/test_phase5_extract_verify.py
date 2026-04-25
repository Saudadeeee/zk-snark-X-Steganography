"""
test_phase5_extract_verify.py — Phase 5: Full Round-trip + ZK Proof Verification

Tests:
  1. full_roundtrip_known_payload  — embed known bytes → reconstruct → extract → exact match
  2. full_roundtrip_random_payload — same with os.urandom(20) bytes
  3. groth16_blob_roundtrip        — embed 274-byte simulated Groth16 blob → exact match
  4. zk_full_pipeline              — real proof: gen → pack → embed → extract → unpack → verify
                                     (SKIP if node not on PATH)

Run:
    python src/runtest/test_phase5_extract_verify.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.runtest._helpers     import section, run_test, summarise, get_video, get_output, \
                                     node_available, SKIP, get_circuits_dir
from src.core.pipeline import extract_all_idr_blocks, extract_bits_direct

from src.core.stego import PayloadEmbedder
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.zk_proof import pack, unpack, blob_bit_length, PROOF_SIZE_BYTES

# ── Config ────────────────────────────────────────────────────────────── #

VIDEO     = get_video('foreman_cif_g8.h264')
VIDEO_HQ  = get_video('foreman_cif_hq.h264')  # QP=30 all-intra: ~50 000 bits capacity
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
TEST_MSG   = b"Hello ZK-Stego"

# ── Common: embed → reconstruct → extract helper ─────────────────────── #

def _roundtrip(payload: bytes, stego_out: str, video: str = None) -> bytes:
    """
    Full pipeline: embed payload into video → write stego_out → extract → return bytes.
    Raises AssertionError if bits_embedded < required.
    Uses VIDEO by default; pass video=VIDEO_HQ for large-payload tests.
    """
    src = video if video is not None else VIDEO
    rec  = BitstreamReconstructor()
    coefficients, fvd, nC_map, nal_map, t1_map = extract_all_idr_blocks(src, rec)

    embedder = PayloadEmbedder()
    modified, bits_emb = embedder.embed_payload(
        coefficients, payload,
        nC_map=nC_map, nal_length_map=nal_map,
        t1_override_map=t1_map,
    )
    assert bits_emb == len(payload) * 8, \
        f"Embed incomplete: {bits_emb}/{len(payload)*8} bits"

    rec.reconstruct_video(
        src,
        modified,
        stego_out,
        max_slices=None,
        frame_verified_data=fvd,
    )

    # Recompute safe positions the same way (needed for extraction)
    from src.core.stego import CAVLCSafetyFilter
    sf   = CAVLCSafetyFilter()
    spos = sf.get_safe_positions(
        coefficients, skip_dc=True,
        nC_map=nC_map, nal_length_map=nal_map,
        t1_override_map=t1_map,
    )

    extracted = extract_bits_direct(
        stego_out,
        embed_safe_positions=spos,
        frame_verified_data=fvd,
        nC_map=nC_map,
        payload_bits=len(payload) * 8,
    )
    return extracted


# ── Tests ─────────────────────────────────────────────────────────────── #

def t_full_roundtrip_known_payload():
    out = get_output('test_p5_known.h264')
    try:
        payload   = b"ZK-STEGO-TEST-01"
        extracted = _roundtrip(payload, out)
        assert extracted == payload, \
            f"Known payload mismatch: {extracted.hex()} != {payload.hex()}"
    finally:
        if os.path.exists(out): os.remove(out)


def t_full_roundtrip_random_payload():
    out = get_output('test_p5_random.h264')
    try:
        payload   = os.urandom(20)
        extracted = _roundtrip(payload, out)
        assert extracted == payload, \
            f"Random payload mismatch (first 8B): {extracted[:8].hex()} != {payload[:8].hex()}"
    finally:
        if os.path.exists(out): os.remove(out)


def t_groth16_blob_roundtrip():
    """Simulate a 274-byte Groth16 blob (fixed pattern) and round-trip it."""
    out = get_output('test_p5_blob.h264')
    try:
        # Build a deterministic 274-byte blob: 4B hdr + 14B msg + 256B proof
        msg_bytes   = TEST_MSG
        proof_bytes = bytes(range(256))   # deterministic fake proof content
        import struct
        blob = struct.pack(">I", len(msg_bytes)) + msg_bytes + proof_bytes
        assert len(blob) == 274, f"Blob size {len(blob)} != 274"

        extracted = _roundtrip(blob, out, video=VIDEO_HQ)
        assert extracted == blob, \
            f"274-byte blob mismatch: first differ at byte " \
            f"{next(i for i,(a,b) in enumerate(zip(extracted,blob)) if a!=b)}"
    finally:
        if os.path.exists(out): os.remove(out)


def t_zk_full_pipeline():
    if not node_available():
        SKIP("zk_full_pipeline", "node not found on PATH")
        return

    out = get_output('test_p5_zk.h264')
    try:
        from src.zk_proof import ZKSnarkBridge
        bridge = ZKSnarkBridge(get_circuits_dir())

        # Phase 1: Generate real Groth16 proof
        proof_dict, public_dict = bridge.generate_proof_for_payload(TEST_MSG, SECRET_KEY)
        assert bridge.verify(proof_dict, public_dict), "Pre-embed proof verification failed"
        proof_bytes = bridge.proof_to_bytes(proof_dict)
        assert len(proof_bytes) == PROOF_SIZE_BYTES

        # Phase 2: Pack blob
        blob = pack(TEST_MSG, proof_bytes)
        assert len(blob) * 8 == blob_bit_length(TEST_MSG)

        # Phase 3-4: Embed + reconstruct + extract
        extracted_blob = _roundtrip(blob, out, video=VIDEO_HQ)
        assert extracted_blob == blob, \
            f"ZK blob extraction mismatch ({sum(a!=b for a,b in zip(extracted_blob,blob))} bytes differ)"

        # Phase 5: Unpack + verify
        ext_msg, ext_proof_bytes = unpack(extracted_blob)
        assert ext_msg == TEST_MSG, \
            f"Message mismatch after extraction: {ext_msg!r}"

        ext_proof_dict = bridge.bytes_to_proof(ext_proof_bytes)
        public_signals = bridge._build_public_signals(ext_msg, SECRET_KEY)
        valid = bridge.verify(ext_proof_dict, public_signals)
        assert valid, "Groth16 proof verification FAILED on extracted data"

    finally:
        if os.path.exists(out): os.remove(out)


# ── Main ─────────────────────────────────────────────────────────────── #

def main():
    section("Phase 5 — Full Round-trip & ZK Proof Verification")
    results = [
        run_test("full_roundtrip_known_payload",  t_full_roundtrip_known_payload),
        run_test("full_roundtrip_random_payload", t_full_roundtrip_random_payload),
        run_test("groth16_blob_roundtrip",        t_groth16_blob_roundtrip),
        run_test("zk_full_pipeline",              t_zk_full_pipeline),
    ]
    sys.exit(summarise(results, "Phase 5"))


if __name__ == '__main__':
    main()
