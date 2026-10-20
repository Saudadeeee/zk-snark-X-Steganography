"""Known-answer vectors pin the exact BDLOP wire format and derivations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KAT_FILE = ROOT / "research" / "bdlop_params" / "kat_v1.json"


@pytest.fixture(scope="module")
def expected() -> dict:
    return json.loads(KAT_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual(expected) -> dict:
    from research.bdlop_params.kat import generate

    assert expected["parameter_set"] == "bdlop-open-128-v1"
    return generate("BDLOP_OPEN_128")


def test_parameter_id_and_public_key_are_unchanged(expected, actual) -> None:
    assert actual["parameter_id"] == expected["parameter_id"]
    assert actual["key_sha256"] == expected["key_sha256"]


@pytest.mark.parametrize("index", range(3))
def test_commitments_and_proofs_match_the_vectors(expected, actual, index) -> None:
    assert actual["vectors"][index] == expected["vectors"][index]


def test_vectors_verify() -> None:
    from research.bdlop_params.kat import CASES, _seed
    from src.lattice_zk import bdlop, codec, opening_proof
    from src.lattice_zk.params import BDLOP_OPEN_128 as params

    case = CASES[1]
    randomness = bdlop.sample_randomness(params, _seed("randomness", case["name"]))
    commitment = bdlop.commit(params, codec.encode_payload(params, case["payload"]), randomness)
    proof = opening_proof.prove_with_stats(
        params, case["statement"], commitment, randomness, mask_seed=_seed("mask", case["name"])
    ).proof
    assert opening_proof.verify(params, case["statement"], commitment, proof)
