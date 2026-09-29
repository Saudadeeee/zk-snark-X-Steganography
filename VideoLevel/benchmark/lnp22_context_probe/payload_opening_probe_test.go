package main

import (
	"crypto/rand"
	"crypto/sha256"
	"testing"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/sampler"
)

// This is relation-plumbing research only. Passing tests do not establish
// concrete commitment security or repair the pinned dependency's other flaws.
func TestPayloadOpeningProbeBindsOnePayloadAndContext(t *testing.T) {
	params := openingProbeParams()
	seed := sha256.Sum256([]byte("verifier-pinned-payload-opening-probe-key-v1"))
	context := []byte("canonical-video-and-session-context-A")
	payload := make([]byte, 32)
	for i := range payload {
		payload[i] = byte(i*7 + 3)
	}
	randomness := sampler.SampleTernaryVec(params.Ring, 3, rand.Reader)
	witness, err := openingProbeWitness(params, payload, randomness)
	if err != nil {
		t.Fatalf("build opening witness: %v", err)
	}
	commitment, err := openingProbeCommitment(params, seed[:], context, witness)
	if err != nil {
		t.Fatalf("build commitment: %v", err)
	}
	statement, err := openingProbeStatement(params, seed[:], context, commitment)
	if err != nil {
		t.Fatalf("build verifier statement: %v", err)
	}
	proof, err := nizk.ProveLinear(params, statement, witness, rand.Reader)
	if err != nil {
		t.Fatalf("prove opening: %v", err)
	}
	encoded, err := encodeFixedCompactProof(params, proof)
	if err != nil {
		t.Fatalf("encode opening proof: %v", err)
	}
	if len(encoded) != fixedProofHeaderBytes+(params.K+params.L)*params.Ring.N*4 {
		t.Fatalf("proof bytes = %d, unexpected for rank", len(encoded))
	}
	t.Logf("serialized experimental opening proof: %d bytes", len(encoded))
	decoded, err := decodeFixedCompactProof(encoded, params)
	if err != nil || !nizk.VerifyLinear(params, statement, decoded) {
		t.Fatalf("valid opening rejected: decode error=%v", err)
	}
	mutatedProof := append([]byte(nil), encoded...)
	mutatedProof[len(mutatedProof)-1] ^= 1
	mutatedDecoded, err := decodeFixedCompactProof(mutatedProof, params)
	if err == nil && nizk.VerifyLinear(params, statement, mutatedDecoded) {
		t.Fatal("accepted changed proof bytes")
	}

	changedContext, err := openingProbeStatement(params, seed[:], []byte("canonical-video-and-session-context-B"), commitment)
	if err != nil || nizk.VerifyLinear(params, changedContext, decoded) {
		t.Fatalf("same proof accepted under changed context: statement error=%v", err)
	}
	// Changing the context and recentering C by the known B_ctx term must
	// not allow a proof to be replayed for a different video/session pair.
	otherContext := []byte("canonical-video-and-session-context-B")
	_, oldKey, oldContextPoly, err := openingProbeMatrices(params, seed[:], context)
	if err != nil {
		t.Fatalf("derive old public context term: %v", err)
	}
	_, newKey, newContextPoly, err := openingProbeMatrices(params, seed[:], otherContext)
	if err != nil {
		t.Fatalf("derive new public context term: %v", err)
	}
	shiftedCommitment := params.Ring.NewPolyVec(2)
	for i := range shiftedCommitment {
		base := params.Ring.Sub(commitment[i], params.Ring.Mul(oldKey[i], oldContextPoly))
		shiftedCommitment[i] = params.Ring.Add(base, params.Ring.Mul(newKey[i], newContextPoly))
	}
	shiftedStatement, err := openingProbeStatement(params, seed[:], otherContext, shiftedCommitment)
	if err != nil || nizk.VerifyLinear(params, shiftedStatement, decoded) {
		t.Fatalf("proof replayed with context and commitment shifted together: statement error=%v", err)
	}
	changedSeed := sha256.Sum256([]byte("different-verifier-pinned-key"))
	changedMatrix, err := openingProbeStatement(params, changedSeed[:], context, commitment)
	if err != nil || nizk.VerifyLinear(params, changedMatrix, decoded) {
		t.Fatalf("same proof accepted under changed matrix seed: statement error=%v", err)
	}
	changedCommitment := params.Ring.NewPolyVec(2)
	for i := range commitment {
		copy(changedCommitment[i], commitment[i])
	}
	changedCommitment[0][0] = (changedCommitment[0][0] + 1) % params.Ring.Q
	changedStatement, err := openingProbeStatement(params, seed[:], context, changedCommitment)
	if err != nil || nizk.VerifyLinear(params, changedStatement, decoded) {
		t.Fatalf("same proof accepted under changed commitment: statement error=%v", err)
	}

	wrongPayload := append([]byte(nil), payload...)
	wrongPayload[0] ^= 1
	wrongWitness, err := openingProbeWitness(params, wrongPayload, randomness)
	if err != nil {
		t.Fatalf("build wrong opening: %v", err)
	}
	if _, err := nizk.ProveLinear(params, statement, wrongWitness, rand.Reader); err == nil {
		t.Fatal("prover accepted a different payload under the same commitment and randomness")
	}

	// b=2 and complement=-1 preserve b+complement=1 algebraically, but
	// violate the pinned Beta=1 bound and must not be proven as a valid byte.
	badWitness, err := openingProbeWitness(params, payload, randomness)
	if err != nil {
		t.Fatalf("build witness for bit-range control: %v", err)
	}
	badWitness.S[3][0] = 2
	badWitness.S[4][0] = params.Ring.Q - 1
	badCommitment, err := openingProbeCommitment(params, seed[:], context, badWitness)
	if err != nil {
		t.Fatalf("build bad-bit control commitment: %v", err)
	}
	badStatement, err := openingProbeStatement(params, seed[:], context, badCommitment)
	if err != nil {
		t.Fatalf("build bad-bit control statement: %v", err)
	}
	if _, err := nizk.ProveLinear(params, badStatement, badWitness, rand.Reader); err == nil {
		t.Fatal("prover accepted a coefficient outside the bit witness bound")
	}
}

