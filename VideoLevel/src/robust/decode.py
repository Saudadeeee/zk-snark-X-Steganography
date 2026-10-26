"""ffmpeg I/O for the robust mode: decode to 8-bit 4:2:0 planes, encode them back.

Any input ffmpeg decodes is accepted (H.264 CAVLC or CABAC, HEVC, Y4M, ...).
Frames are taken in presentation order with ``-fps_mode passthrough`` so no
frame is duplicated or dropped by a frame-rate conversion.

Hygiene for untrusted paths and files (the verifier reads what it is sent):

* paths are resolved and passed as absolute ``file:`` URLs, so a name that
  starts with ``-`` is never read as an option, ``-`` never means stdin and a
  ``concat:`` / ``http:`` prefix is inert; ``-protocol_whitelist`` restricts
  ffmpeg to ``file`` and ``pipe`` as well (checked against ffmpeg 8.0);
* ``ffprobe`` runs first and its fields are validated; a clip whose luma would
  exceed ``MAX_LUMA_SAMPLES`` is refused before decoding, and the decoder is
  told to stop after that many frames in any case, so memory is bounded by
  the constant and not by the file;
* every child process runs with ``-nostdin``, a closed stdin and a
  ``SUBPROCESS_TIMEOUT`` second limit (``subprocess.TimeoutExpired``);
* ``encode`` never overwrites: an existing output path is refused in Python
  (ffmpeg's ``-n`` exits with status 0 on an existing file, so it is only a
  second line of defence).
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Decode budget: 2160p x 3000 frames of luma (~24.9 G samples).  Decoding
# holds about three bytes per luma sample (raw 4:2:0 bytes plus the planes),
# so this is a denial-of-service bound, not a comfort bound; verifiers may
# pass a tighter ``max_luma_samples``.
MAX_LUMA_SAMPLES = 3840 * 2160 * 3000
# The fingerprint header stores width and height in 16 bits; 16384 is 2x 8K.
MAX_DIMENSION = 16384
SUBPROCESS_TIMEOUT = 600.0
DEFAULT_FRAME_RATE = "25/1"
_PROTOCOLS = "file,pipe"
_FRAME_RATE = re.compile(r"^[1-9][0-9]{0,8}(?:/[1-9][0-9]{0,8})?$")


def file_url(path: str | Path) -> str:
    """Absolute ``file:`` URL ffmpeg cannot mistake for an option or protocol."""
    return f"file:{Path(path).resolve()}"


def _existing_file(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"not a readable file: {resolved}")
    return resolved


def require_fresh_output(path: str | Path) -> Path:
    """Resolve an output path, refusing to overwrite anything that exists."""
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing output {target}")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {target.parent}")
    return target


def _frame_rate(value: Any) -> str:
    if value is None:
        return DEFAULT_FRAME_RATE
    text = str(value)
    if not _FRAME_RATE.match(text):
        raise ValueError(f"unsupported frame rate {text!r}")
    return text


@dataclass(frozen=True)
class StreamInfo:
    """Validated ``ffprobe`` fields of the first video stream."""

    width: int
    height: int
    frame_rate: str
    # Declared (``nb_frames``) or estimated (duration x rate) count; None when
    # the container says neither.  Used only for the pre-decode budget check.
    frames: int | None

    @property
    def luma_samples_per_frame(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class DecodedVideo:
    """Planes of a decoded clip; ``y`` has shape ``(frames, height, width)``."""

    y: np.ndarray
    u: np.ndarray
    v: np.ndarray
    frame_rate: str

    def __post_init__(self) -> None:
        if self.y.ndim != 3 or self.y.dtype != np.uint8 or self.y.shape[0] < 1:
            raise ValueError("luma must be a non-empty (frames, height, width) uint8 array")
        frames, height, width = self.y.shape
        if height % 2 or width % 2:
            raise ValueError("4:2:0 planes need even picture dimensions")
        chroma_shape = (frames, height // 2, width // 2)
        for plane in (self.u, self.v):
            if plane.shape != chroma_shape or plane.dtype != np.uint8:
                raise ValueError("chroma planes must be uint8 4:2:0 companions of the luma")
        _frame_rate(self.frame_rate)

    @property
    def frames(self) -> int:
        return int(self.y.shape[0])

    @property
    def height(self) -> int:
        return int(self.y.shape[1])

    @property
    def width(self) -> int:
        return int(self.y.shape[2])


@dataclass(frozen=True)
class EncoderSettings:
    """Encoder for the stego output; not part of what a verifier pins."""

    codec: str = "libx264"
    crf: int = 16
    preset: str = "medium"
    profile: str | None = "high"
    extra: tuple[str, ...] = field(default_factory=tuple)

    def arguments(self) -> list[str]:
        arguments = ["-c:v", self.codec, "-crf", str(self.crf), "-preset", self.preset]
        if self.profile is not None:
            arguments += ["-profile:v", self.profile]
        return arguments + list(self.extra)


def _dimension(stream: Mapping[str, Any], key: str) -> int:
    value = stream.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"ffprobe reported no usable {key}")
    try:
        number = int(value)
    except ValueError as error:
        raise ValueError(f"ffprobe reported a non-integer {key}: {value!r}") from error
    if not 1 <= number <= MAX_DIMENSION:
        raise ValueError(f"{key} {number} is outside 1..{MAX_DIMENSION}")
    if number % 2:
        raise ValueError("4:2:0 decoding needs even picture dimensions")
    return number


def _frame_count(stream: Mapping[str, Any], frame_rate: str) -> int | None:
    declared = stream.get("nb_frames")
    if declared is not None and str(declared).isdigit():
        return int(declared)
    duration = stream.get("duration")
    if duration is None:
        return None
    try:
        seconds = float(duration)
    except (TypeError, ValueError) as error:
        raise ValueError(f"ffprobe reported an unusable duration {duration!r}") from error
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"ffprobe reported an unusable duration {duration!r}")
    numerator, _, denominator = frame_rate.partition("/")
    return math.ceil(seconds * int(numerator) / int(denominator or 1))


def stream_info(stream: Mapping[str, Any]) -> StreamInfo:
    """Validate one ``ffprobe`` stream object; ``ValueError`` on anything odd."""
    width, height = _dimension(stream, "width"), _dimension(stream, "height")
    frame_rate = _frame_rate(stream.get("r_frame_rate"))
    return StreamInfo(width, height, frame_rate, _frame_count(stream, frame_rate))


def probe(path: str | Path, *, timeout: float = SUBPROCESS_TIMEOUT) -> StreamInfo:
    """Validated geometry, frame rate and frame count of the first video stream."""
    resolved = _existing_file(path)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration", "-of", "json",
         file_url(resolved)],
        capture_output=True, check=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=timeout,
    )
    try:
        streams = json.loads(result.stdout).get("streams") or []
    except (json.JSONDecodeError, AttributeError) as error:
        raise ValueError("ffprobe output is not the expected JSON") from error
    if not streams or not isinstance(streams[0], dict):
        raise ValueError(f"no video stream in {resolved}")
    return stream_info(streams[0])


def frame_limit(width: int, height: int, max_luma_samples: int = MAX_LUMA_SAMPLES) -> int:
    """Most frames of ``width x height`` that fit the luma-sample budget."""
    return max_luma_samples // (width * height)


def _too_long(info: StreamInfo, frames: int | None, limit: int, budget: int) -> ValueError:
    seen = "more than" if frames is None else "about"
    count = limit if frames is None else frames
    return ValueError(
        f"clip has {seen} {count} frames of {info.width}x{info.height}; the decode budget of "
        f"{budget} luma samples allows {limit} frames at this size"
    )


def _frames_to_request(info: StreamInfo, max_frames: int | None, limit: int, budget: int) -> int:
    if max_frames is None:
        if info.frames is not None and info.frames > limit:
            raise _too_long(info, info.frames, limit, budget)
        return limit + 1  # one extra frame tells a clip at the budget from one over it
    if max_frames < 1:
        raise ValueError("max_frames must be positive")
    if max_frames > limit:
        raise _too_long(info, max_frames, limit, budget)
    return max_frames


def _planes(raw: bytes, info: StreamInfo) -> DecodedVideo:
    width, height = info.width, info.height
    luma, chroma = width * height, (width // 2) * (height // 2)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, luma + 2 * chroma)
    # ascontiguousarray copies each plane once (the slices are strided views
    # of the raw buffer); no second copy is made.
    y = np.ascontiguousarray(frames[:, :luma]).reshape(-1, height, width)
    u = np.ascontiguousarray(frames[:, luma:luma + chroma]).reshape(-1, height // 2, width // 2)
    v = np.ascontiguousarray(frames[:, luma + chroma:]).reshape(-1, height // 2, width // 2)
    return DecodedVideo(y, u, v, info.frame_rate)


def decode(
    path: str | Path, *, max_frames: int | None = None,
    max_luma_samples: int = MAX_LUMA_SAMPLES, timeout: float = SUBPROCESS_TIMEOUT,
) -> DecodedVideo:
    """Decode ``path`` to yuv420p planes within the luma-sample budget.

    ``max_frames`` asks for a leading prefix of the clip.  Without it, a clip
    longer than the budget raises ``ValueError`` (before decoding when the
    container declares its length, after reading one frame past the budget
    otherwise).
    """
    resolved = _existing_file(path)
    info = probe(resolved, timeout=timeout)
    limit = frame_limit(info.width, info.height, max_luma_samples)
    if limit < 1:
        raise _too_long(info, info.frames, limit, max_luma_samples)
    requested = _frames_to_request(info, max_frames, limit, max_luma_samples)
    command = [
        "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", _PROTOCOLS,
        "-i", file_url(resolved), "-fps_mode", "passthrough", "-frames:v", str(requested),
        "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1",
    ]
    raw = subprocess.run(
        command, capture_output=True, check=True, stdin=subprocess.DEVNULL, timeout=timeout,
    ).stdout
    frame_bytes = info.luma_samples_per_frame * 3 // 2
    if not raw or len(raw) % frame_bytes:
        raise ValueError("decoder output is not a whole number of frames")
    if max_frames is None and len(raw) // frame_bytes > limit:
        raise _too_long(info, None, limit, max_luma_samples)
    return _planes(raw, info)


def encode(
    video: DecodedVideo, output: str | Path, settings: EncoderSettings, *,
    timeout: float = SUBPROCESS_TIMEOUT,
) -> Path:
    """Encode planes with ffmpeg into a new file; the container follows the extension."""
    target = require_fresh_output(output)
    command = [
        "ffmpeg", "-v", "error", "-nostdin", "-n", "-protocol_whitelist", _PROTOCOLS,
        "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{video.width}x{video.height}",
        "-r", video.frame_rate, "-i", "pipe:0",
        *settings.arguments(), "-pix_fmt", "yuv420p", "-protocol_whitelist", "file", file_url(target),
    ]
    frames = np.concatenate(
        [video.y.reshape(video.frames, -1), video.u.reshape(video.frames, -1),
         video.v.reshape(video.frames, -1)], axis=1,
    )
    subprocess.run(
        command, input=np.ascontiguousarray(frames).tobytes(), check=True, capture_output=True,
        timeout=timeout,
    )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg wrote no output to {target}")
    return target
