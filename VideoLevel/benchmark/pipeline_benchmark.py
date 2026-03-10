"""
ZK-Stego Pipeline Benchmark
======================================================
Each stage is timed individually (wall-clock).

Python stages (0-4) run REPEAT=3 times -> min / avg / max.
Node.js stages (5-6) run once (too slow to repeat).

Stages:
  0  extract_all_idr_blocks  -- H264 parse + CAVLC extract + Patcher validate
  1  safety_filter           -- CAVLCSafetyFilter.get_safe_positions
  2  embed_payload           -- PayloadEmbedder.embed_payload
  3  reconstruct_video       -- BitstreamReconstructor.reconstruct_video
  4  extract_bits_direct     -- tracer-free extraction from stego video
  5  ZK proof generation     -- snarkjs groth16 prove  [x1]
  6  ZK proof verification   -- snarkjs groth16 verify [x1]

Usage:
    python benchmark/pipeline_benchmark.py
"""

import os, sys, time, statistics, io

BENCH_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT        = os.path.dirname(BENCH_DIR)
RESULTS_DIR = os.path.join(BENCH_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

sys.path.insert(0, ROOT)

VIDEO      = os.path.join(ROOT, "data", "encoded", "foreman_cif_g8.h264")
OUT_STEGO  = os.path.join(ROOT, "data", "output",  "bench_stego.h264")
CIRCUITS   = os.path.join(ROOT, "circuits")
OUT_TXT    = os.path.join(RESULTS_DIR, "pipeline_results.txt")
REPEAT     = 3

SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
TEST_MSG   = b"Hello ZK-Stego"
PAYLOAD    = TEST_MSG + bytes(range(256))[:260]


class Tee:
    """Write to both stdout and a file simultaneously."""
    def __init__(self, path):
        self._f   = open(path, "w", encoding="utf-8")
        self._out = sys.__stdout__
    def write(self, s):
        self._out.write(s)
        self._f.write(s)
    def flush(self):
        self._out.flush()
        self._f.flush()
    def close(self):
        self._f.close()


tee = Tee(OUT_TXT)
sys.stdout = tee

SEP = "-" * 62

def hdr(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def ms(t):
    return f"{t * 1000:9.1f} ms"

def run_n(label, fn, n=REPEAT):
    samples, result = [], None
    for i in range(n):
        t0      = time.perf_counter()
        result  = fn()
        elapsed = time.perf_counter() - t0
        samples.append(elapsed)
        print(f"  [{label}] rep {i+1}/{n}: {ms(elapsed)}")
    return samples, result

def stat(label, samples):
    mn = min(samples); avg = statistics.mean(samples); mx = max(samples)
    print(f"    -> min={ms(mn)}  avg={ms(avg)}  max={ms(mx)}")
    return avg

def suppress(fn):
    buf = io.StringIO()
    old, sys.stdout = sys.stdout, buf
    try:
        return fn()
    finally:
        sys.stdout = old


print("Loading modules...", end=" ", flush=True)
t_imp = time.perf_counter()

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.embedder.embedder        import CAVLCSafetyFilter, PayloadEmbedder
from src.runtest._idr_extract    import extract_all_idr_blocks, extract_bits_direct

print(f"done ({ms(time.perf_counter() - t_imp)})")


# Stage 0 — extract_all_idr_blocks
hdr("Stage 0 . extract_all_idr_blocks  [H264 parse + CAVLC + Patcher]")

coefficients = fvd = nC_map = nal_map = t1_map = rec = None

def s0():
    global coefficients, fvd, nC_map, nal_map, t1_map, rec
    rec = BitstreamReconstructor()
    coefficients, fvd, nC_map, nal_map, t1_map = extract_all_idr_blocks(VIDEO, rec)

samples0, _ = run_n("idr-extract", s0)
avg0 = stat("idr-extract", samples0)
n_idr = len(fvd); n_coeffs = len(coefficients)
print(f"    IDR frames     : {n_idr}")
print(f"    Non-zero blocks: {n_coeffs}")
print(f"    nC entries     : {len(nC_map)}")


# Stage 1 — CAVLCSafetyFilter
hdr("Stage 1 . CAVLCSafetyFilter.get_safe_positions")

spos = None

def s1():
    global spos
    spos = CAVLCSafetyFilter().get_safe_positions(
        coefficients, skip_dc=True,
        nC_map=nC_map, nal_length_map=nal_map, t1_override_map=t1_map,
    )

samples1, _ = run_n("safety-filter", s1)
avg1 = stat("safety-filter", samples1)
cap_bits = len(spos); need_bits = len(PAYLOAD) * 8
print(f"    Safe positions : {cap_bits} bits  ({cap_bits // 8} bytes)")
print(f"    Payload needed : {need_bits} bits  ({len(PAYLOAD)} bytes)")
print(f"    Head-room      : {cap_bits - need_bits:+d} bits")


# Stage 2 — PayloadEmbedder
hdr("Stage 2 . PayloadEmbedder.embed_payload")

modified = None; bits_emb = 0

def s2():
    global modified, bits_emb
    modified, bits_emb = PayloadEmbedder().embed_payload(
        coefficients, PAYLOAD,
        nC_map=nC_map, nal_length_map=nal_map, t1_override_map=t1_map,
    )

samples2, _ = run_n("embed", s2)
avg2 = stat("embed", samples2)
ok_emb = (bits_emb == need_bits)
print(f"    Bits embedded  : {bits_emb}/{need_bits}  {'[OK]' if ok_emb else '[X] INCOMPLETE'}")
print(f"    Modified blocks: {len(modified)}")


# Stage 3 — BitstreamReconstructor
hdr("Stage 3 . BitstreamReconstructor.reconstruct_video")

def s3():
    suppress(lambda: rec.reconstruct_video(
        VIDEO, modified, OUT_STEGO, frame_verified_data=fvd
    ))
    return os.path.getsize(OUT_STEGO)

samples3, stego_size = run_n("reconstruct", s3)
avg3 = stat("reconstruct", samples3)
orig_size = os.path.getsize(VIDEO)
print(f"    Original size  : {orig_size:,} bytes")
print(f"    Stego size     : {stego_size:,} bytes  (delta {stego_size - orig_size:+d})")


# Stage 4 — extract_bits_direct
hdr("Stage 4 . extract_bits_direct  [tracer-free]")

extracted_bytes = None

def s4():
    global extracted_bytes
    extracted_bytes = extract_bits_direct(
        OUT_STEGO,
        embed_safe_positions=spos,
        frame_verified_data=fvd,
        nC_map=nC_map,
        payload_bits=len(PAYLOAD) * 8,
    )

samples4, _ = run_n("extract", s4)
avg4 = stat("extract", samples4)
match = (extracted_bytes == PAYLOAD)
n_match = sum(a == b for a, b in zip(extracted_bytes, PAYLOAD))
print(f"    Extracted      : {len(extracted_bytes)}/{len(PAYLOAD)} bytes")
print(f"    Bit-perfect    : {'YES [OK]' if match else f'NO -- {len(PAYLOAD)-n_match}/{len(PAYLOAD)} differ [X]'}")


# Stage 5 — ZK proof generation
hdr("Stage 5 . ZK Proof Generation  [snarkjs - x1]")

zk_available = False
t5 = t6 = float("nan")
proof_dict = public_dict = None

try:
    from src.zk_snark_bridge import ZKSnarkBridge
    bridge = ZKSnarkBridge(CIRCUITS)
    print("  Calling bridge.generate_proof_for_payload()...", flush=True)
    t5_start = time.perf_counter()
    proof_dict, public_dict = bridge.generate_proof_for_payload(TEST_MSG, SECRET_KEY)
    t5 = time.perf_counter() - t5_start
    proof_bytes = bridge.proof_to_bytes(proof_dict)
    print(f"  -> Total      : {ms(t5)}")
    print(f"    Proof bytes: {len(proof_bytes)}")
    zk_available = True
except Exception as e:
    print(f"  [SKIP] ZK not available: {e}")


# Stage 6 — ZK proof verification
hdr("Stage 6 . ZK Proof Verification  [snarkjs - x1]")

if zk_available:
    print("  Calling bridge.verify()...", flush=True)
    t6_start = time.perf_counter()
    is_valid = bridge.verify(proof_dict, public_dict)
    t6 = time.perf_counter() - t6_start
    print(f"  -> Total  : {ms(t6)}")
    print(f"    Valid  : {'YES [OK]' if is_valid else 'NO [X]'}")
else:
    is_valid = None


# Summary
hdr("Summary  (avg over 3 reps for Python stages)")

C1, C2, C3 = 42, 12, 28

def fms(v):
    return "  (skip)" if (v != v) else f"{v*1000:9.1f}"

rows = [
    ("0  extract_all_idr_blocks", avg0, f"{n_idr} IDRs, {n_coeffs} blocks"),
    ("1  safety_filter",          avg1, f"{cap_bits} safe bits"),
    ("2  embed_payload",          avg2, f"{len(modified)} modifications"),
    ("3  reconstruct_video",      avg3, f"delta {stego_size-orig_size:+d} bytes"),
    ("4  extract_bits_direct",    avg4, f"{'bit-perfect [OK]' if match else 'MISMATCH [X]'}"),
    ("5  ZK prove  [x1]",        t5,   "snarkjs groth16 prove"),
    ("6  ZK verify [x1]",        t6,   "snarkjs groth16 verify"),
]

print(f"\n  {'Stage':<{C1}} {'avg ms':>{C2}}  {'Notes'}")
print("  " + "-"*C1 + " " + "-"*C2 + "  " + "-"*C3)
for name, avg, note in rows:
    print(f"  {name:<{C1}} {fms(avg):>{C2}}  {note}")

python_total = (avg0 + avg1 + avg2 + avg3 + avg4) * 1000
zk_total     = (0 if t5 != t5 else t5 + (0 if t6 != t6 else t6)) * 1000

print(f"\n  {'Python total (stages 0-4)':<{C1}} {python_total:9.1f} ms")
if zk_available:
    print(f"  {'ZK total (5+6)':<{C1}} {zk_total:9.1f} ms")
    print(f"  {'End-to-end total':<{C1}} {python_total + zk_total:9.1f} ms")

print(f"\n  Bit-perfect : {'YES [OK]' if match else 'NO [X]'}")
if zk_available:
    print(f"  ZK valid    : {'YES [OK]' if is_valid else 'NO [X]'}")

tee.close()
sys.stdout = sys.__stdout__
print(f"\nResults saved to: {OUT_TXT}")

# cleanup temp stego
if os.path.exists(OUT_STEGO):
    os.remove(OUT_STEGO)