func TestPayloadOpeningProbeBitComplementAlgebra(t *testing.T) {
	params := openingProbeParams()
	q := params.Ring.Q
	accepted := 0
	for _, bit := range []int64{-1, 0, 1} {
		for _, complement := range []int64{-1, 0, 1} {
			if ((bit+complement)%q+q)%q != 1 {
				continue
			}
			accepted++
			if !((bit == 0 && complement == 1) || (bit == 1 && complement == 0)) {
				t.Fatalf("non-bit pair passed algebra: (%d, %d)", bit, complement)
			}
		}
	}
	if accepted != 2 {
		t.Fatalf("found %d allowed bit-complement pairs, want 2", accepted)
	}
}

func TestPayloadOpeningProbeRejectsMalformedInputs(t *testing.T) {
	params := openingProbeParams()
	seed := make([]byte, 32)
	if _, err := openingProbeWitness(params, make([]byte, 31), params.Ring.NewPolyVec(3)); err == nil {
		t.Fatal("accepted payload other than exactly 32 bytes")
	}
	if _, err := openingProbeWitness(params, make([]byte, 32), params.Ring.NewPolyVec(2)); err == nil {
		t.Fatal("accepted malformed randomness vector")
	}
	malformedRandomness := params.Ring.NewPolyVec(3)
	malformedRandomness[0] = malformedRandomness[0][:255]
	if _, err := openingProbeWitness(params, make([]byte, 32), malformedRandomness); err == nil {
		t.Fatal("accepted malformed randomness polynomial")
	}
	if _, err := openingProbeStatement(params, seed[:31], []byte("context"), params.Ring.NewPolyVec(2)); err == nil {
		t.Fatal("accepted unpinned key length")
	}
	if _, err := openingProbeStatement(params, seed, nil, params.Ring.NewPolyVec(2)); err == nil {
		t.Fatal("accepted empty context")
	}
	if _, err := openingProbeStatement(params, seed, []byte("context"), params.Ring.NewPolyVec(1)); err == nil {
		t.Fatal("accepted malformed public commitment shape")
	}
	nonCanonical := params.Ring.NewPolyVec(2)
	nonCanonical[0][0] = params.Ring.Q
	if _, err := openingProbeStatement(params, seed, []byte("context"), nonCanonical); err == nil {
		t.Fatal("accepted non-canonical public commitment coefficient")
	}
}
