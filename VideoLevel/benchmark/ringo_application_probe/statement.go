package openingprobe

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
)

const (
	openingStatementVersion uint16 = 1
	openingStatementSize           = 4 + 2 + 8*32 + 8 + 4 + 8
)

const openingStatementMagic = "RGOS"

// openingStatement is the fixed-width public instance for the research
// relation. The caller must source trust-root, relation, session, video and
// carrier fields from verifier-pinned configuration and independent video
// analysis; this type only enforces canonical representation.
type openingStatement struct {
	Version          uint16
	RelationID       [32]byte
	ParameterID      [32]byte
	RegistryRoot     [32]byte
	RegistryEpoch    uint64
	SessionChallenge [32]byte
	CodecPolicyID    [32]byte
	CarrierProfileID [32]byte
	PayloadLength    uint32
	CarrierCount     uint64
	PositionsHash    [32]byte
	VideoCommitment  [32]byte
}

func marshalOpeningStatement(statement openingStatement) ([]byte, error) {
	if statement.Version != openingStatementVersion {
		return nil, fmt.Errorf("unsupported opening statement version %d", statement.Version)
	}
	for _, field := range []struct {
		name   string
		digest [32]byte
	}{
		{"relation id", statement.RelationID},
		{"parameter id", statement.ParameterID},
		{"registry root", statement.RegistryRoot},
		{"session challenge", statement.SessionChallenge},
		{"codec policy id", statement.CodecPolicyID},
		{"carrier profile id", statement.CarrierProfileID},
		{"positions hash", statement.PositionsHash},
		{"video commitment", statement.VideoCommitment},
	} {
		if field.digest == [32]byte{} {
			return nil, fmt.Errorf("opening statement %s must be non-zero", field.name)
		}
	}
	if statement.RegistryEpoch == 0 {
		return nil, errors.New("opening statement registry epoch must be non-zero")
	}
	if statement.PayloadLength != openingPayloadBytes {
		return nil, fmt.Errorf("opening statement payload length must be %d bytes", openingPayloadBytes)
	}
	if statement.CarrierCount == 0 || statement.CarrierCount%8 != 0 {
		return nil, errors.New("opening statement carrier count must be a positive whole number of bytes")
	}
	if statement.CarrierCount/8 > maxOpeningTransportBytes {
		return nil, fmt.Errorf("opening statement envelope exceeds the %d-byte probe limit", maxOpeningTransportBytes)
	}

	encoded := make([]byte, openingStatementSize)
	offset := copy(encoded, openingStatementMagic)
	binary.BigEndian.PutUint16(encoded[offset:], statement.Version)
	offset += 2
	for _, digest := range [][32]byte{
		statement.RelationID,
		statement.ParameterID,
		statement.RegistryRoot,
		statement.SessionChallenge,
		statement.CodecPolicyID,
		statement.CarrierProfileID,
	} {
		offset += copy(encoded[offset:], digest[:])
	}
	binary.BigEndian.PutUint64(encoded[offset:], statement.RegistryEpoch)
	offset += 8
	binary.BigEndian.PutUint32(encoded[offset:], statement.PayloadLength)
	offset += 4
	binary.BigEndian.PutUint64(encoded[offset:], statement.CarrierCount)
	offset += 8
	for _, digest := range [][32]byte{statement.PositionsHash, statement.VideoCommitment} {
		offset += copy(encoded[offset:], digest[:])
	}
	if offset != len(encoded) {
		return nil, errors.New("internal opening statement size mismatch")
	}
	return encoded, nil
}

func parseOpeningStatement(encoded []byte) (openingStatement, error) {
	var statement openingStatement
	if len(encoded) != openingStatementSize {
		return statement, fmt.Errorf("opening statement must be exactly %d bytes", openingStatementSize)
	}
	if !bytes.Equal(encoded[:len(openingStatementMagic)], []byte(openingStatementMagic)) {
		return statement, errors.New("opening statement magic is invalid")
	}
	offset := len(openingStatementMagic)
	statement.Version = binary.BigEndian.Uint16(encoded[offset:])
	offset += 2
	for _, digest := range []*[32]byte{
		&statement.RelationID,
		&statement.ParameterID,
		&statement.RegistryRoot,
		&statement.SessionChallenge,
		&statement.CodecPolicyID,
		&statement.CarrierProfileID,
	} {
		offset += copy(digest[:], encoded[offset:])
	}
	statement.RegistryEpoch = binary.BigEndian.Uint64(encoded[offset:])
	offset += 8
	statement.PayloadLength = binary.BigEndian.Uint32(encoded[offset:])
	offset += 4
	statement.CarrierCount = binary.BigEndian.Uint64(encoded[offset:])
	offset += 8
	for _, digest := range []*[32]byte{&statement.PositionsHash, &statement.VideoCommitment} {
		offset += copy(digest[:], encoded[offset:])
	}
	if offset != len(encoded) {
		return openingStatement{}, errors.New("internal opening statement parse size mismatch")
	}
	canonical, err := marshalOpeningStatement(statement)
	if err != nil {
		return openingStatement{}, err
	}
	if !bytes.Equal(canonical, encoded) {
		return openingStatement{}, errors.New("opening statement encoding is not canonical")
	}
	return statement, nil
}
