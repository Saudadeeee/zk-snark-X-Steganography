package buckler

import (
	"encoding/binary"
	"errors"

	fiatshamir "github.com/consensys/gnark-crypto/fiat-shamir"
	"github.com/sp301415/ringo-snark/math/bignum"
	"github.com/sp301415/ringo-snark/math/bigpoly"
)

const publicWitnessTranscriptDomain = "ringo-snark/buckler/public-witnesses/v1"

// bindPublicWitnesses binds the complete canonical public instance before the
// first Fiat-Shamir challenge. Each vector is represented in Buckler's
// polynomial encoding and framed with its position and rank.
func bindPublicWitnesses[E bignum.Uint[E]](
	oracle *fiatshamir.Transcript,
	witnesses []*bigpoly.Poly[E],
) error {
	if oracle == nil {
		return errors.New("Fiat-Shamir transcript is required")
	}
	if err := oracle.Bind("projConst", []byte(publicWitnessTranscriptDomain)); err != nil {
		return err
	}
	var frame [24]byte
	binary.BigEndian.PutUint64(frame[:8], uint64(len(witnesses)))
	if err := oracle.Bind("projConst", frame[:8]); err != nil {
		return err
	}
	for i, witness := range witnesses {
		if witness == nil {
			return errors.New("nil encoded public witness")
		}
		encoded := witness.Marshal()
		binary.BigEndian.PutUint64(frame[:8], uint64(i))
		binary.BigEndian.PutUint64(frame[8:16], uint64(witness.Rank()))
		binary.BigEndian.PutUint64(frame[16:], uint64(len(encoded)))
		if err := oracle.Bind("projConst", frame[:]); err != nil {
			return err
		}
		if err := oracle.Bind("projConst", encoded); err != nil {
			return err
		}
	}
	return nil
}
