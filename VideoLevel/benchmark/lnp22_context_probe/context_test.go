package main

import (
	"bytes"
	"crypto/rand"
	"encoding/json"
	"errors"
	"math/big"
	"runtime/debug"
	"strings"
	"testing"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
)

func TestLNP22GoModuleVersionMatchesManifestPin(t *testing.T) {
	buildInfo, ok := debug.ReadBuildInfo()
	if !ok {
		t.Fatal("Go build information is unavailable")
	}
	for _, dependency := range buildInfo.Deps {
		if dependency.Path == "github.com/KarpelesLab/lnp22" {
			if dependency.Replace != nil {
				t.Fatalf("LNP22 module was replaced by %q@%q", dependency.Replace.Path, dependency.Replace.Version)
			}
			if dependency.Version != pinnedLNP22ModuleVersion || dependency.Sum != pinnedLNP22ModuleSum {
				t.Fatalf("LNP22 module version/checksum %q %q do not match manifest pin %s %s", dependency.Version, dependency.Sum, pinnedLNP22ModuleVersion, pinnedLNP22ModuleSum)
			}
			return
		}
	}
	t.Fatal("LNP22 module pin is missing from Go build information")
}

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
	baseMatrix := params.Ring.NewPolyMat(params.K, params.L)
	baseTarget := params.Ring.NewPolyVec(params.K)
	baseWitness := params.Ring.NewPolyVec(params.L)
	for row := range baseMatrix {
		baseMatrix[row][row] = params.Ring.One()
		baseTarget[row] = params.Ring.One()
		baseWitness[row] = params.Ring.One()
	}
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
		baseStatement,
		params.K,
		params.L,
		len(units),
		contextDigest,
	)
	if err != nil {
		t.Fatal(err)
	}
	trustedRelationDigest, err := baseRelationDigest(params, baseStatement)
	if err != nil {
		t.Fatal(err)
	}
	valid, err := verifySerializedArtifacts(contextBytes, relationBytes, proofBytes, trustedRelationDigest)
	if err != nil || !valid {
		t.Fatalf("serialized proof and parameter manifest did not verify: valid=%t err=%v", valid, err)
	}
	invalidProof := *proof
	invalidProof.Z = append(invalidProof.Z[:0:0], proof.Z...)
	invalidProof.Z[0] = append(invalidProof.Z[0][:0:0], proof.Z[0]...)
	invalidProof.Z[0][0]++
	invalidProofBytes, err := json.Marshal(invalidProof)
	if err != nil {
		t.Fatal(err)
	}
	var verifyOutput bytes.Buffer
	err = verifyCommand(contextBytes, relationBytes, invalidProofBytes, trustedRelationDigest, &verifyOutput)
	if !errors.Is(err, errProofRejected) || !strings.Contains(verifyOutput.String(), `"valid":false`) {
		t.Fatalf("invalid proof CLI result must return rejection and JSON valid=false: output=%s err=%v", verifyOutput.String(), err)
	}
	if _, err := verifySerializedArtifacts(contextBytes, relationBytes, proofBytes, strings.Repeat("0", 64)); err == nil || !strings.Contains(err.Error(), "trusted base relation digest") {
		t.Fatalf("proof was not rejected against a different verifier-pinned relation: %v", err)
	}
	var changedBase publicRelation
	if err := json.Unmarshal(relationBytes, &changedBase); err != nil {
		t.Fatal(err)
	}
	changedBase.Statement.A[0][0][1] = 1
	changedRelationBytes, err := json.Marshal(changedBase)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := verifySerializedArtifacts(contextBytes, changedRelationBytes, proofBytes, trustedRelationDigest); err == nil || !strings.Contains(err.Error(), "trusted base relation digest") {
		t.Fatalf("proof was not rejected after a canonical base relation mutation: %v", err)
	}
	if _, err := verifySerializedArtifacts(nil, relationBytes, proofBytes, trustedRelationDigest); err == nil || !strings.Contains(err.Error(), "context bytes size") {
		t.Fatalf("empty canonical context did not hit the input bound: %v", err)
	}
	if _, err := verifySerializedArtifacts(make([]byte, maxCanonicalContextBytes+1), relationBytes, proofBytes, trustedRelationDigest); err == nil || !strings.Contains(err.Error(), "context bytes size") {
		t.Fatalf("oversized canonical context did not hit the input bound: %v", err)
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
	valid, err = verifySerializedArtifacts([]byte("video statement B"), relationBytes, proofBytes, trustedRelationDigest)
	if err == nil && valid {
		t.Fatal("serialized proof verified after context mutation")
	}

	var relation publicRelation
	if err := json.Unmarshal(relationBytes, &relation); err != nil {
		t.Fatal(err)
	}
	relation.Statement.A[0][0][0] = relation.Parameters.Q
	malformedRelation, err := json.Marshal(relation)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := verifySerializedArtifacts(contextBytes, malformedRelation, proofBytes, trustedRelationDigest); err == nil {
		t.Fatal("relation with non-canonical field coefficient was accepted")
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
