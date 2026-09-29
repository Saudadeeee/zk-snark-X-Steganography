package openingprobe

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

const (
	openingTransportMagic      = "RZV1"
	openingTransportHeaderSize = len(openingTransportMagic) + 3*4
	maxOpeningTransportBytes   = 16 << 20
)

type openingTransportEnvelope struct {
	StatementBytes  []byte
	Statement       openingStatement
	Commitment      [openingRows]buckler.PublicWitness[*zp.Uint]
	CommitmentBytes []byte
	Proof           *buckler.Proof[*zp.Uint]
	ProofBytes      []byte
}

// encodeOpeningTransportEnvelope packages every public verification input and
// the complete proof. It pads to the verifier-pinned carrier count so a blind
// extractor can read a fixed profile without sidecar lengths.
func encodeOpeningTransportEnvelope(
	statementBytes []byte,
	commitment [openingRows]buckler.PublicWitness[*zp.Uint],
	proof *buckler.Proof[*zp.Uint],
	rank int,
) ([]byte, error) {
	statement, err := parseOpeningStatement(statementBytes)
	if err != nil {
		return nil, fmt.Errorf("parse public statement: %w", err)
	}
	commitmentBytes, err := encodeOpeningCommitment(commitment, rank)
	if err != nil {
		return nil, err
	}
	proofBytes, err := encodeBinaryOpeningProof(proof)
	if err != nil {
		return nil, err
	}
	capacityBytes := statement.CarrierCount / 8
	bodyBytes := uint64(openingTransportHeaderSize) + uint64(len(statementBytes)) +
		uint64(len(commitmentBytes)) + uint64(len(proofBytes))
	if bodyBytes > capacityBytes {
		return nil, fmt.Errorf("statement, commitment and proof need %d bytes; pinned carrier profile holds %d", bodyBytes, capacityBytes)
	}
	if capacityBytes > maxOpeningTransportBytes {
		return nil, errors.New("pinned carrier profile exceeds the transport probe limit")
	}

	envelope := make([]byte, int(capacityBytes))
	copy(envelope, openingTransportMagic)
	offset := len(openingTransportMagic)
	binary.BigEndian.PutUint32(envelope[offset:], uint32(len(statementBytes)))
	offset += 4
	binary.BigEndian.PutUint32(envelope[offset:], uint32(len(commitmentBytes)))
	offset += 4
	binary.BigEndian.PutUint32(envelope[offset:], uint32(len(proofBytes)))
	offset += 4
	for _, part := range [][]byte{statementBytes, commitmentBytes, proofBytes} {
		offset += copy(envelope[offset:], part)
	}
	// The zero-initialized suffix is canonical fixed-profile padding.
	return envelope, nil
}

// decodeOpeningTransportEnvelope accepts the fixed-size in-band object using
// rank/size parameters chosen by the verifier, not values selected from data.
func decodeOpeningTransportEnvelope(encoded []byte, expectedRank int) (*openingTransportEnvelope, error) {
	if err := validateOpeningCommitmentRank(expectedRank); err != nil {
		return nil, err
	}
	if len(encoded) < openingTransportHeaderSize || len(encoded) > maxOpeningTransportBytes {
		return nil, errors.New("opening transport envelope size is out of range")
	}
	if !bytes.Equal(encoded[:len(openingTransportMagic)], []byte(openingTransportMagic)) {
		return nil, errors.New("opening transport envelope magic is invalid")
	}
	offset := len(openingTransportMagic)
	statementLength := uint64(binary.BigEndian.Uint32(encoded[offset:]))
	offset += 4
	commitmentLength := uint64(binary.BigEndian.Uint32(encoded[offset:]))
	offset += 4
	proofLength := uint64(binary.BigEndian.Uint32(encoded[offset:]))
	offset += 4
	expectedCommitmentLength := uint64(openingCommitmentHeaderBytes + openingRows*expectedRank*zp.Bytes)
	if statementLength != openingStatementSize || commitmentLength != expectedCommitmentLength ||
		proofLength == 0 || proofLength > maxOpeningProofBytes {
		return nil, errors.New("opening transport envelope field lengths do not match verifier parameters")
	}
	bodyLength := uint64(openingTransportHeaderSize) + statementLength + commitmentLength + proofLength
	if bodyLength > uint64(len(encoded)) {
		return nil, errors.New("opening transport envelope is truncated")
	}
	statementEnd := offset + int(statementLength)
	commitmentEnd := statementEnd + int(commitmentLength)
	proofEnd := commitmentEnd + int(proofLength)
	statementBytes := encoded[offset:statementEnd]
	commitmentBytes := encoded[statementEnd:commitmentEnd]
	proofBytes := encoded[commitmentEnd:proofEnd]
	statement, err := parseOpeningStatement(statementBytes)
	if err != nil {
		return nil, fmt.Errorf("parse transport statement: %w", err)
	}
	if statement.CarrierCount/8 != uint64(len(encoded)) {
		return nil, errors.New("opening transport length differs from the verifier-pinned carrier count")
	}
	for _, paddingByte := range encoded[proofEnd:] {
		if paddingByte != 0 {
			return nil, errors.New("opening transport padding is not canonical zero")
		}
	}
	commitment, err := decodeOpeningCommitment(commitmentBytes, expectedRank)
	if err != nil {
		return nil, fmt.Errorf("decode transport public commitment: %w", err)
	}
	proof, err := decodeBinaryOpeningProof(proofBytes)
	if err != nil {
		return nil, fmt.Errorf("decode transport proof: %w", err)
	}
	return &openingTransportEnvelope{
		StatementBytes:  append([]byte(nil), statementBytes...),
		Statement:       statement,
		Commitment:      commitment,
		CommitmentBytes: append([]byte(nil), commitmentBytes...),
		Proof:           proof,
		ProofBytes:      append([]byte(nil), proofBytes...),
	}, nil
}
