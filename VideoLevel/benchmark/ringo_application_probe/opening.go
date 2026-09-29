package openingprobe

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/sha3"
	"errors"
	"fmt"
	"io"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
	"github.com/sp301415/ringo-snark/math/bignum"
	"github.com/sp301415/ringo-snark/math/bigpoly"
)

// Research-only circuit for a 32-byte opening shape. It is not a reviewed
// commitment, accepted ZKP backend, or canonical video protocol.
const (
	openingRank         = 1 << 13
	openingPayloadBytes = 32
	openingRandomPolys  = 3
	openingRows         = 2
)

type openingCircuit[E bignum.Uint[E]] struct {
	NTTChecker buckler.LinearChecker[E]

	MatrixNTT     [openingRows][openingRandomPolys]buckler.PublicWitness[E]
	MessageNTT    [openingRows]buckler.PublicWitness[E]
	CommitmentNTT [openingRows]buckler.PublicWitness[E]
	TailMask      buckler.PublicWitness[E]

	RandomCoeffs [openingRandomPolys]buckler.Witness[E]
	RandomNTT    [openingRandomPolys]buckler.Witness[E]
	BitCoeffs    buckler.Witness[E]
	BitNTT       buckler.Witness[E]
}

func (c *openingCircuit[E]) Define(ctx *buckler.Context[E]) {
	for i := range c.RandomCoeffs {
		ctx.AddLinearConstraint(c.RandomNTT[i], c.RandomCoeffs[i], c.NTTChecker)
		ctx.AddInfNormConstraint(c.RandomCoeffs[i], 1)
	}
	ctx.AddLinearConstraint(c.BitNTT, c.BitCoeffs, c.NTTChecker)

	// Over a prime field, b*(b-1)=0 requires every coefficient to be 0 or 1.
	// This is a verifier-enforced arithmetic relation, not a prover precheck.
	var bits buckler.ArithmeticConstraint[E]
	bits.AddTerm(nil, c.BitCoeffs, c.BitCoeffs)
	bits.SubTerm(nil, c.BitCoeffs)
	ctx.AddArithmeticConstraint(bits)

	// The first 256 coefficients encode exactly 32 bytes. All others are zero.
	var tail buckler.ArithmeticConstraint[E]
	tail.AddTerm(c.TailMask, c.BitCoeffs)
	ctx.AddArithmeticConstraint(tail)

	// Two full-ring equations C_i = sum_j A_ij*r_j + B_i*bits. All products
	// are checked in NTT representation; the linear checks pin those NTT
	// witnesses to the bounded coefficient representation above.
	for row := range c.CommitmentNTT {
		var equation buckler.ArithmeticConstraint[E]
		equation.AddTerm(c.CommitmentNTT[row])
		for j := range c.RandomNTT {
			equation.SubTerm(c.MatrixNTT[row][j], c.RandomNTT[j])
		}
		equation.SubTerm(c.MessageNTT[row], c.BitNTT)
		ctx.AddArithmeticConstraint(equation)
	}
}

type openingFixture struct {
	context          []byte
	crs              []byte
	ring             *bigpoly.CyclotomicOperator[*zp.Uint]
	randomCoeffs     [openingRandomPolys]*bigpoly.Poly[*zp.Uint]
	randomNTT        [openingRandomPolys]*bigpoly.Poly[*zp.Uint]
	bitCoeffs        *bigpoly.Poly[*zp.Uint]
	bitNTT           *bigpoly.Poly[*zp.Uint]
	proverAssignment openingCircuit[*zp.Uint]
	publicAssignment openingCircuit[*zp.Uint]
}

