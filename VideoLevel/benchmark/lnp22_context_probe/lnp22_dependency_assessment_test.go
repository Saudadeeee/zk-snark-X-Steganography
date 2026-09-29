package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"io"
	"math/big"
	"testing"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
	"github.com/KarpelesLab/lnp22/sampler"
	"github.com/KarpelesLab/lnp22/tworing"
	"golang.org/x/crypto/sha3"
)

// This assessment distinguishes prover input validation from what the pinned
// verifier actually proves. It is intentionally a test of a defect, not the
// acceptance behavior desired for an application backend.
func TestPinnedLNP22LinearVerifierAcceptsProofForFalseBetaOneStatement(t *testing.T) {
	params := nizk.DefaultParams()
	r := params.Ring
	statement := &nizk.Statement{
		A: r.NewPolyMat(params.K, params.L),
		T: r.NewPolyVec(params.K),
	}
	statement.A[0][0] = r.One()
	statement.T[0][0] = 2
	witness := &nizk.Witness{S: r.NewPolyVec(params.L)}
	witness.S[0][0] = 2
	if _, err := nizk.ProveLinear(params, statement, witness, rand.Reader); err == nil {
		t.Fatal("control prover accepted witness outside Beta=1")
	}
	// The first equation is s[0]=2 coefficient-wise. Therefore there is no
	// witness with every centered coefficient in [-1,1] for this statement.
	for _, candidate := range []int64{-1, 0, 1} {
		if candidate == statement.T[0][0] {
			t.Fatal("control statement unexpectedly has a Beta=1 solution")
		}
	}
	forged, err := assessForgeLinearProofIgnoringBeta(params, statement, witness)
	if err != nil {
		t.Fatalf("construct out-of-bound-witness transcript: %v", err)
	}
	encoded, err := encodeFixedCompactProof(params, forged)
	if err != nil {
		t.Fatalf("serialize out-of-bound-witness transcript: %v", err)
	}
	decoded, err := decodeFixedCompactProof(encoded, params)
	if err != nil {
		t.Fatalf("decode out-of-bound-witness transcript: %v", err)
	}
	if !nizk.VerifyLinear(params, statement, decoded) {
		t.Fatal("expected pinned verifier to accept a proof for this false Beta=1 statement")
	}
}

func TestPinnedLNP22PayloadOpeningVerifierAcceptsNonBitWitnessTranscript(t *testing.T) {
	params := openingProbeParams()
	seed := sha256.Sum256([]byte("verifier-pinned-payload-opening-probe-key-v1"))
	context := []byte("canonical-video-and-session-context-A")
	randomness := sampler.SampleTernaryVec(params.Ring, 3, rand.Reader)
	witness, err := openingProbeWitness(params, make([]byte, 32), randomness)
	if err != nil {
		t.Fatalf("build payload witness: %v", err)
	}
	witness.S[3][0] = 2
	witness.S[4][0] = params.Ring.Q - 1
	commitment, err := openingProbeCommitment(params, seed[:], context, witness)
	if err != nil {
		t.Fatalf("build commitment for non-bit witness: %v", err)
	}
	statement, err := openingProbeStatement(params, seed[:], context, commitment)
	if err != nil {
		t.Fatalf("build verifier-pinned statement: %v", err)
	}
	if _, err := nizk.ProveLinear(params, statement, witness, rand.Reader); err == nil {
		t.Fatal("control prover accepted bit coefficient 2")
	}
	forged, err := assessForgeLinearProofIgnoringBeta(params, statement, witness)
	if err != nil {
		t.Fatalf("construct non-bit-witness transcript: %v", err)
	}
	encoded, err := encodeFixedCompactProof(params, forged)
	if err != nil {
		t.Fatalf("serialize non-bit-witness transcript: %v", err)
	}
	decoded, err := decodeFixedCompactProof(encoded, params)
	if err != nil {
		t.Fatalf("decode non-bit-witness transcript: %v", err)
	}
	if !nizk.VerifyLinear(params, statement, decoded) {
		t.Fatal("expected pinned verifier to accept transcript from non-bit witness")
	}
	// This second case does not prove that no alternative in-bound opening to
	// this particular commitment exists. The first test above is the explicit
	// false-statement counterexample for the exact Beta=1 claim.
}

func assessForgeLinearProofIgnoringBeta(
	params *nizk.Params,
	statement *nizk.Statement,
	witness *nizk.Witness,
) (*nizk.LinearProof, error) {
	r := params.Ring
	for attempt := 0; attempt < 100; attempt++ {
		y := sampler.SampleGaussianVec(r, params.L, params.Sigma, rand.Reader)
		w := r.MatVecMul(statement.A, y)
		challenge := nizk.HashToChallenge(params, statement.A, statement.T, w)
		z := r.NewPolyVec(params.L)
		for i := range z {
			z[i] = r.Add(y[i], r.Mul(challenge, witness.S[i]))
		}
		if r.VecInfNorm(z) <= params.BoundZ {
			return &nizk.LinearProof{W: w, Z: z}, nil
		}
	}
	return nil, errors.New("could not sample a response within the verifier bound")
}

