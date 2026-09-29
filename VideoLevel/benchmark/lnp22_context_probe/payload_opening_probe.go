package main

import (
	"errors"
	"fmt"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
	"github.com/KarpelesLab/lnp22/sampler"
	"golang.org/x/crypto/sha3"
)

// This probe is intentionally not wired into the public prover or verifier.
// It tests whether the pinned linear API can carry the target *shape* of an
// opening relation. No binding/hiding or concrete proof-security claim follows.
const (
	openingProbePayloadBytes = 32
	openingProbeRandomPolys  = 3
	openingProbeContextLimit = 4096
)

func openingProbeParams() *nizk.Params {
	p := nizk.DefaultParams()
	p.K = 3 // two commitment equations and one bit-complement equation
	p.L = 5 // three short randomness polynomials, bits, complements
	return p
}

func openingProbeWitness(params *nizk.Params, payload []byte, randomness ring.PolyVec) (*nizk.Witness, error) {
	if err := validateOpeningProbeParams(params); err != nil {
		return nil, err
	}
	if len(payload) != openingProbePayloadBytes {
		return nil, fmt.Errorf("probe payload must be exactly %d bytes", openingProbePayloadBytes)
	}
	if len(randomness) != openingProbeRandomPolys {
		return nil, errors.New("probe randomness must have three polynomials")
	}
	r := params.Ring
	for _, polynomial := range randomness {
		if len(polynomial) != r.N {
			return nil, errors.New("probe randomness polynomial has wrong rank")
		}
	}
	if r.VecInfNorm(randomness) > params.Beta {
		return nil, errors.New("probe randomness exceeds the pinned norm")
	}
	w := r.NewPolyVec(params.L)
	for i := range randomness {
		copy(w[i], r.Reduce(randomness[i]))
	}
	for byteIndex, value := range payload {
		for bitIndex := 0; bitIndex < 8; bitIndex++ {
			bit := int64((value >> (7 - bitIndex)) & 1)
			coefficient := 8*byteIndex + bitIndex
			w[3][coefficient] = bit
			w[4][coefficient] = 1 - bit
		}
	}
	return &nizk.Witness{S: w}, nil
}

func openingProbeCommitment(params *nizk.Params, seed, context []byte, witness *nizk.Witness) (ring.PolyVec, error) {
	matrix, contextKey, contextPoly, err := openingProbeMatrices(params, seed, context)
	if err != nil {
		return nil, err
	}
	if witness == nil || len(witness.S) != params.L {
		return nil, errors.New("probe opening has wrong witness shape")
	}
	for _, polynomial := range witness.S {
		if len(polynomial) != params.Ring.N {
			return nil, errors.New("probe opening has wrong polynomial rank")
		}
	}
	r := params.Ring
	commitment := r.MatVecMul(matrix[:2], witness.S)
	for i := range commitment {
		commitment[i] = r.Add(commitment[i], r.Mul(contextKey[i], contextPoly))
	}
	return commitment, nil
}

func openingProbeStatement(params *nizk.Params, seed, context []byte, commitment ring.PolyVec) (*nizk.Statement, error) {
	matrix, contextKey, contextPoly, err := openingProbeMatrices(params, seed, context)
	if err != nil {
		return nil, err
	}
	if len(commitment) != 2 {
		return nil, errors.New("probe commitment must have two polynomials")
	}
	r := params.Ring
	target := r.NewPolyVec(params.K)
	for i := range commitment {
		if len(commitment[i]) != r.N {
			return nil, errors.New("probe commitment polynomial has wrong rank")
		}
		for _, coefficient := range commitment[i] {
			if coefficient < 0 || coefficient >= r.Q {
				return nil, errors.New("probe commitment has non-canonical coefficient")
			}
		}
		target[i] = r.Sub(commitment[i], r.Mul(contextKey[i], contextPoly))
	}
	for i := range target[2] {
		target[2][i] = 1 // bits + complements = 1 coefficient-wise
	}
	return &nizk.Statement{A: matrix, T: target}, nil
}

func openingProbeMatrices(params *nizk.Params, seed, context []byte) (ring.PolyMat, ring.PolyVec, ring.Poly, error) {
	if err := validateOpeningProbeParams(params); err != nil {
		return nil, nil, nil, err
	}
	if len(seed) != 32 {
		return nil, nil, nil, errors.New("probe verifier-pinned matrix seed must be 32 bytes")
	}
	if len(context) == 0 || len(context) > openingProbeContextLimit {
		return nil, nil, nil, errors.New("probe context length out of range")
	}
	r := params.Ring
	// The caller must supply canonical verifier-derived context. The context
	// digest also selects the public matrix: a context-independent matrix and
	// only an additive B_ctx*H(context) term would allow public recentering of
	// the commitment and reuse of the same proof under another context.
	h := sha3.New256()
	_, _ = h.Write([]byte("zkstego/lnp22/payload-opening-probe/context/v1\x00"))
	_, _ = h.Write(context)
	digest := h.Sum(nil)
	xof := sha3.NewShake256()
	_, _ = xof.Write([]byte("zkstego/lnp22/payload-opening-probe/matrices/v1\x00"))
	_, _ = xof.Write(seed)
	_, _ = xof.Write(digest)
	matrix := r.NewPolyMat(params.K, params.L)
	randomRows := sampler.SampleUniformMat(r, 2, params.L, xof)
	for row := 0; row < 2; row++ {
		copy(matrix[row], randomRows[row])
		matrix[row][4] = r.NewPoly() // complement is constrained only by row 2
	}
	contextMatrix := sampler.SampleUniformMat(r, 2, 1, xof)
	contextKey := r.NewPolyVec(2)
	for row := range contextKey {
		contextKey[row] = contextMatrix[row][0]
	}
	matrix[2][3] = r.One()
	matrix[2][4] = r.One()

	contextPoly := r.NewPoly()
	for i, b := range digest {
		contextPoly[i] = int64(b)
	}
	return matrix, contextKey, contextPoly, nil
}

func validateOpeningProbeParams(params *nizk.Params) error {
	if params == nil || params.Ring == nil || params.Ring.N != 256 || params.Ring.Q != 8380417 ||
		params.K != 3 || params.L != 5 || params.Kappa != 60 || params.Beta != 1 ||
		params.Sigma != 350 || params.BoundZ != 1400 {
		return errors.New("probe requires exact pinned experimental parameters")
	}
	return params.Validate()
}
