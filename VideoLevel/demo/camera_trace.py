"""Camera-proof internals for terminal_demo.py: Merkle opening and video digest.

Both are recomputed here in Python, step by step, and checked against what the
proof and the native ``video-digest`` command use, so the terminal shows how the
public root and the video digest come about rather than only their values.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from src.camera_registry import CameraRegistry, _empty_subtree_roots, camera_public_key
from src.native_blind_contract import segment_schedule
from src.poseidon import poseidon
from src.video_binding import VIDEO_DIGEST_DOMAIN, ebsp_to_rbsp, split_annex_b

NAL_NAMES = {1: "P/non-IDR", 5: "IDR", 6: "SEI", 7: "SPS", 8: "PPS", 9: "AUD"}


def short(value: int) -> str:
    return f"0x{value:064x}"[:18] + ".."


def merkle_walk(session, registry: CameraRegistry, secret: int, index: int) -> None:
    """Open leaf ``index`` to the root level by level, the computation the circuit constrains."""
    path = registry.path(index)
    empty = _empty_subtree_roots(registry.depth)
    node = camera_public_key(secret)
    session.say(f"Mo duong Merkle (PRIVATE trong proof): la {index}, pk = Poseidon(secret) = {short(node)}")
    session.say("  tang  bit  vi tri node   sibling               node moi = Poseidon(trai, phai)")
    for level, (sibling, bit) in enumerate(zip(path.siblings, path.path_indices)):
        left, right = (sibling, node) if bit else (node, sibling)
        node = poseidon([left, right])
        note = "  (cay con rong)" if sibling == empty[level] else ""
        session.say(f"  {level:4}  {bit:3}  {'phai' if bit else 'trai':10}  {short(sibling)}  -> {short(node)}{note}")
    session.check("Poseidon tung tang tu pk mo dung toi ROOT", node == registry.root)
    session.say("  bit = path_indices (bit thu i cua chi so la); sibling = node anh em; tang 16 = root.")
    session.say("  Circuit (MerkleInclusion) rang buoc dung 16 lan Poseidon nay -> proof khong lo la nao.")


def digest_breakdown(session, source: Path, segments: dict, key: bytes, frame_bits: int, max_bits: int,
                     native_digest: bytes) -> None:
    """Rebuild the canonical byte string of the video digest NAL by NAL and compare with native."""
    cleared: dict[int, list[int]] = {}
    for placement in segment_schedule(segments, key, frame_bits, max_bits):
        cleared.setdefault(placement.candidate.nal_index, []).append(placement.candidate.rbsp_bit_offset)
    canonical = bytearray(VIDEO_DIGEST_DOMAIN + frame_bits.to_bytes(4, "big") + max_bits.to_bytes(4, "big"))
    session.say(f"Python tai tao digest tu {source.name} (doc lap voi native):")
    session.say(f"  prefix = '{VIDEO_DIGEST_DOMAIN.decode()}' || u32 {frame_bits} || u32 {max_bits}"
                f" = {len(canonical)} byte")
    session.say("   NAL  loai        EBSP    RBSP  EPB  bit carrier dat ve 0  doi byte  SHA256(rbsp') prefix")
    example = None
    units = split_annex_b(source.read_bytes())
    for nal, (header, ebsp) in enumerate(units):
        rbsp = ebsp_to_rbsp(ebsp)
        original = bytes(rbsp)
        for bit in cleared.get(nal, ()):
            rbsp[bit // 8] &= ~(0x80 >> (bit % 8)) & 0xFF
            if example is None and original[bit // 8] >> (7 - bit % 8) & 1:
                example = (nal, bit, original[bit // 8], rbsp[bit // 8])
        canonical += (1 + len(rbsp)).to_bytes(4, "big") + bytes((header,)) + rbsp
        changed = sum(a != b for a, b in zip(original, rbsp))
        if nal < session.args.rows:
            session.say(f"  {nal:4}  {NAL_NAMES.get(header & 0x1F, str(header & 0x1F)):9} {len(ebsp):6}  {len(rbsp):6}"
                        f"  {len(ebsp) - len(rbsp):3}  {len(cleared.get(nal, ())):20}  {changed:8}"
                        f"  {hashlib.sha256(rbsp).hexdigest()[:16]}")
    if len(units) > session.args.rows:
        session.say(f"  ... {len(units) - session.args.rows} NAL nua (--rows de xem them)")
    session.say(f"  Moi NAL dong gop: u32(1 + len(rbsp')) || header 1B || rbsp'; tong canonical = {len(canonical):,} byte")
    if example is not None:
        nal, bit, before, after = example
        session.say(f"  Vi du: NAL {nal} RBSP bit {bit} = byte {bit // 8} bit {bit % 8} (MSB truoc):"
                    f" {before:08b} -> {after:08b} truoc khi bam")
    python_digest = hashlib.sha256(canonical).digest()
    session.say(f"  SHA256(canonical) = {python_digest.hex()}")
    session.check("digest Python (tung NAL) = digest native video-digest", python_digest == native_digest)
    session.say(f"  {sum(map(len, cleared.values()))} bit carrier tren {len(cleared)} IDR bi xoa; moi bit con lai"
                " (header, MB, he so, bit dau khong mang khung, SEI, SPS/PPS) deu vao hash.")