// This is an upstream dependency assessment, not a desired verifier behavior.
// Keep it pinned to the exact dependency version in go.mod. If the test stops
// reproducing, review the upstream implementation and remove/update this guard.
func TestPinnedLNP22RangeVerifierAcceptsMissingRangeSubproofs(t *testing.T) {
	params := nizk.DefaultParams()
	params.Beta = 2
	if err := params.Validate(); err != nil {
		t.Fatalf("validate assessment parameters: %v", err)
	}

	witness := &nizk.Witness{S: params.Ring.NewPolyVec(params.L)}
	witness.S[0][0] = 2
	statement := &nizk.Statement{
		A: sampler.SampleUniformMat(params.Ring, params.K, params.L, rand.Reader),
	}
	statement.T = params.Ring.MatVecMul(statement.A, witness.S)

	linearProof, err := nizk.ProveLinear(params, statement, witness, rand.Reader)
	if err != nil {
		t.Fatalf("prove valid wider linear witness: %v", err)
	}
	if !nizk.VerifyLinear(params, statement, linearProof) {
		t.Fatal("control linear proof rejected")
	}

	// Beta=1 is stricter than the underlying linear witness bound Beta=2.
	// A real range proof should reject this witness; ProveRange does so.
	rangeStatement := &nizk.RangeStatement{Statement: *statement, Beta: 1}
	if _, err := nizk.ProveRange(params, rangeStatement, witness, rand.Reader); err == nil {
		t.Fatal("control ProveRange unexpectedly accepted coefficient 2 outside [-1,1]")
	}

	// The pinned VerifyRange checks only the linear proof and the shapes/norms
	// of these fields. It accepts omitted bit proofs and a zero-shaped
	// reconstruction proof, despite the witness violating the claimed range.
	reconParams := params
	reconLength := 0
	for x := int64(2 * params.Beta); x > 0; x >>= 1 {
		reconLength++
	}
	if reconLength == 0 {
		t.Fatal("invalid assessment reconstruction dimensions")
	}
	forgedRangeProof := &nizk.RangeProof{
		LinearPart: *linearProof,
		ReconProof: nizk.LinearProof{
			W: reconParams.Ring.NewPolyVec(1),
			Z: reconParams.Ring.NewPolyVec(reconLength),
		},
	}
	if !nizk.VerifyRange(params, rangeStatement, forgedRangeProof) {
		t.Fatal("expected this pinned dependency defect to reproduce; inspect upstream changes")
	}

}

// TestPinnedLNP22TwoRingVerifierAcceptsWitnessOutsideNormBound is a dependency
// assessment, not desired product behavior. It constructs the documented
// Fiat-Shamir response for a valid linear relation whose witness violates the
// statement's explicit L2 bound. The pinned Prove API rejects that witness,
// but Verify accepts the algebraically valid proof because it never checks the
// L2 bound (or a proof of it).
func TestPinnedLNP22TwoRingVerifierAcceptsWitnessOutsideNormBound(t *testing.T) {
	r, err := ring.NewBig(64, big.NewInt(8380417))
	if err != nil {
		t.Fatalf("create assessment ring: %v", err)
	}
	params := tworing.DefaultParams(r)
	witness := &tworing.Witness{S: r.NewPolyVec(params.L)}
	witness.S[0][0].SetInt64(2) // squared L2 norm is 4, above the claimed bound 1.
	statement := &tworing.Statement{
		Linear: []tworing.LinearStatement{{
			A: sampler.SampleBigUniformMat(r, params.K, params.L, rand.Reader),
		}},
		Norm: &tworing.NormStatement{L2BoundSq: big.NewInt(1)},
	}
	statement.Linear[0].T = r.MatVecMul(statement.Linear[0].A, witness.S)

	if _, err := tworing.Prove(params, statement, witness, rand.Reader); err == nil {
		t.Fatal("control Prove unexpectedly accepted a witness outside the claimed L2 bound")
	}

	forged, err := assessForgeTwoRingProofIgnoringL2(params, statement, witness, rand.Reader)
	if err != nil {
		t.Fatalf("construct assessment proof: %v", err)
	}
	if !tworing.Verify(params, statement, forged) {
		t.Fatal("expected pinned verifier norm-bound defect to reproduce; inspect upstream changes")
	}
}

