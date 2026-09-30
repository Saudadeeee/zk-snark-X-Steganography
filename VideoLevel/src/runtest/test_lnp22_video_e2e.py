"""Fast tests for the explicitly experimental LNP22 video transport envelope."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = ROOT / "benchmark" / "lnp22_context_probe"
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

from video_e2e import (
    SYNC_KEY_ENV,
    ProcessTreeRSSSampler,
    _build_parser,
    _emit_progress_event,
    _run_go,
    _sync_key_from_environment,
    _verify_from_video,
    decode_video_probe_payload,
    embed_and_verify,
    encode_video_probe_payload,
    make_video_probe_statement,
)

from src.blind_payload_chunks import pack_payload_chunks


def test_video_probe_envelope_round_trips_canonical_statement_and_proof():
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"demo message",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256="44" * 32,
    )
    encoded = encode_video_probe_payload(statement, b"proof-bytes", b"demo message")

    decoded = decode_video_probe_payload(encoded)

    assert decoded.statement_bytes == statement
    assert decoded.proof_bytes == b"proof-bytes"
    assert decoded.payload_bytes == b"demo message"


def test_video_probe_statement_binds_all_video_context_fields():
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"demo message",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256="44" * 32,
    )

    decoded = decode_video_probe_payload(encode_video_probe_payload(statement, b"p", b"demo message"))

    assert decoded.context["canonical_video_sha256"] == "22" * 32
    assert "cover_hash" not in decoded.context
    assert decoded.context["version"] == 3
    assert decoded.context["positions_hash"] == "33" * 32
    assert decoded.context["relation_id"] == "44" * 32
    assert decoded.context["payload_commitment"]
    assert decoded.context["registry_binding"] == "unregistered-experimental-probe"
    assert (
        decoded.context["codec_policy"]["video_commitment"]
        == "canonical-h264-carrier-normalized-sha256-v1"
    )
    assert decoded.context["security_scope"] == (
        "knowledge of the verifier-pinned short linear-relation witness, "
        "bound to this public context"
    )


@pytest.mark.parametrize("statement", [b"", b"not-json", b"{}", b"{} "])
def test_video_probe_encoder_rejects_noncanonical_statement(statement):
    with pytest.raises(ValueError):
        encode_video_probe_payload(statement, b"proof", b"payload")


def test_video_probe_decoder_rejects_truncation_and_length_mismatch():
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"demo message",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256="44" * 32,
    )
    encoded = encode_video_probe_payload(statement, b"proof", b"demo message")

    with pytest.raises(ValueError):
        decode_video_probe_payload(encoded[:-1])
    with pytest.raises(ValueError):
        decode_video_probe_payload(encoded + b"trailing")


def test_video_probe_statement_rejects_mutation():
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"demo message",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256="44" * 32,
    )
    tampered = statement.replace(
        b'"canonical_video_sha256":"' + b"2" * 64,
        b'"canonical_video_sha256":"' + b"3" * 64,
    )

    with pytest.raises(ValueError):
        decode_video_probe_payload(encode_video_probe_payload(tampered, b"proof", b"demo message"))


def test_video_probe_requires_high_entropy_sized_sync_key(monkeypatch):
    monkeypatch.delenv(SYNC_KEY_ENV, raising=False)
    with pytest.raises(ValueError, match=SYNC_KEY_ENV):
        _sync_key_from_environment()

    monkeypatch.setenv(SYNC_KEY_ENV, "a1" * 16)
    assert _sync_key_from_environment() == bytes.fromhex("a1" * 16)


def test_go_child_process_does_not_inherit_blind_sync_key(monkeypatch):
    monkeypatch.setenv(SYNC_KEY_ENV, "b2" * 32)
    monkeypatch.setenv("ZKSTEGOLNP22_API_TOKEN", "test-api-secret")
    monkeypatch.setenv("ZKSTEGOLNP22_WITNESS_PATH", "C:/private/witness.json")
    captured = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return CompletedProcess(args=[], returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr("video_e2e.subprocess.run", fake_run)
    assert _run_go(["-h"]) == {}
    assert SYNC_KEY_ENV not in captured["env"]
    assert "ZKSTEGOLNP22_API_TOKEN" not in captured["env"]
    assert "ZKSTEGOLNP22_WITNESS_PATH" not in captured["env"]


def test_video_e2e_refuses_to_overwrite_any_requested_artifact(tmp_path):
    source = tmp_path / "cover.h264"
    output = tmp_path / "stego.h264"
    relation = tmp_path / "relation.json"
    report = tmp_path / "report.json"
    source.write_bytes(b"not parsed because output pre-exists")
    output.write_bytes(b"preserve existing video")

    with pytest.raises(FileExistsError):
        embed_and_verify(
            source,
            output,
            report,
            relation_path=relation,
            witness_path=tmp_path / "witness.json",
            trusted_relation_sha256="44" * 32,
        )

    assert output.read_bytes() == b"preserve existing video"


@pytest.mark.parametrize(
    "proof_mode, prove_flag",
    [("augmented", "-fixed-prove"), ("compact", "-fixed-compact-prove")],
)
def test_video_e2e_uses_segmented_carrier_context_and_reports_published_hash(
    monkeypatch, tmp_path, capsys, proof_mode, prove_flag
):
    source = tmp_path / "cover.h264"
    output = tmp_path / "stego.h264"
    relation_output = tmp_path / "relation.json"
    report_output = tmp_path / "report.json"
    witness_input = tmp_path / "witness.json"
    source.write_bytes(b"source video")
    relation_output.write_text('{"relation_sha256":"44' + '44' * 31 + '"}', encoding="utf-8")
    witness_input.write_text("private setup witness", encoding="utf-8")
    monkeypatch.setattr("video_e2e._sync_key_from_environment", lambda: b"k" * 32)
    derive_calls = []
    embed_calls = []
    go_calls = []

    def fake_go(args, **_kwargs):
        go_calls.append(args)
        proof_path = Path(args[args.index("-proof-out") + 1])
        proof_path.write_bytes(b"proof")
        return {"proof_bytes": 5, "prove_ms": 2.0}

    monkeypatch.setattr("video_e2e._run_go", fake_go)
    def fake_derive(_source, chunks, *_args, **kwargs):
        derive_calls.append((chunks, kwargs))
        kwargs["progress_callback"](
            {
                "phase": "carrier_context",
                "event": "segment_completed",
                "segment_index": 0,
                "segments_total": 1,
            }
        )
        return SimpleNamespace(
            positions_hash="55" * 32,
            canonical_video_sha256="66" * 32,
            segments_used=len(chunks),
            frames_per_segment=kwargs["frames_per_segment"],
        )

    monkeypatch.setattr("video_e2e.derive_chunked_video_context", fake_derive)

    def fake_embed(_source, candidate, payload, *_args, **kwargs):
        payload_chunks = pack_payload_chunks(
            payload,
            chunk_size=kwargs["chunk_size"],
        )
        embed_calls.append((payload_chunks, kwargs))
        kwargs["progress_callback"](
            {
                "phase": "embed",
                "event": "segment_completed",
                "segment_index": 0,
                "segments_total": 1,
            }
        )
        Path(candidate).write_bytes(b"strict-decoded stego bytes")
        return SimpleNamespace(
            segments_used=len(payload_chunks),
            carriers_used=sum((14 + len(chunk)) * 8 for chunk in payload_chunks),
        )

    monkeypatch.setattr("video_e2e.embed_chunked_video_payload", fake_embed)
    verify_calls = []

    def fake_verify(*_args, **kwargs):
        verify_calls.append(kwargs)
        return {
            "valid": True,
            "proof_format": "LNPF-v1" if proof_mode == "augmented" else "LNPF-v2",
            "statement_id": "77" * 32,
            "proof_bytes": 5,
            "payload_bytes": len(b"LNP22 experimental proof transport only; not an application claim."),
            "carriers_used": 900,
            "verify_ms": 3.0,
        }

    monkeypatch.setattr("video_e2e._verify_from_video", fake_verify)

    report = embed_and_verify(
        source,
        output,
        report_output,
        relation_path=relation_output,
        witness_path=witness_input,
        trusted_relation_sha256="44" * 32,
        proof_mode=proof_mode,
    )

    assert output.read_bytes() == b"strict-decoded stego bytes"
    assert report["output_video_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert report["relation_artifact"] == str(relation_output.resolve())
    assert report["proof_mode"] == proof_mode
    assert report["peak_rss_mb"] > 0
    assert all("-fixed-setup" not in args for args in go_calls)
    assert all(prove_flag in args for args in go_calls)
    assert all("-relation-in" in args and "-witness-in" in args for args in go_calls)
    assert verify_calls[0]["trusted_relation_sha256"] == "44" * 32
    assert len(derive_calls) == 1
    assert len(embed_calls) == 1
    assert len(derive_calls[0][0]) == len(embed_calls[0][0])
    progress = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert {event["phase"] for event in progress} >= {"carrier_context", "embed"}
    assert all("timestamp_utc" in event for event in progress)
    assert any(event["event"] == "segment_completed" for event in progress)
    carrier_completed = next(
        event
        for event in progress
        if event["phase"] == "carrier_context" and event["event"] == "completed"
    )
    assert carrier_completed["segments_used"] == len(derive_calls[0][0])
    assert "segments_total" not in carrier_completed
    embed_completed = next(
        event
        for event in progress
        if event["phase"] == "embed" and event["event"] == "completed"
    )
    assert embed_completed["segments_used"] == len(embed_calls[0][0])
    assert "segments_total" not in embed_completed


def test_progress_event_is_redacted_jsonl(capsys):
    _emit_progress_event(
        {
            "phase": "carrier_context",
            "event": "segment_started",
            "segment_index": 2,
            "segments_total": 30,
        }
    )

    event = json.loads(capsys.readouterr().err)
    assert event["phase"] == "carrier_context"
    assert event["event"] == "segment_started"
    assert event["segment_index"] == 2
    assert event["segments_total"] == 30
    assert set(event) == {
        "event",
        "phase",
        "segment_index",
        "segments_total",
        "timestamp_utc",
    }

    with pytest.raises(ValueError, match="unsupported fields"):
        _emit_progress_event({"phase": "x", "event": "y", "witness": "secret"})

    with pytest.raises(TypeError, match="string phase and event"):
        _emit_progress_event({"phase": 1, "event": "segment_started"})


def test_process_tree_rss_sampler_sums_processes_and_tracks_peak():
    class FakeProcess:
        def __init__(self, pid, rss, children=()):
            self.pid = pid
            self.rss = rss
            self._children = list(children)

        def children(self, recursive):
            assert recursive is True
            return list(self._children)

        def memory_info(self):
            return SimpleNamespace(rss=self.rss)

    child = FakeProcess(2, 40)
    root = FakeProcess(1, 100, [child, child])
    sampler = ProcessTreeRSSSampler(process=root)

    assert sampler.sample_once() == 140
    child.rss = 10
    root.rss = 20
    assert sampler.sample_once() == 30
    assert sampler.peak_rss_bytes == 140


def test_process_tree_rss_sampler_marks_child_enumeration_denial_incomplete():
    class FakeProcess:
        pid = 1

        def children(self, recursive):
            assert recursive is True
            raise psutil.AccessDenied(self.pid)

        def memory_info(self):
            return SimpleNamespace(rss=100)

    sampler = ProcessTreeRSSSampler(process=FakeProcess())

    assert sampler.sample_once() == 100
    assert sampler.rss_sampling_errors_observed is True
    assert sampler.rss_sampling_error_count == 1


def test_process_tree_rss_sampler_marks_inaccessible_child_memory_incomplete():
    class FakeProcess:
        def __init__(self, pid, rss=None):
            self.pid = pid
            self.rss = rss

        def children(self, recursive):
            assert recursive is True
            return [FakeProcess(2)]

        def memory_info(self):
            if self.rss is None:
                raise psutil.AccessDenied(self.pid)
            return SimpleNamespace(rss=self.rss)

    sampler = ProcessTreeRSSSampler(process=FakeProcess(1, 100))

    assert sampler.sample_once() == 100
    assert sampler.rss_sampling_errors_observed is True
    assert sampler.rss_sampling_error_count == 1


def test_process_tree_rss_sampler_ignores_child_exiting_during_sample():
    class FakeProcess:
        def __init__(self, pid, rss=None):
            self.pid = pid
            self.rss = rss

        def children(self, recursive):
            assert recursive is True
            return [FakeProcess(2)]

        def memory_info(self):
            if self.rss is None:
                raise psutil.NoSuchProcess(self.pid)
            return SimpleNamespace(rss=self.rss)

    sampler = ProcessTreeRSSSampler(process=FakeProcess(1, 100))

    assert sampler.sample_once() == 100
    assert sampler.rss_sampling_errors_observed is False
    assert sampler.rss_sampling_error_count == 0


@pytest.mark.parametrize("interval", [0, float("nan"), float("inf")])
def test_process_tree_rss_sampler_rejects_nonfinite_or_nonpositive_interval(interval):
    with pytest.raises(ValueError, match="finite positive"):
        ProcessTreeRSSSampler(sample_interval_seconds=interval)


def test_process_tree_rss_sampler_stops_sampling_thread_on_context_exit():
    class FakeProcess:
        pid = 1

        def children(self, recursive):
            assert recursive is True
            return []

        def memory_info(self):
            return SimpleNamespace(rss=100)

    sampler = ProcessTreeRSSSampler(
        process=FakeProcess(),
        sample_interval_seconds=10,
    )

    with sampler:
        assert sampler._thread is not None
        assert sampler._thread.is_alive()

    assert sampler._thread is None
    assert sampler.peak_rss_bytes == 100


def test_video_e2e_rejects_relation_not_matching_verifier_pin(tmp_path, monkeypatch):
    source = tmp_path / "cover.h264"
    output = tmp_path / "stego.h264"
    relation = tmp_path / "relation.json"
    witness = tmp_path / "witness.json"
    report = tmp_path / "report.json"
    source.write_bytes(b"source video")
    relation.write_text('{"relation_sha256":"55' + '55' * 31 + '"}', encoding="utf-8")
    witness.write_text("private witness", encoding="utf-8")
    monkeypatch.setattr("video_e2e._sync_key_from_environment", lambda: b"k" * 32)
    monkeypatch.setattr("video_e2e._run_go", lambda *_args, **_kwargs: pytest.fail("must reject before proving"))

    with pytest.raises(ValueError, match="verifier pin"):
        embed_and_verify(
            source,
            output,
            report,
            relation_path=relation,
            witness_path=witness,
            trusted_relation_sha256="44" * 32,
        )


def test_embed_cli_requires_preprovisioned_relation_witness_and_trust_pin():
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["embed", "--video", "in.h264", "--output", "out.h264"])

    args = parser.parse_args(
        [
            "embed",
            "--video", "in.h264",
            "--output", "out.h264",
            "--report-output", "report.json",
            "--relation", "relation.json",
            "--witness", "witness.json",
            "--trusted-relation-sha256", "44" * 32,
            "--session-challenge-hex", "66" * 32,
        ]
    )

    assert args.relation == Path("relation.json")
    assert args.witness == Path("witness.json")
    assert args.trusted_relation_sha256 == "44" * 32
    assert args.proof_mode == "augmented"

    compact_args = parser.parse_args(
        [
            "embed",
            "--video", "in.h264",
            "--output", "out.h264",
            "--report-output", "report.json",
            "--relation", "relation.json",
            "--witness", "witness.json",
            "--trusted-relation-sha256", "44" * 32,
            "--session-challenge-hex", "66" * 32,
            "--proof-mode", "compact",
        ]
    )
    assert compact_args.proof_mode == "compact"

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "verify",
                "--video", "out.h264",
                "--relation", "relation.json",
                "--trusted-relation-sha256", "44" * 32,
            ]
        )
    verify_args = parser.parse_args(
        [
            "verify",
            "--video", "out.h264",
            "--relation", "relation.json",
            "--trusted-relation-sha256", "44" * 32,
            "--session-database", "sessions.sqlite3",
            "--session-context-binding-hex", "55" * 32,
        ]
    )
    assert verify_args.session_database == Path("sessions.sqlite3")
    assert verify_args.session_context_binding_hex == "55" * 32


def test_video_verifier_uses_only_extracted_chunk_context(tmp_path, monkeypatch):
    relation = tmp_path / "relation.json"
    relation.write_text("{}", encoding="utf-8")
    trusted_relation_hash = "44" * 32
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"payload",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256=trusted_relation_hash,
    )
    encoded = encode_video_probe_payload(
        statement, b"LNPF\x01" + b"\0" * 6, b"payload"
    )
    extraction_progress = []

    def fake_extract(*_args, progress_callback=None, **_kwargs):
        assert progress_callback is not None
        progress_callback(
            {"phase": "extract", "event": "segments_ready", "segments_total": 2}
        )
        return SimpleNamespace(
            payload=encoded,
            positions_hash="33" * 32,
            canonical_video_sha256="22" * 32,
            carriers_used=512,
            segments_used=2,
        )

    monkeypatch.setattr("video_e2e.extract_chunked_video_payload", fake_extract)
    go_call = {}

    def fake_go(args, **kwargs):
        go_call.update(args=args, statement=kwargs["stdin"])
        return {"valid": True, "verify_ms": 4.0}

    monkeypatch.setattr("video_e2e._run_go", fake_go)

    result = _verify_from_video(
        tmp_path / "video-only.h264",
        relation_path=relation,
        trusted_relation_sha256=trusted_relation_hash,
        sync_key=b"k" * 32,
        progress_callback=extraction_progress.append,
    )

    assert result["valid"] is True
    assert result["positions_hash"] == "33" * 32
    assert result["canonical_video_sha256"] == "22" * 32
    assert go_call["statement"] == statement
    assert "-fixed-verify" in go_call["args"]
    assert extraction_progress == [
        {"phase": "extract", "event": "segments_ready", "segments_total": 2}
    ]


@pytest.mark.parametrize(
    "proof_version, verify_flag",
    [(1, "-fixed-verify"), (2, "-fixed-compact-verify")],
)
def test_video_verifier_routes_by_embedded_proof_format(
    tmp_path, monkeypatch, proof_version, verify_flag
):
    relation = tmp_path / "relation.json"
    relation.write_text("{}", encoding="utf-8")
    relation_pin = "44" * 32
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"payload",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256=relation_pin,
    )
    proof = b"LNPF" + bytes([proof_version]) + b"\0" * 6
    encoded = encode_video_probe_payload(statement, proof, b"payload")
    monkeypatch.setattr(
        "video_e2e.extract_chunked_video_payload",
        lambda *_args, **_kwargs: SimpleNamespace(
            payload=encoded,
            positions_hash="33" * 32,
            canonical_video_sha256="22" * 32,
            carriers_used=512,
            segments_used=2,
        ),
    )
    go_call = {}

    def fake_go(args, **kwargs):
        go_call.update(args=args, statement=kwargs["stdin"])
        return {"valid": True, "verify_ms": 4.0}

    monkeypatch.setattr("video_e2e._run_go", fake_go)
    result = _verify_from_video(
        tmp_path / "video-only.h264",
        relation_path=relation,
        trusted_relation_sha256=relation_pin,
        sync_key=b"k" * 32,
    )

    assert result["proof_format"] == f"LNPF-v{proof_version}"
    assert verify_flag in go_call["args"]
    assert go_call["statement"] == statement


def test_video_verifier_rejects_unknown_embedded_proof_version(tmp_path, monkeypatch):
    relation = tmp_path / "relation.json"
    relation.write_text("{}", encoding="utf-8")
    relation_pin = "44" * 32
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"payload",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256=relation_pin,
    )
    encoded = encode_video_probe_payload(
        statement, b"LNPF\x7f" + b"\0" * 6, b"payload"
    )
    monkeypatch.setattr(
        "video_e2e.extract_chunked_video_payload",
        lambda *_args, **_kwargs: SimpleNamespace(
            payload=encoded,
            positions_hash="33" * 32,
            canonical_video_sha256="22" * 32,
            carriers_used=512,
            segments_used=2,
        ),
    )
    monkeypatch.setattr(
        "video_e2e._run_go",
        lambda *_args, **_kwargs: pytest.fail("must reject unknown proof version"),
    )

    with pytest.raises(ValueError, match="unsupported embedded proof format"):
        _verify_from_video(
            tmp_path / "video-only.h264",
            relation_path=relation,
            trusted_relation_sha256=relation_pin,
            sync_key=b"k" * 32,
        )


def test_video_verifier_rejects_segment_position_commitment_mismatch(
    tmp_path, monkeypatch
):
    relation = tmp_path / "relation.json"
    relation.write_text("{}", encoding="utf-8")
    trusted_relation_hash = "44" * 32
    statement = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"payload",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256=trusted_relation_hash,
    )
    encoded = encode_video_probe_payload(statement, b"proof", b"payload")
    monkeypatch.setattr(
        "video_e2e.extract_chunked_video_payload",
        lambda *_args, **_kwargs: SimpleNamespace(
            payload=encoded,
            positions_hash="55" * 32,
            canonical_video_sha256="22" * 32,
            carriers_used=512,
            segments_used=2,
        ),
    )
    monkeypatch.setattr("video_e2e._run_go", lambda *_args, **_kwargs: pytest.fail("must reject before proof verify"))

    with pytest.raises(ValueError, match="carrier positions"):
        _verify_from_video(
            tmp_path / "video-only.h264",
            relation_path=relation,
            trusted_relation_sha256=trusted_relation_hash,
            sync_key=b"k" * 32,
        )


@pytest.mark.skipif(shutil.which("go") is None, reason="Go is required for LNP22 probe")
def test_probe_wrapper_runs_real_lnp22_prove_and_verify(tmp_path):
    relation = tmp_path / "relation.json"
    witness = tmp_path / "witness.json"
    proof = tmp_path / "proof.lnpf"
    setup = _run_go([
        "-fixed-setup",
        "-relation-out", str(relation),
        "-witness-out", str(witness),
    ])
    relation_pin = setup["relation_sha256"]
    context = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"demo message",
        canonical_video_sha256="22" * 32,
        positions_hash="33" * 32,
        relation_sha256=relation_pin,
    )
    _run_go(
        [
            "-fixed-prove",
            "-relation-in", str(relation),
            "-witness-in", str(witness),
            "-proof-out", str(proof),
        ],
        stdin=context,
    )
    verified = _run_go(
        [
            "-fixed-verify",
            "-relation-in", str(relation),
            "-proof-in", str(proof),
            "-trusted-base-relation-sha256", relation_pin,
        ],
        stdin=context,
    )

    assert verified["valid"] is True
    assert proof.stat().st_size == 33_803

    changed_context = make_video_probe_statement(
        session_id=bytes(range(32)),
        payload=b"demo message",
        canonical_video_sha256="55" * 32,
        positions_hash="33" * 32,
        relation_sha256=relation_pin,
    )
    with pytest.raises(RuntimeError, match="LNP22 CLI failed"):
        _run_go(
            [
                "-fixed-verify",
                "-relation-in", str(relation),
                "-proof-in", str(proof),
                "-trusted-base-relation-sha256", relation_pin,
            ],
            stdin=changed_context,
        )
