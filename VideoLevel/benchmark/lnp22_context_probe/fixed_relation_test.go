package main

import (
	"bytes"
	"crypto/rand"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"
)

func TestCompactFixedRelationProofBindsCanonicalContext(t *testing.T) {
	relationBytes, witnessBytes, relationDigest, err := createFixedRelation(rand.Reader)
	if err != nil {
		t.Fatalf("create fixed relation: %v", err)
	}
	contextBytes := []byte(`{"payload_commitment":"abc","session":"compact-context-test"}`)
	proofBytes, err := proveFixedCompact(contextBytes, relationBytes, witnessBytes, rand.Reader)
	if err != nil {
		t.Fatalf("prove compact fixed relation: %v", err)
	}
	if len(proofBytes) != fixedProofHeaderBytes+(4+5)*256*4 {
		t.Fatalf("compact proof size = %d, want %d", len(proofBytes), fixedProofHeaderBytes+(4+5)*256*4)
	}
	if string(proofBytes[:4]) != fixedProofMagic || proofBytes[4] != fixedCompactProofVersion {
		t.Fatalf("compact proof header does not identify its distinct format: %x", proofBytes[:5])
	}

	valid, err := verifyFixedCompact(contextBytes, relationBytes, proofBytes, relationDigest)
	if err != nil || !valid {
		t.Fatalf("compact proof rejected: valid=%t err=%v", valid, err)
	}
	changedContext := []byte(`{"payload_commitment":"abc","session":"compact-context-tesu"}`)
	valid, err = verifyFixedCompact(changedContext, relationBytes, proofBytes, relationDigest)
	if err != nil || valid {
		t.Fatalf("compact proof did not reject changed context: valid=%t err=%v", valid, err)
	}
	if _, err := verifyFixedCompact(contextBytes, relationBytes, proofBytes, "00"); err == nil {
		t.Fatal("compact verifier accepted a missing trusted relation pin")
	}
	mutatedProof := append([]byte(nil), proofBytes...)
	mutatedProof[len(mutatedProof)-1] ^= 1
	valid, err = verifyFixedCompact(contextBytes, relationBytes, mutatedProof, relationDigest)
	if err != nil || valid {
		t.Fatalf("compact verifier accepted a mutated proof: valid=%t err=%v", valid, err)
	}

	params, baseStatement, _, err := parseFixedRelation(relationBytes, relationDigest)
	if err != nil {
		t.Fatalf("parse fixed relation: %v", err)
	}
	first, err := transformFixedStatementByContext(params, baseStatement, contextBytes)
	if err != nil {
		t.Fatalf("transform statement: %v", err)
	}
	second, err := transformFixedStatementByContext(params, baseStatement, changedContext)
	if err != nil {
		t.Fatalf("transform statement for changed context: %v", err)
	}
	if reflect.DeepEqual(first, second) {
		t.Fatal("different canonical contexts produced the same transformed statement")
	}
	if _, err := transformFixedStatementByContext(params, baseStatement, []byte(`{"b":2, "a":1}`)); err == nil {
		t.Fatal("context transform accepted non-canonical JSON")
	}
}

func TestCompactFixedRelationDoesNotProvePayloadCommitmentOpening(t *testing.T) {
	relationBytes, witnessBytes, relationDigest, err := createFixedRelation(rand.Reader)
	if err != nil {
		t.Fatalf("create fixed relation: %v", err)
	}

	// The probe context includes a payload commitment, but the fixed LNP22
	// witness is unrelated to the payload and proveFixedCompact only proves
	// knowledge of that pre-provisioned witness. Re-proving the same witness
	// under two distinct commitments succeeds; this is characterization of the
	// probe's security boundary, not desired application behavior.
	for _, contextBytes := range [][]byte{
		[]byte(`{"payload_commitment":"commitment-for-payload-A","session":"payload-opening-test"}`),
		[]byte(`{"payload_commitment":"commitment-for-payload-B","session":"payload-opening-test"}`),
	} {
		proofBytes, err := proveFixedCompact(contextBytes, relationBytes, witnessBytes, rand.Reader)
		if err != nil {
			t.Fatalf("prove under context %s: %v", contextBytes, err)
		}
		valid, err := verifyFixedCompact(contextBytes, relationBytes, proofBytes, relationDigest)
		if err != nil || !valid {
			t.Fatalf("control proof rejected for context %s: valid=%t err=%v", contextBytes, valid, err)
		}
	}
}

