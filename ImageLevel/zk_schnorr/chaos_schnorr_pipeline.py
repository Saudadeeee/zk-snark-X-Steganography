"""
Chaos-driven steganography pipeline backed by Schnorr proofs.

The module mirrors the responsibilities of `HybridProofArtifact` but
swaps Groth16 proofs for compact Schnorr proofs so we can evaluate both
approaches under identical embedding and feature extraction conditions.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.zk_stego.chaos_embedding import ChaosEmbedding, generate_chaos_key_from_secret

from .schnorr_proof import SchnorrProof, SchnorrProofSystem


def _extract_feature_point(image_array: np.ndarray) -> Tuple[int, int]:
    """
    Reuse the gradient-based feature detector from the SNARK pipeline.
    """
    height, width = image_array.shape[:2]

    if image_array.ndim == 3:
        gray = np.mean(image_array, axis=2).astype(np.uint8)
    else:
        gray = image_array

    grad_x = np.abs(np.diff(gray, axis=1))
    grad_y = np.abs(np.diff(gray, axis=0))
    grad_x = np.pad(grad_x, ((0, 0), (0, 1)), mode="edge")
    grad_y = np.pad(grad_y, ((0, 1), (0, 0)), mode="edge")

    gradient_mag = grad_x + grad_y
    window_size = max(4, min(16, width // 4, height // 4))

    best_x, best_y, max_texture = width // 2, height // 2, 0
    step = max(1, window_size // 4)

    for y in range(window_size // 2, height - window_size // 2, step):
        for x in range(window_size // 2, width - window_size // 2, step):
            window = gradient_mag[
                y - window_size // 2 : y + window_size // 2,
                x - window_size // 2 : x + window_size // 2,
            ]
            texture = np.sum(window)
            if texture > max_texture:
                max_texture = texture
                best_x, best_y = x, y

    best_x = max(1, min(best_x, width - 2))
    best_y = max(1, min(best_y, height - 2))
    return best_x, best_y


def _prepare_statement(
    image_array: np.ndarray,
    message: str,
    x0: int,
    y0: int,
    chaos_key: int,
) -> Tuple[Dict[str, int], bytes]:
    """Build the canonical statement that both SNARK and Schnorr digest."""
    image_hash = hashlib.sha256(image_array.tobytes()).hexdigest()
    message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()

    statement = {
        "image_hash": int(image_hash, 16),
        "message_hash": int(message_hash, 16),
        "chaos_key": int(chaos_key),
        "x0": int(x0),
        "y0": int(y0),
        "bit_length": len(message.encode("utf-8")) * 8,
        "timestamp": int(time.time()),
    }

    statement_bytes = json.dumps(statement, sort_keys=True).encode("utf-8")
    return statement, statement_bytes


@dataclass
class SchnorrProofPackage:
    """Structured response returned by the Schnorr pipeline."""

    stego_metadata: Dict[str, int]
    schnorr_proof: Dict[str, str]
    public_key: str
    runtime_ms: float

    def serialize(self) -> Dict[str, object]:
        return {
            "stego_metadata": self.stego_metadata,
            "schnorr_proof": self.schnorr_proof,
            "public_key": self.public_key,
            "runtime_ms": self.runtime_ms,
        }


class SchnorrChaosPipeline:
    """
    Drop-in replacement for the Groth16 embedding workflow.
    """

    def __init__(self) -> None:
        self.proof_system = SchnorrProofSystem()

    def embed_with_proof(
        self,
        image_array: np.ndarray,
        message: str,
        chaos_secret: str = "default_key",
        schnorr_secret: Optional[int] = None,
    ) -> Tuple[Image.Image, SchnorrProofPackage]:
        """
        Embed `message` using chaos LSB and return Schnorr proof package.
        """
        start_time = time.perf_counter()
        x0, y0 = _extract_feature_point(image_array)

        chaos_key = generate_chaos_key_from_secret(chaos_secret)
        chaos_embed = ChaosEmbedding(image_array)

        bits = []
        for byte in message.encode("utf-8"):
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)

        stego_array = chaos_embed.embed_bits(bits, x0, y0, chaos_key)
        stego_image = Image.fromarray(stego_array.astype(np.uint8))

        statement, statement_bytes = _prepare_statement(
            image_array=image_array,
            message=message,
            x0=x0,
            y0=y0,
            chaos_key=chaos_key,
        )

        if schnorr_secret is None:
            schnorr_secret, public_key = self.proof_system.generate_keypair()
        else:
            public_key = self.proof_system.derive_public(schnorr_secret)

        proof = self.proof_system.prove(statement_bytes, schnorr_secret)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        package = SchnorrProofPackage(
            stego_metadata=statement,
            schnorr_proof=proof.to_dict(),
            public_key=hex(public_key),
            runtime_ms=elapsed_ms,
        )

        return stego_image, package

    def verify_proof(self, package: SchnorrProofPackage | Dict[str, object]) -> bool:
        """
        Verify Schnorr proof extracted from a stego asset.
        """
        if isinstance(package, SchnorrProofPackage):
            data = package.serialize()
        else:
            data = package

        statement_bytes = json.dumps(data["stego_metadata"], sort_keys=True).encode("utf-8")
        proof = SchnorrProof.from_dict(data["schnorr_proof"])
        public_key = int(data["public_key"], 16)

        return self.proof_system.verify(statement_bytes, public_key, proof)
