"""Role-separated CLI for the BDLOP video proof, over the stand-in channel."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.lattice_zk import cli
from src.lattice_zk import video_pipeline as pipeline
from src.runtest.test_latticezk_video_pipeline import FakeTransport


@pytest.fixture(autouse=True)
def _environment(monkeypatch) -> None:
    monkeypatch.setenv(cli.SYNC_KEY_ENV, "ab" * 32)
    monkeypatch.setattr(pipeline, "_default_transport", FakeTransport)


def _run(capsys, *argv: object) -> tuple[int, dict]:
    code = cli.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else {"stderr": captured.err})


def _issuer(tmp_path: Path, capsys) -> tuple[Path, Path]:
    public, private = tmp_path / "issuer.pub", tmp_path / "issuer.key"
    assert _run(capsys, "issuer-keygen", "--public", public, "--private", private)[0] == 0
    return public, private


def _cover(tmp_path: Path) -> Path:
    cover = tmp_path / "cover.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    return cover


def test_in_band_flow_across_roles(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                "--out", registry)[1]["mode"] == "in-band"
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 2)

    code, grant = _run(capsys, "session-issue", "--database", database, *verifier)
    assert code == 0 and len(grant["challenge"]) == 64

    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    stego, opening = tmp_path / "stego.h264", tmp_path / "opening.json"
    code, embedded = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", stego,
                          "--session", grant["challenge"], "--payload-file", payload,
                          "--opening-out", opening, *verifier)
    assert code == 0 and embedded["envelope_bytes"] == 14_309
    assert b"hidden record" not in stego.read_bytes()
    assert json.loads(opening.read_text())["payload"] == b"hidden record".hex()

    code, verified = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 0 and verified["valid"] and verified["statement_id"] == embedded["statement_id"]
    code, replay = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 1 and not replay["valid"]


def test_registered_flow_authenticates_only_the_registered_holder(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    payload = tmp_path / "device.bin"
    payload.write_bytes(b"device 42")
    credentials = []
    for name in ("holder", "stranger"):
        public, private = tmp_path / f"{name}.pub.json", tmp_path / f"{name}.key.json"
        assert _run(capsys, "credential-new", "--payload-file", payload,
                    "--public", public, "--private", private)[0] == 0
        credentials.append((public, private))
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1,
                "--credential", credentials[0][0], "--out", registry)[1]["mode"] == "registered"
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1,
                "--credential", credentials[0][0])

    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)
    stego = tmp_path / "stego.h264"
    base = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1)
    code, embedded = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", stego,
                          "--session", grant["challenge"],
                          "--credential-private", credentials[0][1], *base)
    assert code == 0 and embedded["envelope_bytes"] == 7_589

    # An unregistered credential cannot even resolve pins against this registry.
    code, _ = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", tmp_path / "x.h264",
                   "--session", grant["challenge"],
                   "--credential-private", credentials[1][1], *base)
    assert code == 2

    code, verified = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 0 and verified["valid"] and verified["mode"] == "registered"


def test_cli_fails_closed_on_bad_configuration(tmp_path, capsys, monkeypatch) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry = tmp_path / "registry.json"
    _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1, "--out", registry)
    database = tmp_path / "sessions.sqlite3"
    common = ("--database", database, "--registry", registry, "--issuer-public", issuer_public)

    assert _run(capsys, "session-issue", *common, "--minimum-epoch", 2)[0] == 2  # rollback floor
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1,
                "--out", registry)[0] == 2  # never overwrites
    other_public, _ = tmp_path / "other.pub", tmp_path / "other.key"
    _run(capsys, "issuer-keygen", "--public", other_public, "--private", tmp_path / "other.key")
    assert _run(capsys, "session-issue", "--database", database, "--registry", registry,
                "--issuer-public", other_public, "--minimum-epoch", 1)[0] == 2

    _, grant = _run(capsys, "session-issue", *common, "--minimum-epoch", 1)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"p")
    embed = ("embed", "--video", _cover(tmp_path), "--output", tmp_path / "s.h264",
             "--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1,
             "--payload-file", payload, "--opening-out", tmp_path / "o.json")
    assert _run(capsys, *embed, "--session", "zz")[0] == 2
    monkeypatch.delenv(cli.SYNC_KEY_ENV)
    assert _run(capsys, *embed, "--session", grant["challenge"])[0] == 2


def test_public_carrier_order_needs_no_stego_key(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv(cli.SYNC_KEY_ENV)
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1, "--out", registry)
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1,
                "--public-carrier-order")
    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"public record")
    stego = tmp_path / "stego.h264"
    code, _ = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", stego,
                   "--session", grant["challenge"], "--payload-file", payload,
                   "--opening-out", tmp_path / "o.json", *verifier)
    assert code == 0
    code, verified = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 0 and verified["valid"]


# -- file handling --------------------------------------------------------- #

def test_key_pairs_are_never_half_written(tmp_path, capsys) -> None:
    public, private = tmp_path / "issuer.pub", tmp_path / "issuer.key"
    private.write_bytes(b"existing secret")
    assert _run(capsys, "issuer-keygen", "--public", public, "--private", private)[0] == 2
    assert not public.exists() and private.read_bytes() == b"existing secret"

    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"device 42")
    holder_public, holder_private = tmp_path / "holder.pub.json", tmp_path / "holder.key.json"
    holder_private.write_text("{}")
    assert _run(capsys, "credential-new", "--payload-file", payload,
                "--public", holder_public, "--private", holder_private)[0] == 2
    assert not holder_public.exists() and holder_private.read_text() == "{}"

    same = tmp_path / "same.key"
    assert _run(capsys, "issuer-keygen", "--public", same, "--private", same)[0] == 2
    assert not same.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows uses ACLs")
def test_secret_files_are_owner_only(tmp_path, capsys) -> None:
    public, private = _issuer(tmp_path, capsys)
    assert stat.S_IMODE(private.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(public.stat().st_mode) & 0o022 == 0


def _registry_and_grant(tmp_path: Path, capsys) -> tuple[tuple[object, ...], str]:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1, "--out", registry)
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1)
    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)
    return verifier, grant["challenge"]


def test_embed_checks_every_output_before_proving(tmp_path, capsys) -> None:
    verifier, challenge = _registry_and_grant(tmp_path, capsys)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    stego, opening = tmp_path / "stego.h264", tmp_path / "opening.json"
    embed = ("embed", "--video", _cover(tmp_path), "--output", stego, "--session", challenge,
             "--payload-file", payload, *verifier)

    # Without somewhere to keep the opening, no stego video may be produced.
    assert _run(capsys, *embed)[0] == 2 and not stego.exists()
    opening.write_text("{}")
    assert _run(capsys, *embed, "--opening-out", opening)[0] == 2 and not stego.exists()
    opening.unlink()
    stego.write_bytes(b"older video")
    assert _run(capsys, *embed, "--opening-out", opening)[0] == 2
    assert stego.read_bytes() == b"older video" and not opening.exists()
    stego.unlink()
    assert _run(capsys, *embed, "--opening-out", opening)[0] == 0
    assert stego.exists() and opening.exists()


def test_malformed_credential_files_fail_closed(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    payload = tmp_path / "device.bin"
    payload.write_bytes(b"device 42")
    public, private = tmp_path / "holder.pub.json", tmp_path / "holder.key.json"
    _run(capsys, "credential-new", "--payload-file", payload, "--public", public, "--private", private)
    record = json.loads(private.read_text())
    variants = {
        "array.json": [record],
        "other-params.json": {**record, "parameter_id": "00" * 32},
        "short-randomness.json": {**record, "randomness": record["randomness"][:-2]},
        "bad-commitment.json": {**record, "commitment": "zz"},
    }
    for name, content in variants.items():
        path = tmp_path / name
        path.write_text(json.dumps(content))
        code, report = _run(capsys, "registry-sign", "--issuer-private", issuer_private,
                            "--epoch", 1, "--credential", path, "--out", tmp_path / f"{name}.reg")
        if name == "short-randomness.json":  # the public part is still well formed
            assert code == 0
            continue
        assert code == 2 and "error:" in report["stderr"], name
    code, report = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", tmp_path / "s.h264",
                        "--session", "07" * 32, "--credential-private", tmp_path / "short-randomness.json",
                        "--registry", tmp_path / "short-randomness.json.reg",
                        "--issuer-public", issuer_public, "--minimum-epoch", 1)
    assert code == 2 and "malformed" in report["stderr"]


def test_corrupted_credential_secret_is_refused_before_embedding(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    payload = tmp_path / "device.bin"
    payload.write_bytes(b"device 42")
    public, private = tmp_path / "holder.pub.json", tmp_path / "holder.key.json"
    _run(capsys, "credential-new", "--payload-file", payload, "--public", public, "--private", private)
    registry = tmp_path / "registry.json"
    _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1,
         "--credential", public, "--out", registry)
    secret = json.loads(private.read_text())
    flipped = bytearray(bytes.fromhex(secret["randomness"]))
    flipped[0] = {0x00: 0x01, 0x01: 0xFF, 0xFF: 0x00}[flipped[0]]  # int8, stays ternary
    for index, changes in enumerate((
        {"randomness": bytes(flipped).hex()},  # ternary but not the opening
        {"payload": b"device 43".hex()},  # opening of another payload
        {"randomness": 7},  # wrong JSON type
    )):
        corrupted = tmp_path / f"corrupted-{index}.json"
        corrupted.write_text(json.dumps({**secret, **changes}))
        stego = tmp_path / f"stego-{index}.h264"
        code, report = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", stego,
                            "--session", "07" * 32, "--credential-private", corrupted,
                            "--registry", registry, "--issuer-public", issuer_public,
                            "--minimum-epoch", 1)
        assert code == 2 and "error:" in report["stderr"] and not stego.exists()