func TestFixedRelationProofBindsCanonicalContext(t *testing.T) {
	relationBytes, witnessBytes, relationDigest, err := createFixedRelation(rand.Reader)
	if err != nil {
		t.Fatalf("create fixed relation: %v", err)
	}
	contextBytes := []byte(`{"payload_commitment":"abc","session":"fixed-relation-test"}`)
	proofBytes, err := proveFixed(contextBytes, relationBytes, witnessBytes, rand.Reader)
	if err != nil {
		t.Fatalf("prove fixed relation: %v", err)
	}

	valid, err := verifyFixed(contextBytes, relationBytes, proofBytes, relationDigest)
	if err != nil || !valid {
		t.Fatalf("fixed relation proof rejected: valid=%t err=%v", valid, err)
	}

	changedContext := []byte(`{"payload_commitment":"abc","session":"fixed-relation-tesu"}`)
	valid, err = verifyFixed(changedContext, relationBytes, proofBytes, relationDigest)
	if err != nil || valid {
		t.Fatalf("proof did not reject changed context: valid=%t err=%v", valid, err)
	}

	params, baseStatement, _, err := parseFixedRelation(relationBytes, relationDigest)
	if err != nil {
		t.Fatalf("parse fixed relation: %v", err)
	}
	units, _, err := deriveUnitsWithDomain(contextBytes, params.Ring.Q, fixedContextDomain)
	if err != nil {
		t.Fatalf("derive fixed context units: %v", err)
	}
	proofParams, _, err := augmentFixedPublicStatement(params, baseStatement, units)
	if err != nil {
		t.Fatalf("augment fixed public statement: %v", err)
	}
	proof, err := decodeFixedProof(proofBytes, proofParams)
	if err != nil {
		t.Fatalf("decode binary proof: %v", err)
	}
	proof.Z[0][0] = (proof.Z[0][0] + 1) % params.Ring.Q
	mutatedProof, err := encodeFixedProof(proofParams, proof)
	if err != nil {
		t.Fatalf("encode mutated binary proof: %v", err)
	}
	valid, err = verifyFixed(contextBytes, relationBytes, mutatedProof, relationDigest)
	if err != nil || valid {
		t.Fatalf("mutated proof was not rejected: valid=%t err=%v", valid, err)
	}
}

func TestFixedProofBinaryEncodingRejectsMalformedArtifacts(t *testing.T) {
	relationBytes, witnessBytes, relationDigest, err := createFixedRelation(rand.Reader)
	if err != nil {
		t.Fatalf("create fixed relation: %v", err)
	}
	contextBytes := []byte(`{"session":"binary-format-test"}`)
	proofBytes, err := proveFixed(contextBytes, relationBytes, witnessBytes, rand.Reader)
	if err != nil {
		t.Fatalf("prove fixed relation: %v", err)
	}
	if len(proofBytes) != fixedProofHeaderBytes+(16+17)*256*4 {
		t.Fatalf("unexpected default proof size %d", len(proofBytes))
	}
	for name, malformed := range map[string][]byte{
		"bad magic": func() []byte {
			copy := append([]byte(nil), proofBytes...)
			copy[0] ^= 1
			return copy
		}(),
		"trailing byte": append(append([]byte(nil), proofBytes...), 0),
	} {
		if _, err := verifyFixed(contextBytes, relationBytes, malformed, relationDigest); err == nil {
			t.Errorf("verifier accepted malformed binary proof (%s)", name)
		}
	}
}

