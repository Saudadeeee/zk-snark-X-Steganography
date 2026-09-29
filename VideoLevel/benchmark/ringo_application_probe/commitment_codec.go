package openingprobe

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

const openingCommitmentMagic = "RZC1"

// encodeOpeningCommitment serializes the verifier's two public commitment
// polynomials in fixed-width canonical field encoding. This object is
// separate from buckler.Proof and must also be carried in-band for verification.
func encodeOpeningCommitment(
	commitment [openingRows]buckler.PublicWitness[*zp.Uint],
	rank int,
) ([]byte, error) {
	if err := validateOpeningCommitmentRank(rank); err != nil {
		return nil, err
	}
	encoded := make([]byte, openingCommitmentHeaderBytes+openingRows*rank*zp.Bytes)
	copy(encoded, openingCommitmentMagic)
	binary.BigEndian.PutUint32(encoded[len(openingCommitmentMagic):], uint32(rank))
	offset := openingCommitmentHeaderBytes
	for row := range commitment {
		if len(commitment[row]) != rank {
			return nil, fmt.Errorf("public commitment row %d has %d coefficients; want %d", row, len(commitment[row]), rank)
		}
		for column, coefficient := range commitment[row] {
			if coefficient == nil {
				return nil, fmt.Errorf("public commitment coefficient [%d][%d] is nil", row, column)
			}
			canonical := coefficient.Bytes()
			copy(encoded[offset:], canonical[:])
			offset += zp.Bytes
		}
	}
	return encoded, nil
}

func decodeOpeningCommitment(encoded []byte, expectedRank int) ([openingRows]buckler.PublicWitness[*zp.Uint], error) {
	var commitment [openingRows]buckler.PublicWitness[*zp.Uint]
	if err := validateOpeningCommitmentRank(expectedRank); err != nil {
		return commitment, err
	}
	wantSize := openingCommitmentHeaderBytes + openingRows*expectedRank*zp.Bytes
	if len(encoded) != wantSize {
		return commitment, fmt.Errorf("public commitment size is %d bytes; want %d", len(encoded), wantSize)
	}
	if !bytes.Equal(encoded[:len(openingCommitmentMagic)], []byte(openingCommitmentMagic)) {
		return commitment, errors.New("public commitment magic is invalid")
	}
	rank := binary.BigEndian.Uint32(encoded[len(openingCommitmentMagic):openingCommitmentHeaderBytes])
	if uint64(rank) != uint64(expectedRank) {
		return commitment, errors.New("public commitment rank does not match verifier parameters")
	}
	offset := openingCommitmentHeaderBytes
	for row := range commitment {
		commitment[row] = make(buckler.PublicWitness[*zp.Uint], expectedRank)
		for column := range commitment[row] {
			coefficient := new(zp.Uint)
			if err := coefficient.SetBytesCanonical(encoded[offset : offset+zp.Bytes]); err != nil {
				return [openingRows]buckler.PublicWitness[*zp.Uint]{}, fmt.Errorf("decode public commitment coefficient [%d][%d]: %w", row, column, err)
			}
			commitment[row][column] = coefficient
			offset += zp.Bytes
		}
	}
	canonical, err := encodeOpeningCommitment(commitment, expectedRank)
	if err != nil {
		return [openingRows]buckler.PublicWitness[*zp.Uint]{}, err
	}
	if !bytes.Equal(canonical, encoded) {
		return [openingRows]buckler.PublicWitness[*zp.Uint]{}, errors.New("public commitment encoding is not canonical")
	}
	return commitment, nil
}

func validateOpeningCommitmentRank(rank int) error {
	if rank < openingPayloadBytes*8 || rank&(rank-1) != 0 {
		return errors.New("public commitment rank must be a power of two at least as large as the payload bit length")
	}
	maxRank := (maxOpeningProofBytes - openingCommitmentHeaderBytes) / (openingRows * zp.Bytes)
	if rank > maxRank {
		return fmt.Errorf("public commitment rank exceeds the %d-byte probe limit", maxOpeningProofBytes)
	}
	return nil
}

const openingCommitmentHeaderBytes = len(openingCommitmentMagic) + 4