func newOpeningFixture(context []byte) (*openingFixture, error) {
	if len(context) == 0 {
		return nil, errors.New("context required")
	}
	f := &openingFixture{
		context: append([]byte(nil), context...),
		ring:    bigpoly.NewCyclotomicOperator[*zp.Uint](openingRank),
	}
	crsDigest := sha256.Sum256([]byte("verifier-pinned-ringo-crs/probe/v1"))
	f.crs = append([]byte(nil), crsDigest[:16]...)
	for i := range f.randomCoeffs {
		coeffs := f.ring.NewPoly(false)
		if err := sampleTernary(coeffs); err != nil {
			return nil, err
		}
		f.randomCoeffs[i] = coeffs
		f.randomNTT[i] = f.ring.FwdNTT(coeffs)
	}
	f.bitCoeffs = f.ring.NewPoly(false)
	for i := 0; i < openingPayloadBytes; i++ {
		value := byte(i*7 + 3)
		for bit := 0; bit < 8; bit++ {
			f.bitCoeffs.Coeffs[i*8+bit].SetInt64(int64((value >> (7 - bit)) & 1))
		}
	}
	f.bitNTT = f.ring.FwdNTT(f.bitCoeffs)
	if err := f.rebuildAssignments(); err != nil {
		return nil, err
	}
	return f, nil
}

func (f *openingFixture) rebuildAssignments() error {
	matrix, message, err := derivePublicMatrix(f.ring, f.context)
	if err != nil {
		return err
	}
	var commitment [openingRows]*bigpoly.Poly[*zp.Uint]
	for row := range commitment {
		commitment[row] = f.ring.NewPoly(true)
		for j := range f.randomNTT {
			f.ring.MulAddTo(commitment[row], matrix[row][j], f.randomNTT[j])
		}
		f.ring.MulAddTo(commitment[row], message[row], f.bitNTT)
	}
	mask := f.ring.NewPoly(false)
	for i := openingPayloadBytes * 8; i < openingRank; i++ {
		mask.Coeffs[i].SetInt64(1)
	}
	var public openingCircuit[*zp.Uint]
	for row := range commitment {
		public.CommitmentNTT[row] = commitment[row].Coeffs
		public.MessageNTT[row] = message[row].Coeffs
		for j := range f.randomNTT {
			public.MatrixNTT[row][j] = matrix[row][j].Coeffs
		}
	}
	public.TailMask = mask.Coeffs
	f.publicAssignment = public
	f.proverAssignment = public
	for j := range f.randomNTT {
		f.proverAssignment.RandomCoeffs[j] = f.randomCoeffs[j].Coeffs
		f.proverAssignment.RandomNTT[j] = f.randomNTT[j].Coeffs
	}
	f.proverAssignment.BitCoeffs = f.bitCoeffs.Coeffs
	f.proverAssignment.BitNTT = f.bitNTT.Coeffs
	return nil
}

func derivePublicMatrix(ring *bigpoly.CyclotomicOperator[*zp.Uint], context []byte) (
	[openingRows][openingRandomPolys]*bigpoly.Poly[*zp.Uint],
	[openingRows]*bigpoly.Poly[*zp.Uint], error,
) {
	var matrix [openingRows][openingRandomPolys]*bigpoly.Poly[*zp.Uint]
	var message [openingRows]*bigpoly.Poly[*zp.Uint]
	if len(context) == 0 {
		return matrix, message, errors.New("context required")
	}
	contextDigest := sha256.Sum256(context)
	seed := sha256.Sum256([]byte("verifier-pinned-ringo-matrix-seed/probe/v1"))
	xof := sha3.NewSHAKE256()
	_, _ = xof.Write([]byte("zkstego/ringo-opening/matrix/v1\x00"))
	_, _ = xof.Write(seed[:])
	_, _ = xof.Write(contextDigest[:])
	var elementBytes [32]byte
	for row := range matrix {
		for j := range matrix[row] {
			coeffs := ring.NewPoly(false)
			for _, coefficient := range coeffs.Coeffs {
				if _, err := io.ReadFull(xof, elementBytes[:]); err != nil {
					return matrix, message, err
				}
				coefficient.SetBytes(elementBytes[:])
			}
			matrix[row][j] = ring.FwdNTT(coeffs)
		}
		coeffs := ring.NewPoly(false)
		for _, coefficient := range coeffs.Coeffs {
			if _, err := io.ReadFull(xof, elementBytes[:]); err != nil {
				return matrix, message, err
			}
			coefficient.SetBytes(elementBytes[:])
		}
		message[row] = ring.FwdNTT(coeffs)
	}
	return matrix, message, nil
}

