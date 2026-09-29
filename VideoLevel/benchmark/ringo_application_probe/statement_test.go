package openingprobe

import (
	"bytes"
	"crypto/sha256"
	"testing"
)

func TestOpeningStatementCanonicalRoundTrip(t *testing.T) {
	statement := validOpeningStatement()
	encoded, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal opening statement: %v", err)
	}
	if len(encoded) != openingStatementSize {
		t.Fatalf("canonical statement size=%d; want %d", len(encoded), openingStatementSize)
	}
	decoded, err := parseOpeningStatement(encoded)
	if err != nil {
		t.Fatalf("parse opening statement: %v", err)
	}
	if decoded != statement {
		t.Fatalf("round trip changed public statement:\n got: %#v\nwant: %#v", decoded, statement)
	}
	reencoded, err := marshalOpeningStatement(decoded)
	if err != nil || !bytes.Equal(encoded, reencoded) {
		t.Fatalf("statement encoding is not canonical: err=%v", err)
	}
}

func TestOpeningStatementRejectsMalformedAndInvalidFields(t *testing.T) {
	valid, err := marshalOpeningStatement(validOpeningStatement())
	if err != nil {
		t.Fatalf("marshal valid statement: %v", err)
	}
	trailing := append(append([]byte(nil), valid...), 0)
	badMagic := append([]byte(nil), valid...)
	badMagic[0] ^= 0xff
	for name, encoded := range map[string][]byte{
		"empty":     nil,
		"truncated": valid[:len(valid)-1],
		"trailing":  trailing,
		"bad magic": badMagic,
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := parseOpeningStatement(encoded); err == nil {
				t.Fatal("accepted malformed canonical statement")
			}
		})
	}

	for name, mutate := range map[string]func(*openingStatement){
		"unsupported version": func(s *openingStatement) { s.Version++ },
		"empty relation id":   func(s *openingStatement) { s.RelationID = [32]byte{} },
		"empty session":       func(s *openingStatement) { s.SessionChallenge = [32]byte{} },
		"wrong payload length": func(s *openingStatement) {
			s.PayloadLength = openingPayloadBytes - 1
		},
		"zero carrier count":  func(s *openingStatement) { s.CarrierCount = 0 },
		"zero registry epoch": func(s *openingStatement) { s.RegistryEpoch = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			statement := validOpeningStatement()
			mutate(&statement)
			if _, err := marshalOpeningStatement(statement); err == nil {
				t.Fatal("marshaled invalid public statement")
			}
		})
	}
}

func validOpeningStatement() openingStatement {
	return openingStatement{
		Version:          openingStatementVersion,
		RelationID:       sha256.Sum256([]byte("probe-relation-v1")),
		ParameterID:      sha256.Sum256([]byte("probe-parameter-v1")),
		RegistryRoot:     sha256.Sum256([]byte("probe-registry-root-v1")),
		RegistryEpoch:    7,
		SessionChallenge: sha256.Sum256([]byte("verifier-issued-one-use-session")),
		CodecPolicyID:    sha256.Sum256([]byte("h264-baseline-cavlc-policy-v1")),
		CarrierProfileID: sha256.Sum256([]byte("blind-cavlc-carrier-profile-v1")),
		PayloadLength:    openingPayloadBytes,
		CarrierCount:     16_000_000,
		PositionsHash:    sha256.Sum256([]byte("positions-derived-from-received-video")),
		VideoCommitment:  sha256.Sum256([]byte("canonical-normalized-h264-video")),
	}
}
