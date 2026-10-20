"""Role-separated CLI for the BDLOP video proof, over the stand-in channel."""

from __future__ import annotations

import json
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