// verifyOpening is the only intended verification entry point for this probe.
// The caller supplies only the public commitment and independently known
// context; matrix, message and payload mask are derived on the verifier side.
func verifyOpening(
	verifier *buckler.Verifier[*zp.Uint],
	context []byte,
	commitment [openingRows]buckler.PublicWitness[*zp.Uint],
	proof *buckler.Proof[*zp.Uint],
) (valid bool, err error) {
	defer func() {
		if recovered := recover(); recovered != nil {
			valid = false
			err = fmt.Errorf("malformed proof caused verifier panic: %v", recovered)
		}
	}()
	if verifier == nil || proof == nil {
		return false, errors.New("verifier and proof required")
	}
	ring := bigpoly.NewCyclotomicOperator[*zp.Uint](openingRank)
	matrix, message, err := derivePublicMatrix(ring, context)
	if err != nil {
		return false, err
	}
	var public openingCircuit[*zp.Uint]
	for row := range commitment {
		if len(commitment[row]) != openingRank {
			return false, errors.New("invalid public commitment length")
		}
		for _, coefficient := range commitment[row] {
			if coefficient == nil {
				return false, errors.New("nil public commitment coefficient")
			}
		}
		public.CommitmentNTT[row] = commitment[row]
		public.MessageNTT[row] = message[row].Coeffs
		for j := range matrix[row] {
			public.MatrixNTT[row][j] = matrix[row][j].Coeffs
		}
	}
	mask := ring.NewPoly(false)
	for i := openingPayloadBytes * 8; i < openingRank; i++ {
		mask.Coeffs[i].SetInt64(1)
	}
	public.TailMask = mask.Coeffs
	return verifier.Verify(&public, proof), nil
}

func (f *openingFixture) withBitCoefficient(index int, value int64) *openingFixture {
	changed := *f
	changed.bitCoeffs = f.ring.NewPoly(false)
	for i := range changed.bitCoeffs.Coeffs {
		changed.bitCoeffs.Coeffs[i].Set(f.bitCoeffs.Coeffs[i])
	}
	changed.bitCoeffs.Coeffs[index].SetInt64(value)
	changed.bitNTT = f.ring.FwdNTT(changed.bitCoeffs)
	if err := changed.rebuildAssignments(); err != nil {
		panic(err) // the fixture's already validated context cannot fail here
	}
	return &changed
}

func (f *openingFixture) withRandomCoefficient(polyIndex, index int, value int64) *openingFixture {
	changed := *f
	changed.randomCoeffs[polyIndex] = f.ring.NewPoly(false)
	for i := range changed.randomCoeffs[polyIndex].Coeffs {
		changed.randomCoeffs[polyIndex].Coeffs[i].Set(f.randomCoeffs[polyIndex].Coeffs[i])
	}
	changed.randomCoeffs[polyIndex].Coeffs[index].SetInt64(value)
	changed.randomNTT[polyIndex] = f.ring.FwdNTT(changed.randomCoeffs[polyIndex])
	if err := changed.rebuildAssignments(); err != nil {
		panic(err) // the fixture's already validated context cannot fail here
	}
	return &changed
}

func sampleTernary(poly *bigpoly.Poly[*zp.Uint]) error {
	var one [1]byte
	for _, coefficient := range poly.Coeffs {
		for {
			if _, err := io.ReadFull(rand.Reader, one[:]); err != nil {
				return err
			}
			if one[0] < 252 {
				coefficient.SetInt64(int64(one[0]%3) - 1)
				break
			}
		}
	}
	return nil
}

func cloneVector(vector buckler.PublicWitness[*zp.Uint]) buckler.PublicWitness[*zp.Uint] {
	clone := make(buckler.PublicWitness[*zp.Uint], len(vector))
	for i := range vector {
		clone[i] = new(zp.Uint).Set(vector[i])
	}
	return clone
}
