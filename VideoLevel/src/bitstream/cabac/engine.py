"""H.264 CABAC arithmetic decoding and encoding engines (ITU-T H.264 9.3.1.2, 9.3.3.2, 9.3.4).

Both engines work bit-exactly on an RBSP byte string.  The encoder follows the
encoding process of 9.3.4 (InitEncoder, EncodeDecision, EncodeBypass,
EncodeTerminate, EncodeFlush); together with the shared syntax traversal of
``syntax`` this defines the *canonical* CABAC encoding a verifier requires.

Bit accounting used for I_PCM and the end of a slice: after a terminate bin
equal to 1 the decoder has consumed exactly the bits the encoder wrote up to
and including the final bit of EncodeFlush (the rbsp_stop_one_bit at the end
of a slice).
"""

from __future__ import annotations

from .tables import INIT_I, RANGE_TAB_LPS, TRANS_IDX_LPS, TRANS_IDX_MPS

NUM_CONTEXTS = 1024


def init_context_states(slice_qp: int) -> tuple[list[int], list[int]]:
    """``(pStateIdx, valMPS)`` lists for an I slice (9.3.1.1)."""
    qp = min(max(slice_qp, 0), 51)
    states = [0] * NUM_CONTEXTS
    mps = [0] * NUM_CONTEXTS
    for index, (m, n) in enumerate(INIT_I):
        pre = min(max(((m * qp) >> 4) + n, 1), 126)
        if pre <= 63:
            states[index], mps[index] = 63 - pre, 0
        else:
            states[index], mps[index] = pre - 64, 1
    return states, mps


class CabacError(ValueError):
    """The slice data is not a valid CABAC encoding."""


class CabacDecoder:
    """Arithmetic decoding engine over RBSP bytes starting at a bit offset."""

    __slots__ = ("data", "end", "mps", "offset", "pos", "range", "states")

    encoding = False

    def __init__(self, data: bytes, bit_pos: int, slice_qp: int) -> None:
        self.data = data
        self.end = len(data) * 8
        self.pos = bit_pos
        self.states, self.mps = init_context_states(slice_qp)
        self.start()

    def _bit(self) -> int:
        pos = self.pos
        if pos >= self.end:
            # Reading past the end only happens on malformed data.
            raise CabacError("CABAC data ends before the slice is complete")
        self.pos = pos + 1
        return (self.data[pos >> 3] >> (7 - (pos & 7))) & 1

    def start(self) -> None:
        """InitDecodingEngine (also after I_PCM samples)."""
        self.range = 510
        value = 0
        for _ in range(9):
            value = (value << 1) | self._bit()
        self.offset = value
        if value >= 510:
            raise CabacError("codIOffset 510 or 511 is forbidden")

    def decision(self, ctx: int, _value: int | None = None) -> int:
        state = self.states[ctx]
        lps = RANGE_TAB_LPS[state][(self.range >> 6) & 3]
        rng = self.range - lps
        if self.offset >= rng:
            bin_value = 1 - self.mps[ctx]
            self.offset -= rng
            rng = lps
            if state == 0:
                self.mps[ctx] = 1 - self.mps[ctx]
            self.states[ctx] = TRANS_IDX_LPS[state]
        else:
            bin_value = self.mps[ctx]
            self.states[ctx] = TRANS_IDX_MPS[state]
        offset = self.offset
        while rng < 256:
            rng <<= 1
            offset = (offset << 1) | self._bit()
        self.range = rng
        self.offset = offset
        return bin_value

    def bypass(self, _value: int | None = None) -> int:
        self.offset = (self.offset << 1) | self._bit()
        if self.offset >= self.range:
            self.offset -= self.range
            return 1
        return 0

    def terminate(self, _value: int | None = None) -> int:
        self.range -= 2
        if self.offset >= self.range:
            return 1
        rng, offset = self.range, self.offset
        while rng < 256:
            rng <<= 1
            offset = (offset << 1) | self._bit()
        self.range, self.offset = rng, offset
        return 0


class BitWriter:
    """MSB-first bit writer."""

    __slots__ = ("count", "cur", "out")

    def __init__(self) -> None:
        self.out = bytearray()
        self.cur = 0
        self.count = 0

    def write(self, bit: int) -> None:
        self.cur = (self.cur << 1) | bit
        self.count += 1
        if self.count == 8:
            self.out.append(self.cur)
            self.cur = 0
            self.count = 0

    def write_bits(self, value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            self.write((value >> shift) & 1)

    @property
    def bit_length(self) -> int:
        return len(self.out) * 8 + self.count

    @property
    def aligned(self) -> bool:
        return self.count == 0

    def to_bytes(self) -> bytes:
        if self.count:
            raise ValueError("bit writer is not byte aligned")
        return bytes(self.out)


class CabacEncoder:
    """Arithmetic encoding engine of 9.3.4 writing into a :class:`BitWriter`."""

    __slots__ = ("first_bit", "low", "mps", "outstanding", "range", "states", "writer")

    encoding = True

    def __init__(self, writer: BitWriter, slice_qp: int) -> None:
        self.writer = writer
        self.states, self.mps = init_context_states(slice_qp)
        self.start()

    def start(self) -> None:
        """InitEncoder (also after I_PCM samples)."""
        self.low = 0
        self.range = 510
        self.outstanding = 0
        self.first_bit = True

    def _put(self, bit: int) -> None:
        if self.first_bit:
            self.first_bit = False
        else:
            self.writer.write(bit)
        if self.outstanding:
            other = 1 - bit
            write = self.writer.write
            for _ in range(self.outstanding):
                write(other)
            self.outstanding = 0

    def _renorm(self) -> None:
        rng, low = self.range, self.low
        while rng < 256:
            if low < 256:
                self._put(0)
            elif low >= 512:
                low -= 512
                self._put(1)
            else:
                low -= 256
                self.outstanding += 1
            rng <<= 1
            low <<= 1
        self.range, self.low = rng, low

    def decision(self, ctx: int, value: int) -> int:
        state = self.states[ctx]
        lps = RANGE_TAB_LPS[state][(self.range >> 6) & 3]
        self.range -= lps
        if value != self.mps[ctx]:
            self.low += self.range
            self.range = lps
            if state == 0:
                self.mps[ctx] = 1 - self.mps[ctx]
            self.states[ctx] = TRANS_IDX_LPS[state]
        else:
            self.states[ctx] = TRANS_IDX_MPS[state]
        if self.range < 256:
            self._renorm()
        return value

    def bypass(self, value: int) -> int:
        self.low <<= 1
        if value:
            self.low += self.range
        if self.low >= 1024:
            self._put(1)
            self.low -= 1024
        elif self.low < 512:
            self._put(0)
        else:
            self.low -= 512
            self.outstanding += 1
        return value

    def terminate(self, value: int) -> int:
        self.range -= 2
        if value:
            self.low += self.range
            self._flush()
        else:
            self._renorm()
        return value

    def _flush(self) -> None:
        self.range = 2
        self._renorm()
        self._put((self.low >> 9) & 1)
        self.writer.write_bits(((self.low >> 7) & 3) | 1, 2)