func TestFixedRelationVerifierRequiresOutOfBandRelationPin(t *testing.T) {
	relationBytes, witnessBytes, relationDigest, err := createFixedRelation(rand.Reader)
	if err != nil {
		t.Fatalf("create fixed relation: %v", err)
	}
	contextBytes := []byte(`{"session":"pin-test"}`)
	proofBytes, err := proveFixed(contextBytes, relationBytes, witnessBytes, rand.Reader)
	if err != nil {
		t.Fatalf("prove fixed relation: %v", err)
	}
	if _, err := verifyFixed(contextBytes, relationBytes, proofBytes, "00"); err == nil {
		t.Fatal("verifier accepted a relation without its trusted digest")
	}
	if relationDigest == "" {
		t.Fatal("fixed relation digest is empty")
	}
}

func TestFixedCLISetupProveVerifyRoundTrip(t *testing.T) {
	root := t.TempDir()
	relationPath := filepath.Join(root, "registered-relation.json")
	witnessPath := filepath.Join(root, "private-witness.json")
	proofPath := filepath.Join(root, "proof.lnpf")
	var setupOutput bytes.Buffer
	if err := runFixedSetup(relationPath, witnessPath, &setupOutput); err != nil {
		t.Fatalf("fixed setup CLI path: %v", err)
	}
	var setup struct {
		RelationSHA256 string `json:"relation_sha256"`
	}
	if err := json.Unmarshal(setupOutput.Bytes(), &setup); err != nil {
		t.Fatalf("decode setup result: %v", err)
	}
	if setup.RelationSHA256 == "" {
		t.Fatal("setup did not report the relation pin")
	}
	if _, err := os.Stat(witnessPath); err != nil {
		t.Fatalf("private witness was not persisted for the prover: %v", err)
	}

	contextBytes := []byte(`{"session":"fixed-cli-round-trip"}`)
	var proveOutput bytes.Buffer
	if err := runFixedProve(
		bytes.NewReader(contextBytes), relationPath, witnessPath, proofPath, &proveOutput,
	); err != nil {
		t.Fatalf("fixed prove CLI path: %v", err)
	}
	var prove struct {
		ProofBytes int `json:"proof_bytes"`
	}
	if err := json.Unmarshal(proveOutput.Bytes(), &prove); err != nil {
		t.Fatalf("decode prove result: %v", err)
	}
	if prove.ProofBytes != fixedProofHeaderBytes+(16+17)*256*4 {
		t.Fatalf("CLI emitted %d proof bytes; want the pinned binary size", prove.ProofBytes)
	}

	var verifyOutput bytes.Buffer
	if err := runFixedVerify(
		bytes.NewReader(contextBytes), relationPath, proofPath, setup.RelationSHA256, &verifyOutput,
	); err != nil {
		t.Fatalf("fixed verify CLI path: %v", err)
	}
	var verified struct {
		Valid bool `json:"valid"`
	}
	if err := json.Unmarshal(verifyOutput.Bytes(), &verified); err != nil {
		t.Fatalf("decode verify result: %v", err)
	}
	if !verified.Valid {
		t.Fatal("fixed CLI workflow did not report valid=true")
	}

	changedContext := []byte(`{"session":"fixed-cli-round-tripu"}`)
	var rejectedOutput bytes.Buffer
	err := runFixedVerify(
		bytes.NewReader(changedContext), relationPath, proofPath, setup.RelationSHA256, &rejectedOutput,
	)
	if err != errProofRejected {
		t.Fatalf("changed-context CLI verification error = %v; want %v", err, errProofRejected)
	}
	var rejected struct {
		Valid bool `json:"valid"`
	}
	if err := json.Unmarshal(rejectedOutput.Bytes(), &rejected); err != nil {
		t.Fatalf("decode rejected verification result: %v", err)
	}
	if rejected.Valid {
		t.Fatal("fixed CLI accepted a proof under a changed context")
	}
}

