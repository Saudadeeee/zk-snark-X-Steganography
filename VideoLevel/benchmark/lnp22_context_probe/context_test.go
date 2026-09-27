package main

import (
	"crypto/rand"
	"encoding/json"
	"math/big"
	"strings"
	"testing"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
)

func TestDeriveUnitsEncodesStatementDigest(t *testing.T) {
	const modulus int64 = 8_380_417
	statement := []byte(`{"protocol":"zkstego-context-probe-v1"}`)
	units, digest, err := deriveUnits(statement, modulus)
	if err != nil {
		t.Fatal(err)
	}
	if len(units) != 12 {
		t.Fatalf("got %d units; want 12", len(units))
	}
	encoded := big.NewInt(0)
	base := big.NewInt(modulus - 1)
	place := big.NewInt(1)
	for _, unit := range units {
		if unit <= 0 || unit >= modulus {
			t.Fatalf("unit %d is outside [1,q-1]", unit)
		}
		term := new(big.Int).Mul(big.NewInt(unit-1), place)
		encoded.Add(encoded, term)
		place.Mul(place, base)
	}
	if encoded.Cmp(new(big.Int).SetBytes(digest[:])) != 0 {
		t.Fatal("context units do not encode the full digest")
	}
}

func TestAugmentationAddsSatisfiableContextRows(t *testing.T) {
	baseRing, err := ring.New(2, 5)
	if err != nil {
		t.Fatal(err)
	}
	params := &nizk.Params{Ring: baseRing, K: 1, L: 1, Kappa: 1, Beta: 1, Sigma: 2, BoundZ: 8}
	baseMatrix := baseRing.NewPolyMat(1, 1)
	baseMatrix[0][0][0] = 2
	baseTarget := baseRing.NewPolyVec(1)
	baseTarget[0][0] = 2
	baseWitness := baseRing.NewPolyVec(1)
	baseWitness[0][0] = 1
	units := []int64{3, 4}

	augmentedParams, statement, witness, err := augmentLinearRelation(
		params,
		&nizk.Statement{A: baseMatrix, T: baseTarget},
		&nizk.Witness{S: baseWitness},
		units,
	)
	if err != nil {
		t.Fatal(err)
	}
	if augmentedParams.K != 3 || augmentedParams.L != 3 {
		t.Fatalf("got augmented dimensions K=%d L=%d; want 3,3", augmentedParams.K, augmentedParams.L)
	}
	if !ringEqual(augmentedParams, statement, witness) {
		t.Fatal("augmented witness does not satisfy the augmented linear relation")
	}
	if witness.S[1][0] != 1 || witness.S[2][0] != 1 {
		t.Fatal("context witness suffix is not fixed to one")
	}
}

func TestProofRejectsChangedContext(t *testing.T) {
	params := nizk.DefaultParams()
	params.K = 1
	params.L = 1
	baseMatrix := params.Ring.NewPolyMat(1, 1)
	baseMatrix[0][0] = params.Ring.One()
	baseTarget := params.Ring.NewPolyVec(1)
	baseTarget[0] = params.Ring.One()
	baseWitness := params.Ring.NewPolyVec(1)
	baseWitness[0] = params.Ring.One()
	baseStatement := &nizk.Statement{A: baseMatrix, T: baseTarget}
	witness := &nizk.Witness{S: baseWitness}

	contextBytes := []byte("video statement A")
	units, contextDigest, err := deriveUnits(contextBytes, params.Ring.Q)
	if err != nil {
		t.Fatal(err)
	}
	proofParams, statement, proofWitness, err := augmentLinearRelation(params, baseStatement, witness, units)
	if err != nil {
		t.Fatal(err)
	}
	proof, err := nizk.ProveLinear(proofParams, statement, proofWitness, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	if !nizk.VerifyLinear(proofParams, statement, proof) {
		t.Fatal("proof did not verify against its original context")
	}
	proofBytes, err := json.Marshal(proof)
	if err != nil {
		t.Fatal(err)
	}
	relationBytes, err := marshalPublicRelation(
		proofParams,
		statement,
		params.K,
		params.L,
		len(units),
		contextDigest,
	)
	if err != nil {
		t.Fatal(err)
	}
	valid, err := verifySerializedArtifacts(contextBytes, relationBytes, proofBytes)
	if err != nil || !valid {
		t.Fatalf("serialized proof and parameter manifest did not verify: valid=%t err=%v", valid, err)
	}

	mutatedUnits := append([]int64(nil), units...)
	mutatedUnits[0] = mutatedUnits[0]%(params.Ring.Q-1) + 1
	_, mutatedStatement, _, err := augmentLinearRelation(params, baseStatement, witness, mutatedUnits)
	if err != nil {
		t.Fatal(err)
	}
	if nizk.VerifyLinear(proofParams, mutatedStatement, proof) {
		t.Fatal("proof verified after context mutation")
	}
	valid, err = verifySerializedArtifacts([]byte("video statement B"), relationBytes, proofBytes)
	if err == nil && valid {
		t.Fatal("serialized proof verified after context mutation")
	}
}

func TestReadCanonicalContextRejectsOversizedInput(t *testing.T) {
	input := strings.NewReader(strings.Repeat("x", maxCanonicalContextBytes+1))
	if _, err := readCanonicalContext(input); err == nil {
		t.Fatal("oversized canonical context was accepted")
	}
}

func TestValidateOutputPathsRejectsAliases(t *testing.T) {
	if err := validateOutputPaths("results/proof.json", "results/./proof.json"); err == nil {
		t.Fatal("equivalent proof and relation output paths were accepted")
	}
	if err := validateOutputPaths("results/proof.json", "results/relation.json"); err != nil {
		t.Fatalf("distinct output paths were rejected: %v", err)
	}
}

func ringEqual(params *nizk.Params, statement *nizk.Statement, witness *nizk.Witness) bool {
	return params.Ring.VecEqual(params.Ring.MatVecMul(statement.A, witness.S), statement.T)
}
