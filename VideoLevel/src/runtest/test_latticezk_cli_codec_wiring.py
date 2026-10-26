"""The CLI ``--codec-policy`` / ``--gop-policy`` choices thread the right profile."""

from __future__ import annotations

import pytest

from src.lattice_zk import cli
from src.lattice_zk import video_pipeline as pipeline
from src.transport import gop_policy as gop_policies
from src.transport.blind_sync import BlindOperatingContract
from src.transport.cabac_sync import CabacMagnitudeContract


def _profile(argv_tail: list[str], *, registered: bool):
    base = ["embed", "--video", "v", "--output", "o", "--session", "ab" * 32,
            "--registry", "r", "--issuer-public", "p", "--minimum-epoch", "1"]
    arguments = cli._build_parser().parse_args(base + argv_tail)
    return cli._profile(arguments, registered=registered)


def test_codec_policy_choices_cover_cavlc_and_cabac() -> None:
    assert set(cli.CODEC_POLICIES) == {"v1", "v2", "cabac"}
    assert cli.CODEC_POLICIES["cabac"] == pipeline.CODEC_POLICY_CABAC_V1


@pytest.mark.parametrize("policy", ["v1", "v2"])
def test_cavlc_policies_use_the_blind_contract(policy) -> None:
    profile = _profile(["--codec-policy", policy], registered=True)
    assert isinstance(profile.contract, BlindOperatingContract)
    assert profile.codec_policy == cli.CODEC_POLICIES[policy]
    assert profile.gop_policy == gop_policies.ALL_INTRA


def test_cabac_policy_uses_the_cabac_contract() -> None:
    profile = _profile(["--codec-policy", "cabac"], registered=True)
    assert isinstance(profile.contract, CabacMagnitudeContract)
    assert profile.codec_policy == pipeline.CODEC_POLICY_CABAC_V1
    # Its id differs from both CAVLC policies' ids.
    from src.lattice_zk.params import BDLOP_OPEN_128

    others = {_profile(["--codec-policy", p], registered=True).profile_id(BDLOP_OPEN_128)
              for p in ("v1", "v2")}
    assert profile.profile_id(BDLOP_OPEN_128) not in others


def test_gop_policy_threads_through() -> None:
    profile = _profile(["--gop-policy", "idr-carriers-inter-raw-v1"], registered=True)
    assert profile.gop_policy == "idr-carriers-inter-raw-v1"
    assert profile.options()["gop_policy"] == "idr-carriers-inter-raw-v1"
    # CABAC + GOP>1 is a valid combination.
    cabac_gop = _profile(["--codec-policy", "cabac", "--gop-policy", "idr-carriers-inter-raw-v1"],
                         registered=True)
    assert isinstance(cabac_gop.contract, CabacMagnitudeContract)
    assert cabac_gop.gop_policy == "idr-carriers-inter-raw-v1"


def test_unknown_policy_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit):
        _profile(["--codec-policy", "v3"], registered=True)
