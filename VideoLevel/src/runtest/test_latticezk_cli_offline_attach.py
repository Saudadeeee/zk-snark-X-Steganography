"""CLI flows for the offline epoch mode and the payload range attachment (stand-in channel)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.lattice_zk import cli
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk import video_proof
from src.runtest.test_latticezk_cli import _cover, _issuer, _run
from src.runtest.test_latticezk_video_pipeline import FakeTransport


@pytest.fixture(autouse=True)
def _environment(monkeypatch) -> None:
    monkeypatch.setenv(cli.SYNC_KEY_ENV, "ab" * 32)
    # The pipeline selects the transport per profile; the stand-in ignores it.
    monkeypatch.setattr(pipeline, "_default_transport", lambda profile=None: FakeTransport())


def test_offline_epoch_flow_rejects_replay_per_verifier(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, beacon = tmp_path / "registry.json", tmp_path / "epoch.json"
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                "--out", registry)[1]["codec_policy"] == "v2"
    code, issued = _run(capsys, "epoch-issue", "--issuer-private", issuer_private, "--out", beacon,
                        "--window-seconds", 3600)
    assert code == 0 and issued["window_seconds"] == 3600 and len(issued["challenge"]) == 64
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 2)

    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    stego, opening = tmp_path / "stego.h264", tmp_path / "opening.json"
    code, embedded = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", stego,
                          "--epoch-beacon", beacon, "--payload-file", payload,
                          "--opening-out", opening, *verifier)
    assert code == 0 and embedded["session_mode"] == "offline-epoch"
    assert embedded["envelope_bytes"] == video_proof.envelope_size(cli.PARAMS)

    ledger_a, ledger_b = tmp_path / "verifier-a.sqlite", tmp_path / "verifier-b.sqlite"
    code, verified = _run(capsys, "verify", "--video", stego, "--database", ledger_a,
                          "--epoch-beacon", beacon, *verifier)
    assert code == 0 and verified["valid"] and verified["session_mode"] == "offline-epoch"
    assert verified["statement_id"] == embedded["statement_id"]
    code, replay = _run(capsys, "verify", "--video", stego, "--database", ledger_a,
                        "--epoch-beacon", beacon, *verifier)
    assert code == 1 and not replay["valid"] and "replay" in replay["reason"]
    # Another verifier with its own ledger accepts the same video.
    code, elsewhere = _run(capsys, "verify", "--video", stego, "--database", ledger_b,
                           "--epoch-beacon", beacon, *verifier)
    assert code == 0 and elsewhere["valid"]
    # Both session arguments, or neither, is an error.
    code, report = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", tmp_path / "x.h264",
                        "--payload-file", payload, "--opening-out", tmp_path / "x.json", *verifier)
    assert code == 2 and "exactly one of --session or --epoch-beacon" in report["stderr"]
    # A beacon signed by another issuer is refused before anything is read.
    other_public, other_private = tmp_path / "other.pub", tmp_path / "other.key"
    assert _run(capsys, "issuer-keygen", "--public", other_public, "--private", other_private)[0] == 0
    forged = tmp_path / "forged.json"
    assert _run(capsys, "epoch-issue", "--issuer-private", other_private, "--out", forged)[0] == 0
    code, report = _run(capsys, "verify", "--video", stego, "--database", ledger_b,
                        "--epoch-beacon", forged, *verifier)
    assert code == 2 and "epoch beacon signature" in report["stderr"]


def test_payload_range_attachment_flow(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    length = 20
    code, signed = _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                        "--out", registry, "--payload-range-bytes", length)
    assert code == 0 and signed["payload_range_bytes"] == length
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 2,
                "--payload-range-bytes", length)
    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)

    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    stego, opening = tmp_path / "stego.h264", tmp_path / "opening.json"
    code, embedded = _run(capsys, "embed", "--video", _cover(tmp_path), "--output", stego,
                          "--session", grant["challenge"], "--payload-file", payload,
                          "--opening-out", opening, *verifier)
    attachment = video_proof.payload_range_attachment(cli.PARAMS, length)
    assert code == 0 and embedded["payload_padded"] is True
    assert embedded["envelope_bytes"] == video_proof.envelope_size(cli.PARAMS, attachment=attachment)
    record = json.loads(opening.read_text())
    assert record["padded"] is True and bytes.fromhex(record["payload"]) == video_proof.pad_payload(
        b"hidden record", length
    )

    envelope = tmp_path / "envelope.bin"
    code, verified = _run(capsys, "verify", "--video", stego, "--database", database,
                          "--envelope-out", envelope, *verifier)
    assert code == 0 and verified["valid"]
    # A verifier that does not pin the attachment rejects the video.
    plain = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 2)
    code, report = _run(capsys, "session-issue", "--database", database, *plain)
    assert code == 2  # the plain profile is not the registered relation

    nonce = "ab" * 32
    disclosure = tmp_path / "disclosure.bin"
    assert _run(capsys, "disclose", "--opening", opening, "--statement-id", verified["statement_id"],
                "--nonce", nonce, "--out", disclosure)[0] == 0
    code, checked = _run(capsys, "disclosure-verify", "--envelope", envelope, "--disclosure", disclosure,
                         "--statement-id", verified["statement_id"], "--nonce", nonce,
                         "--payload-range-bytes", length)
    assert code == 0 and checked["valid"]
    assert bytes.fromhex(checked["payload_unpadded_hex"]) == b"hidden record"
    # Without the pinned length the envelope cannot even be decoded.
    code, report = _run(capsys, "disclosure-verify", "--envelope", envelope, "--disclosure", disclosure,
                        "--statement-id", verified["statement_id"], "--nonce", nonce)
    assert code == 2


def test_registered_profile_refuses_the_attachment(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    payload = tmp_path / "device.bin"
    payload.write_bytes(b"device 42")
    public, private = tmp_path / "holder.pub.json", tmp_path / "holder.key.json"
    assert _run(capsys, "credential-new", "--payload-file", payload, "--public", public,
                "--private", private)[0] == 0
    code, report = _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1,
                        "--credential", public, "--out", tmp_path / "r.json", "--payload-range-bytes", 20)
    assert code == 2 and "in-band mode only" in report["stderr"]
