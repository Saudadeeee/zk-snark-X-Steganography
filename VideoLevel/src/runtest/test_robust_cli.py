"""Role-separated CLI for the robust (semi-fragile) video proof.

Fast tests drive argparse, the profile/pins wiring, the reused issuer and
credential handlers and every configuration guard that fires *before* ffmpeg
(so they need neither ffmpeg nor local data).  Two end-to-end tests embed and
verify over short CIF clips; they are gated behind ``ffmpeg`` being present and
the (gitignored) source being on disk.  Clips are trimmed to the fewest frames
a ``recommended`` envelope fits at CIF: a registered envelope fits in 153
frames and an in-band one in 285 (``src.robust.pipeline.channel_plan``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.lattice_zk import cli as lattice_cli
from src.robust import cli
from src.robust import pipeline as robust

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "data/raw/container_cif.y4m"
FOREMAN = "data/raw/foreman_cif_300f.y4m"
# Fewest CIF frames whose channel carries a ``recommended`` envelope.
REGISTERED_FRAMES = 153
IN_BAND_FRAMES = 285
_FFMPEG = shutil.which("ffmpeg")


@pytest.fixture(autouse=True)
def _environment(monkeypatch) -> None:
    monkeypatch.setenv(cli.SYNC_KEY_ENV, "ab" * 32)


def _run(capsys, *argv: object) -> tuple[int, dict]:
    code = cli.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else {"stderr": captured.err})


def _issuer(tmp_path: Path, capsys) -> tuple[Path, Path]:
    public, private = tmp_path / "issuer.pub", tmp_path / "issuer.key"
    assert _run(capsys, "issuer-keygen", "--public", public, "--private", private)[0] == 0
    return public, private


def _credential(tmp_path: Path, capsys, name: str = "cred") -> tuple[Path, Path]:
    payload = tmp_path / f"{name}.bin"
    payload.write_bytes(b"camera-7")
    public, private = tmp_path / f"{name}.pub.json", tmp_path / f"{name}.key.json"
    assert _run(capsys, "credential-new", "--payload-file", payload,
                "--public", public, "--private", private)[0] == 0
    return public, private


def _ffmpeg_trim(source: Path, frames: int, out: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source),
                    "-frames:v", str(frames), str(out)], check=True)


# -- argparse, reuse and profile/pins wiring (no ffmpeg, no data) ---------- #

def test_issuer_and_credential_commands_reuse_the_fragile_handlers() -> None:
    parser = cli._build_parser()
    keygen = parser.parse_args(["issuer-keygen", "--public", "p", "--private", "k"])
    credential = parser.parse_args(["credential-new", "--payload-file", "f", "--public", "p", "--private", "k"])
    assert keygen.handler is lattice_cli._issuer_keygen
    assert credential.handler is lattice_cli._credential_new
    # The robust CLI commits under the fragile CLI's parameter set, so key and
    # credential artefacts are interchangeable between the two modes.
    assert cli.PARAMS is lattice_cli.PARAMS


def test_credential_is_interchangeable_with_the_fragile_cli(tmp_path, capsys) -> None:
    _public, private = _credential(tmp_path, capsys)
    credential = lattice_cli._private_credential(private)  # the fragile CLI reads it verbatim
    assert credential.commitment.is_canonical(cli.PARAMS)


@pytest.mark.parametrize("registered,step", [(True, robust.REGISTERED_STEP), (False, robust.IN_BAND_STEP)])
def test_profile_follows_the_mode(registered, step) -> None:
    profile = cli._profile(registered=registered)
    assert profile.registered is registered and profile.step == step


def test_registered_and_in_band_profiles_have_distinct_ids() -> None:
    registered = cli._profile(registered=True).profile_id(cli.PARAMS)
    in_band = cli._profile(registered=False).profile_id(cli.PARAMS)
    assert registered != in_band


def _session_args(*tail: str):
    return cli._build_parser().parse_args(
        ["session-issue", "--database", "d", "--registry", "r", "--issuer-public", "p",
         "--minimum-epoch", "1", *tail]
    )


def test_public_carrier_order_overrides_the_env_key() -> None:
    profile = cli._profile(registered=False)
    arguments = _session_args("--public-carrier-order")
    assert cli._sync_key(arguments, profile) == robust.public_sync_key(cli.PARAMS, profile)


def test_sync_key_requires_exactly_32_bytes(monkeypatch) -> None:
    profile = cli._profile(registered=False)
    arguments = _session_args()
    assert len(cli._sync_key(arguments, profile)) == 32  # the autouse 32-byte key
    monkeypatch.setenv(cli.SYNC_KEY_ENV, "ab" * 16)  # too short for the watermark
    with pytest.raises(ValueError):
        cli._sync_key(arguments, profile)
    monkeypatch.delenv(cli.SYNC_KEY_ENV)
    with pytest.raises(ValueError):
        cli._sync_key(arguments, profile)


def test_registry_sign_modes_and_holder_id_binding(tmp_path, capsys) -> None:
    _issuer_public, issuer_private = _issuer(tmp_path, capsys)
    code, signed = _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                        "--out", tmp_path / "inband.json")
    assert code == 0 and signed["mode"] == "in-band" and signed["policy"] == robust.ROBUST_POLICY
    public, _private = _credential(tmp_path, capsys)
    code, signed = _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                        "--credential", public, "--holder-id", "alice@example.org",
                        "--out", tmp_path / "registered.json")
    assert code == 0 and signed["mode"] == "registered" and signed["holder_id"] == "alice@example.org"
    # A holder id is meaningless without a registered credential.
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                "--holder-id", "alice", "--out", tmp_path / "bad.json")[0] == 2


def _registry_and_grant(tmp_path: Path, capsys) -> tuple[tuple[object, ...], str]:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1, "--out", registry)
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1)
    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)
    return verifier, grant["challenge"]


def test_embed_config_errors_fire_before_ffmpeg(tmp_path, capsys, monkeypatch) -> None:
    verifier, challenge = _registry_and_grant(tmp_path, capsys)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    missing = tmp_path / "nope.y4m"  # a valid error fires before the cover is read
    stego = tmp_path / "stego.mp4"
    base = ["embed", "--video", missing, "--output", stego, *verifier]
    # Exactly one of a payload (in-band) or a credential (registered).
    assert _run(capsys, *base, "--session", challenge, "--payload-file", payload,
                "--credential-private", tmp_path / "x.json")[0] == 2
    # In-band without somewhere to keep the opening.
    assert _run(capsys, *base, "--session", challenge, "--payload-file", payload)[0] == 2
    # A malformed session challenge.
    assert _run(capsys, *base, "--session", "zz", "--payload-file", payload,
                "--opening-out", tmp_path / "o.json")[0] == 2
    # No carrier key at all.
    monkeypatch.delenv(cli.SYNC_KEY_ENV)
    assert _run(capsys, *base, "--session", challenge, "--payload-file", payload,
                "--opening-out", tmp_path / "o2.json")[0] == 2
    assert not stego.exists()


def test_embed_refuses_to_overwrite_before_proving(tmp_path, capsys) -> None:
    verifier, challenge = _registry_and_grant(tmp_path, capsys)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    stego, opening = tmp_path / "stego.mp4", tmp_path / "opening.json"
    embed = ["embed", "--video", tmp_path / "nope.y4m", "--output", stego, "--session", challenge,
             "--payload-file", payload, "--opening-out", opening, *verifier]
    opening.write_text("{}")
    assert _run(capsys, *embed)[0] == 2 and not stego.exists()  # opening already exists
    opening.unlink()
    stego.write_bytes(b"older video")
    assert _run(capsys, *embed)[0] == 2  # output already exists
    assert stego.read_bytes() == b"older video" and not opening.exists()


def test_verifier_config_fails_closed(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1, "--out", registry)
    base = ("--database", database, "--registry", registry, "--issuer-public", issuer_public)
    assert _run(capsys, "session-issue", *base, "--minimum-epoch", 2)[0] == 2  # rollback floor
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1,
                "--out", registry)[0] == 2  # never overwrites
    other_public = tmp_path / "other.pub"
    _run(capsys, "issuer-keygen", "--public", other_public, "--private", tmp_path / "other.key")
    assert _run(capsys, "session-issue", "--database", database, "--registry", registry,
                "--issuer-public", other_public, "--minimum-epoch", 1)[0] == 2  # wrong issuer


def test_key_pairs_are_never_half_written(tmp_path, capsys) -> None:
    public, private = tmp_path / "issuer.pub", tmp_path / "issuer.key"
    private.write_bytes(b"existing secret")
    assert _run(capsys, "issuer-keygen", "--public", public, "--private", private)[0] == 2
    assert not public.exists() and private.read_bytes() == b"existing secret"


# -- end to end over short clips (needs ffmpeg and local data) ------------- #

@pytest.mark.skipif(_FFMPEG is None, reason="robust verify decodes with ffmpeg")
@pytest.mark.needs_data(CONTAINER)
def test_registered_flow_end_to_end(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    public, private = _credential(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 1,
                "--credential", public, "--out", registry)[1]["mode"] == "registered"
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1,
                "--credential", public)
    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)

    cover = tmp_path / "cover.y4m"
    _ffmpeg_trim(ROOT / CONTAINER, REGISTERED_FRAMES, cover)
    stego = tmp_path / "stego.mp4"
    base = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 1)
    code, embedded = _run(capsys, "embed", "--video", cover, "--output", stego,
                          "--session", grant["challenge"], "--credential-private", private, *base)
    assert code == 0 and embedded["mode"] == "registered" and embedded["envelope_bytes"] == 8_741
    # The robust mode re-encodes: the stego is a fresh file distinct from the cover.
    assert stego.exists() and stego.read_bytes() != cover.read_bytes()

    code, verified = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 0 and verified["valid"] and verified["mode"] == "registered"
    assert verified["statement_id"] == embedded["statement_id"]
    assert verified["bad_frames"] == [] and verified["flagged_cells"] == 0

    # The one-use session is consumed, so a replay of the same video is rejected.
    code, replay = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 1 and not replay["valid"]

    # A credential the registry never registered cannot even resolve pins.
    _stranger_public, stranger_private = _credential(tmp_path, capsys, name="stranger")
    code, _ = _run(capsys, "embed", "--video", cover, "--output", tmp_path / "x.mp4",
                   "--session", grant["challenge"], "--credential-private", stranger_private, *base)
    assert code == 2


@pytest.mark.skipif(_FFMPEG is None, reason="robust verify decodes with ffmpeg")
@pytest.mark.needs_data(FOREMAN)
def test_in_band_flow_end_to_end_with_disclosure(tmp_path, capsys) -> None:
    issuer_public, issuer_private = _issuer(tmp_path, capsys)
    registry, database = tmp_path / "registry.json", tmp_path / "sessions.sqlite3"
    assert _run(capsys, "registry-sign", "--issuer-private", issuer_private, "--epoch", 2,
                "--out", registry)[1]["mode"] == "in-band"
    verifier = ("--registry", registry, "--issuer-public", issuer_public, "--minimum-epoch", 2)
    _, grant = _run(capsys, "session-issue", "--database", database, *verifier)

    cover = tmp_path / "cover.y4m"
    _ffmpeg_trim(ROOT / FOREMAN, IN_BAND_FRAMES, cover)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hidden record")
    stego, opening = tmp_path / "stego.mp4", tmp_path / "opening.json"
    code, embedded = _run(capsys, "embed", "--video", cover, "--output", stego,
                          "--session", grant["challenge"], "--payload-file", payload,
                          "--opening-out", opening, *verifier)
    assert code == 0 and embedded["mode"] == "in-band" and embedded["envelope_bytes"] == 16_421
    assert b"hidden record" not in stego.read_bytes()
    assert json.loads(opening.read_text())["payload"] == b"hidden record".hex()

    envelope = tmp_path / "envelope.bin"
    code, verified = _run(capsys, "verify", "--video", stego, "--database", database,
                          "--envelope-out", envelope, *verifier)
    assert code == 0 and verified["valid"] and verified["statement_id"] == embedded["statement_id"]
    assert envelope.exists()
    code, replay = _run(capsys, "verify", "--video", stego, "--database", database, *verifier)
    assert code == 1 and not replay["valid"]

    # The verified envelope lets a recipient check a zero-knowledge disclosure of
    # the payload; the opening randomness never appears in the disclosure.
    nonce = "5a" * 32
    disclosure = tmp_path / "disclosure.bin"
    assert _run(capsys, "disclose", "--opening", opening, "--statement-id",
                embedded["statement_id"], "--nonce", nonce, "--out", disclosure)[0] == 0
    randomness = bytes.fromhex(json.loads(opening.read_text())["randomness"])
    assert randomness not in disclosure.read_bytes()

    check = ("disclosure-verify", "--envelope", envelope, "--disclosure", disclosure,
             "--statement-id", verified["statement_id"])
    code, report = _run(capsys, *check, "--nonce", nonce)
    assert code == 0 and report["valid"] and report["payload_hex"] == b"hidden record".hex()
    code, report = _run(capsys, *check, "--nonce", "5b" * 32)
    assert code == 1 and not report["valid"]
