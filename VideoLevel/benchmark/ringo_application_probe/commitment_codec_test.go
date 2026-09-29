package openingprobe

import (
	"bytes"
	"testing"
)

func TestOpeningCommitmentCanonicalRoundTrip(t *testing.T) {
	statement := validOpeningStatement()
	context, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal public statement: %v", err)
	}
	fixture, err := newOpeningFixtureWithRank(context, 512)
	if err != nil {
		t.Fatalf("build opening fixture: %v", err)
	}
	commitment := fixture.publicAssignment.CommitmentNTT
	encoded, err := encodeOpeningCommitment(commitment, fixture.rank)
	if err != nil {
		t.Fatalf("encode public opening commitment: %v", err)
	}
	wantSize := len(openingCommitmentMagic) + 4 + openingRows*fixture.rank*16
	if len(encoded) != wantSize {
		t.Fatalf("encoded commitment size=%d; want %d", len(encoded), wantSize)
	}
	decoded, err := decodeOpeningCommitment(encoded, fixture.rank)
	if err != nil {
		t.Fatalf("decode public opening commitment: %v", err)
	}
	reencoded, err := encodeOpeningCommitment(decoded, fixture.rank)
	if err != nil || !bytes.Equal(encoded, reencoded) {
		t.Fatalf("commitment encoding is not canonical: err=%v", err)
	}
}

func TestOpeningCommitmentRejectsMalformedWireData(t *testing.T) {
	statement := validOpeningStatement()
	context, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal public statement: %v", err)
	}
	fixture, err := newOpeningFixtureWithRank(context, 512)
	if err != nil {
		t.Fatalf("build opening fixture: %v", err)
	}
	encoded, err := encodeOpeningCommitment(fixture.publicAssignment.CommitmentNTT, fixture.rank)
	if err != nil {
		t.Fatalf("encode public opening commitment: %v", err)
	}
	badMagic := append([]byte(nil), encoded...)
	badMagic[0] ^= 1
	badRank := append([]byte(nil), encoded...)
	badRank[len(openingCommitmentMagic)+3]++
	trailing := append(append([]byte(nil), encoded...), 0)
	for name, malformed := range map[string][]byte{
		"empty":      nil,
		"truncated":  encoded[:len(encoded)-1],
		"bad magic":  badMagic,
		"wrong rank": badRank,
		"trailing":   trailing,
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := decodeOpeningCommitment(malformed, fixture.rank); err == nil {
				t.Fatal("accepted malformed public commitment")
			}
		})
	}
	if _, err := decodeOpeningCommitment(encoded, fixture.rank*2); err == nil {
		t.Fatal("accepted commitment under a mismatched verifier rank")
	}
}