func TestFixedCompactCLISetupProveVerifyRoundTrip(t *testing.T) {
	root := t.TempDir()
	relationPath := filepath.Join(root, "registered-relation.json")
	witnessPath := filepath.Join(root, "private-witness.json")
	proofPath := filepath.Join(root, "compact-proof.lnpf")
	var setupOutput bytes.Buffer
	if err := runFixedSetup(relationPath, witnessPath, &setupOutput); err != nil {
		t.Fatalf("fixed setup CLI path: %v", err)
	}
	var setup struct {
		RelationSHA256 string `json:"relation_sha256"`
	}
	if err := json.Unmarshal(setupOutput.Bytes(), &setup); err != nil || !isSHA256Hex(setup.RelationSHA256) {
		t.Fatalf("invalid fixed setup result: %q err=%v", setupOutput.Bytes(), err)
	}
	contextBytes := []byte(`{"session":"fixed-compact-cli-round-trip"}`)
	var proveOutput bytes.Buffer
	if err := runFixedCompactProve(
		bytes.NewReader(contextBytes), relationPath, witnessPath, proofPath, &proveOutput,
	); err != nil {
		t.Fatalf("fixed compact prove CLI path: %v", err)
	}
	var prove struct {
		ProofBytes int `json:"proof_bytes"`
	}
	if err := json.Unmarshal(proveOutput.Bytes(), &prove); err != nil ||
		prove.ProofBytes != fixedProofHeaderBytes+(4+5)*256*4 {
		t.Fatalf("invalid compact prove result: %q err=%v", proveOutput.Bytes(), err)
	}
	var verifyOutput bytes.Buffer
	if err := runFixedCompactVerify(
		bytes.NewReader(contextBytes), relationPath, proofPath, setup.RelationSHA256, &verifyOutput,
	); err != nil {
		t.Fatalf("fixed compact verify CLI path: %v", err)
	}
	var verified struct {
		Valid bool `json:"valid"`
	}
	if err := json.Unmarshal(verifyOutput.Bytes(), &verified); err != nil || !verified.Valid {
		t.Fatalf("compact workflow did not report valid=true: %q err=%v", verifyOutput.Bytes(), err)
	}
	changedContext := []byte(`{"session":"fixed-compact-cli-round-tripu"}`)
	err := runFixedCompactVerify(
		bytes.NewReader(changedContext), relationPath, proofPath, setup.RelationSHA256, &verifyOutput,
	)
	if err != errProofRejected {
		t.Fatalf("changed-context compact verification error = %v; want %v", err, errProofRejected)
	}
}

func TestFixedCLIExecutableRoundTrip(t *testing.T) {
	root := t.TempDir()
	relationPath := filepath.Join(root, "public-relation.json")
	witnessPath := filepath.Join(root, "private-witness.json")
	proofPath := filepath.Join(root, "proof.lnpf")
	moduleDirectory, err := os.Getwd()
	if err != nil {
		t.Fatalf("get module directory: %v", err)
	}
	run := func(context []byte, args ...string) ([]byte, error) {
		t.Helper()
		command := exec.Command("go", append([]string{"run", "."}, args...)...)
		command.Dir = moduleDirectory
		if context != nil {
			command.Stdin = bytes.NewReader(context)
		}
		return command.Output()
	}

	setupOutput, err := run(nil,
		"-fixed-setup", "-relation-out", relationPath, "-witness-out", witnessPath,
	)
	if err != nil {
		t.Fatalf("run fixed setup CLI: %v", err)
	}
	var setup struct {
		RelationSHA256 string `json:"relation_sha256"`
	}
	if err := json.Unmarshal(setupOutput, &setup); err != nil || !isSHA256Hex(setup.RelationSHA256) {
		t.Fatalf("invalid setup CLI output %q: %v", setupOutput, err)
	}
	contextBytes := []byte(`{"session":"fixed-cli-process-round-trip"}`)
	proveOutput, err := run(contextBytes,
		"-fixed-prove", "-relation-in", relationPath, "-witness-in", witnessPath, "-proof-out", proofPath,
	)
	if err != nil {
		t.Fatalf("run fixed prove CLI: %v", err)
	}
	var prove struct {
		ProofBytes int `json:"proof_bytes"`
	}
	if err := json.Unmarshal(proveOutput, &prove); err != nil ||
		prove.ProofBytes != fixedProofHeaderBytes+(16+17)*256*4 {
		t.Fatalf("invalid prove CLI output %q: %v", proveOutput, err)
	}
	verifyArgs := []string{
		"-fixed-verify", "-relation-in", relationPath, "-proof-in", proofPath,
		"-trusted-base-relation-sha256", setup.RelationSHA256,
	}
	verifyOutput, err := run(contextBytes, verifyArgs...)
	if err != nil {
		t.Fatalf("run fixed verify CLI: %v", err)
	}
	var verified struct {
		Valid bool `json:"valid"`
	}
	if err := json.Unmarshal(verifyOutput, &verified); err != nil || !verified.Valid {
		t.Fatalf("fixed verify CLI did not accept matching context: output=%q err=%v", verifyOutput, err)
	}

	changedContext := []byte(`{"session":"fixed-cli-process-round-tripu"}`)
	rejectedOutput, err := run(changedContext, verifyArgs...)
	if err == nil {
		t.Fatalf("fixed verify CLI accepted changed context: %q", rejectedOutput)
	}
	if exitError, ok := err.(*exec.ExitError); !ok || exitError.ExitCode() == 0 {
		t.Fatalf("changed-context CLI exit error is not a verification rejection: %v", err)
	}
	if err := json.Unmarshal(rejectedOutput, &verified); err != nil || verified.Valid {
		t.Fatalf("changed-context CLI output should report valid=false: output=%q err=%v", rejectedOutput, err)
	}
}