// TestPinnedLNP22TwoRingVerifierAcceptsQuadraticForgeryFromUnhashedWy is a
// direct soundness assessment. For B=0 and V=1, no witness satisfies the
// quadratic statement <s,Bs>=V. The verifier accepts Z=0, Wq=0, Wy=-c² because Wy
// affects its equation but is omitted from the Fiat-Shamir transcript.
func TestPinnedLNP22TwoRingVerifierAcceptsQuadraticForgeryFromUnhashedWy(t *testing.T) {
	r, err := ring.NewBig(64, big.NewInt(8380417))
	if err != nil {
		t.Fatalf("create assessment ring: %v", err)
	}
	params := tworing.DefaultParams(r)
	statement := &tworing.Statement{
		Quadratic: []tworing.QuadraticStatement{{
			B: r.NewPolyMat(params.L, params.L),
			V: r.One(),
		}},
	}
	proof := &tworing.Proof{
		Z:  r.NewPolyVec(params.L),
		Wq: []ring.BigPoly{r.NewPoly()},
		Wy: []ring.BigPoly{r.NewPoly()},
	}
	challenge := assessTwoRingChallenge(params, statement, proof.W, proof.Wq)
	proof.Wy[0] = r.Sub(r.NewPoly(), r.Mul(challenge, challenge))

	if !tworing.Verify(params, statement, proof) {
		t.Fatal("expected this pinned dependency soundness defect to reproduce; inspect upstream changes")
	}
}

func assessForgeTwoRingProofIgnoringL2(
	params *tworing.Params,
	statement *tworing.Statement,
	witness *tworing.Witness,
	rng io.Reader,
) (*tworing.Proof, error) {
	r := params.Ring
	for attempt := 0; attempt < 10000; attempt++ {
		y := sampler.SampleBigGaussianVec(r, params.L, params.Sigma, rng)
		w := r.MatVecMul(statement.Linear[0].A, y)
		challenge := assessTwoRingChallenge(params, statement, w, nil)
		z := r.NewPolyVec(params.L)
		for i := range z {
			z[i] = r.Add(y[i], r.Mul(challenge, witness.S[i]))
		}
		if r.VecInfNorm(z).Cmp(params.BoundZ) > 0 {
			continue
		}
		return &tworing.Proof{W: w, Z: z}, nil
	}
	return nil, errors.New("could not sample a response within the verifier's infinity-norm bound")
}

func assessTwoRingChallenge(
	params *tworing.Params,
	statement *tworing.Statement,
	w ring.BigPolyVec,
	wq []ring.BigPoly,
) ring.BigPoly {
	h := sha3.NewShake256()
	h.Write([]byte("lnp22-tworing-v1"))
	assessWriteInt(h, len(statement.Linear))
	for _, linear := range statement.Linear {
		assessWriteInt(h, len(linear.A))
		for _, row := range linear.A {
			assessWriteBigVec(h, params.Ring, row)
		}
		assessWriteBigVec(h, params.Ring, linear.T)
	}
	assessWriteInt(h, len(statement.Quadratic))
	for _, quadratic := range statement.Quadratic {
		assessWriteInt(h, len(quadratic.B))
		for _, row := range quadratic.B {
			assessWriteBigVec(h, params.Ring, row)
		}
		assessWriteBigPoly(h, params.Ring, quadratic.V)
	}
	if statement.Norm != nil {
		assessWriteBigInt(h, statement.Norm.L2BoundSq)
	}
	assessWriteBigVec(h, params.Ring, w)
	for _, commitment := range wq {
		assessWriteBigPoly(h, params.Ring, commitment)
	}
	seed := make([]byte, 64)
	_, _ = h.Read(seed)
	return sampler.SampleBigChallenge(params.Ring, seed, params.Kappa)
}

func assessWriteBigVec(h interface{ Write([]byte) (int, error) }, r *ring.BigRing, v ring.BigPolyVec) {
	assessWriteInt(h, len(v))
	for _, p := range v {
		assessWriteBigPoly(h, r, p)
	}
}

func assessWriteBigPoly(h interface{ Write([]byte) (int, error) }, r *ring.BigRing, p ring.BigPoly) {
	for i := 0; i < r.N; i++ {
		assessWriteBigInt(h, p[i])
	}
}

func assessWriteBigInt(h interface{ Write([]byte) (int, error) }, value *big.Int) {
	encoded := value.Bytes()
	assessWriteInt(h, len(encoded))
	_, _ = h.Write(encoded)
}

func assessWriteInt(h interface{ Write([]byte) (int, error) }, value int) {
	var encoded [8]byte
	binary.LittleEndian.PutUint64(encoded[:], uint64(value))
	_, _ = h.Write(encoded[:])
}
