"""Known-answer vectors pin the exact BDLOP wire format and derivations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KAT_DIR = ROOT / "research" / "bdlop_params"
# (vector file, params.py attribute, parameter set name)
KAT_SETS = (
    ("kat_v1.json", "BDLOP_OPEN_128_V1", "bdlop-open-128-v1"),
    ("kat_v2.json", "BDLOP_OPEN_128_V2", "bdlop-open-128-v2"),
)


@pytest.fixture(scope="module", params=KAT_SETS, ids=[name for _, _, name in KAT_SETS])
def kat(request) -> tuple[dict, dict, str]:
    from research.bdlop_params.kat import generate

    file_name, attribute, name = request.param
    expected = json.loads((KAT_DIR / file_name).read_text(encoding="utf-8"))
    assert expected["parameter_set"] == name
    return expected, generate(attribute), attribute


def test_parameter_id_and_public_key_are_unchanged(kat) -> None:
    expected, actual, _ = kat
    assert actual["parameter_id"] == expected["parameter_id"]
    assert actual["key_sha256"] == expected["key_sha256"]


@pytest.mark.parametrize("index", range(3))
def test_commitments_and_proofs_match_the_vectors(kat, index) -> None:
    expected, actual, _ = kat
    assert actual["vectors"][index] == expected["vectors"][index]


def test_vectors_verify(kat) -> None:
    from research.bdlop_params.kat import CASES, _seed
    from src.lattice_zk import bdlop, codec, opening_proof
    from src.lattice_zk import params as parameter_sets

    params = getattr(parameter_sets, kat[2])
    case = CASES[1]
    randomness = bdlop.sample_randomness(params, _seed("randomness", case["name"]))
    commitment = bdlop.commit(params, codec.encode_payload(params, case["payload"]), randomness)
    proof = opening_proof.prove_with_stats(
        params, case["statement"], commitment, randomness, mask_seed=_seed("mask", case["name"])
    ).proof
    assert opening_proof.verify(params, case["statement"], commitment, proof)