func TestFixedCompactCLIExecutableRoundTrip(t *testing.T) {
	root := t.TempDir()
	relationPath := filepath.Join(root, "public-relation.json")
	witnessPath := filepath.Join(root, "private-witness.json")
	proofPath := filepath.Join(root, "compact-proof.lnpf")
	moduleDirectory, err := os.Getwd()
	if err != nil {
		t.Fatalf("get module directory: %v", err)
	}
	run := func(context []byte, args ...string) ([]byte, error) {
		t.Helper()
		command := exec.Command("go", append([]string{"run", "."}, args...)...)
		command.Dir = moduleDirectory
		if context != nil {
			command.Stdin = bytes.NewReader(context)
		}
		return command.Output()
	}
	setupOutput, err := run(nil,
		"-fixed-setup", "-relation-out", relationPath, "-witness-out", witnessPath,
	)
	if err != nil {
		t.Fatalf("run fixed setup CLI: %v", err)
	}
	var setup struct {
		RelationSHA256 string `json:"relation_sha256"`
	}
	if err := json.Unmarshal(setupOutput, &setup); err != nil || !isSHA256Hex(setup.RelationSHA256) {
		t.Fatalf("invalid setup CLI output %q: %v", setupOutput, err)
	}
	contextBytes := []byte(`{"session":"fixed-compact-cli-process-round-trip"}`)
	proveOutput, err := run(contextBytes,
		"-fixed-compact-prove", "-relation-in", relationPath,
		"-witness-in", witnessPath, "-proof-out", proofPath,
	)
	if err != nil {
		t.Fatalf("run fixed compact prove CLI: %v", err)
	}
	var prove struct {
		ProofBytes int `json:"proof_bytes"`
	}
	if err := json.Unmarshal(proveOutput, &prove); err != nil ||
		prove.ProofBytes != fixedProofHeaderBytes+(4+5)*256*4 {
		t.Fatalf("invalid compact prove CLI output %q: %v", proveOutput, err)
	}
	verifyArgs := []string{
		"-fixed-compact-verify", "-relation-in", relationPath,
		"-proof-in", proofPath, "-trusted-base-relation-sha256", setup.RelationSHA256,
	}
	verifyOutput, err := run(contextBytes, verifyArgs...)
	if err != nil {
		t.Fatalf("run fixed compact verify CLI: %v", err)
	}
	var verified struct {
		Valid bool `json:"valid"`
	}
	if err := json.Unmarshal(verifyOutput, &verified); err != nil || !verified.Valid {
		t.Fatalf("invalid compact verify CLI output %q: %v", verifyOutput, err)
	}
	changedContext := []byte(`{"session":"fixed-compact-cli-process-round-tripu"}`)
	if _, err := run(changedContext, verifyArgs...); err == nil {
		t.Fatal("compact CLI accepted a changed context")
	}
}
