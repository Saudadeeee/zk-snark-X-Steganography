package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/sampler"
)

type report struct {
	Backend                     string  `json:"backend"`
	PinnedRevision              string  `json:"pinned_revision"`
	ContextDigestSHA256         string  `json:"context_digest_sha256"`
	ContextDigestSHA3           string  `json:"context_digest_sha3_256"`
	BaseRelationSHA256          string  `json:"base_relation_sha256"`
	ContextUnitCount            int     `json:"context_unit_count"`
	AugmentedRows               int     `json:"augmented_rows"`
	AugmentedWitnessPolynomials int     `json:"augmented_witness_polynomials"`
	ProofBytes                  int     `json:"proof_bytes"`
	ProofSHA256                 string  `json:"proof_sha256"`
	PublicRelationBytes         int     `json:"public_relation_bytes"`
	ProveMilliseconds           float64 `json:"prove_milliseconds"`
	VerifyMilliseconds          float64 `json:"verify_milliseconds"`
	Valid                       bool    `json:"valid"`
	ChangedContextRejected      bool    `json:"changed_context_rejected"`
	SecurityStatus              string  `json:"security_status"`
}

var errProofRejected = errors.New("proof verification failed")

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	verifyMode := flag.Bool("verify", false, "verify serialized probe artifacts instead of generating a proof")
	proofPath := flag.String("proof-out", "", "write serialized proof JSON to this path")
	relationPath := flag.String("relation-out", "", "write augmented public relation JSON to this path")
	proofInputPath := flag.String("proof-in", "", "read serialized proof JSON from this path in verify mode")
	relationInputPath := flag.String("relation-in", "", "read augmented public relation JSON from this path in verify mode")
	trustedBaseRelation := flag.String("trusted-base-relation-sha256", "", "verifier-configured SHA-256 pin for the base relation")
	flag.Parse()
	if *verifyMode {
		return runVerify(*proofInputPath, *relationInputPath, *trustedBaseRelation)
	}
	if *proofPath == "" || *relationPath == "" {
		return errors.New("-proof-out and -relation-out are required")
	}
	if err := validateOutputPaths(*proofPath, *relationPath); err != nil {
		return err
	}
	contextBytes, err := readCanonicalContext(os.Stdin)
	if err != nil {
		return fmt.Errorf("read canonical statement from stdin: %w", err)
	}

	baseParams := nizk.DefaultParams()
	baseMatrix := sampler.SampleUniformMat(baseParams.Ring, baseParams.K, baseParams.L, rand.Reader)
	baseWitness := sampler.SampleTernaryVec(baseParams.Ring, baseParams.L, rand.Reader)
	baseTarget := baseParams.Ring.MatVecMul(baseMatrix, baseWitness)
	baseStatement := &nizk.Statement{A: baseMatrix, T: baseTarget}
	witness := &nizk.Witness{S: baseWitness}

	units, contextDigest, err := deriveUnits(contextBytes, baseParams.Ring.Q)
	if err != nil {
		return fmt.Errorf("derive context units: %w", err)
	}
	params, statement, augmentedWitness, err := augmentLinearRelation(baseParams, baseStatement, witness, units)
	if err != nil {
		return fmt.Errorf("augment public relation: %w", err)
	}

	proveStarted := time.Now()
	proof, err := nizk.ProveLinear(params, statement, augmentedWitness, rand.Reader)
	proveDuration := time.Since(proveStarted)
	if err != nil {
		return fmt.Errorf("generate LNP22 proof: %w", err)
	}
	proofBytes, err := json.Marshal(proof)
	if err != nil {
		return fmt.Errorf("serialize proof: %w", err)
	}
	verifyStarted := time.Now()
	valid := nizk.VerifyLinear(params, statement, proof)
	verifyDuration := time.Since(verifyStarted)
	if !valid {
		return errors.New("LNP22 verifier rejected freshly generated proof")
	}

	mutatedContext := append([]byte(nil), contextBytes...)
	mutatedContext[len(mutatedContext)-1] ^= 1
	mutatedUnits, _, err := deriveUnits(mutatedContext, baseParams.Ring.Q)
	if err != nil {
		return fmt.Errorf("derive mutated context units: %w", err)
	}
	_, mutatedStatement, _, err := augmentLinearRelation(baseParams, baseStatement, witness, mutatedUnits)
	if err != nil {
		return fmt.Errorf("augment mutated statement: %w", err)
	}
	changedContextRejected := !nizk.VerifyLinear(params, mutatedStatement, proof)
	if !changedContextRejected {
		return errors.New("proof unexpectedly verified after statement-context mutation")
	}

	relationBytes, err := marshalPublicRelation(
		params,
		statement,
		baseStatement,
		baseParams.K,
		baseParams.L,
		len(units),
		contextDigest,
	)
	if err != nil {
		return fmt.Errorf("serialize public relation: %w", err)
	}
	baseDigest, err := baseRelationDigest(baseParams, baseStatement)
	if err != nil {
		return fmt.Errorf("derive verifier-pinned base relation digest: %w", err)
	}
	serializedValid, err := verifySerializedArtifacts(contextBytes, relationBytes, proofBytes, baseDigest)
	if err != nil {
		return fmt.Errorf("verify serialized artifacts: %w", err)
	}
	if !serializedValid {
		return errors.New("serialized proof artifact failed verification")
	}
	if err := writeExclusive(*proofPath, proofBytes); err != nil {
		return fmt.Errorf("write proof artifact: %w", err)
	}
	if err := writeExclusive(*relationPath, relationBytes); err != nil {
		cleanupErr := os.Remove(*proofPath)
		if cleanupErr != nil && !os.IsNotExist(cleanupErr) {
			return errors.Join(
				fmt.Errorf("write public relation artifact: %w", err),
				fmt.Errorf("remove proof artifact after relation write failure: %w", cleanupErr),
			)
		}
		return fmt.Errorf("write public relation artifact: %w", err)
	}
	proofHash := sha256.Sum256(proofBytes)
	contextHash := sha256.Sum256(contextBytes)
	result := report{
		Backend:                     "LNP22 experimental linear relation",
		PinnedRevision:              pinnedLNP22Revision,
		ContextDigestSHA256:         fmt.Sprintf("%x", contextHash),
		ContextDigestSHA3:           fmt.Sprintf("%x", contextDigest),
		BaseRelationSHA256:          baseDigest,
		ContextUnitCount:            len(units),
		AugmentedRows:               params.K,
		AugmentedWitnessPolynomials: params.L,
		ProofBytes:                  len(proofBytes),
		ProofSHA256:                 fmt.Sprintf("%x", proofHash),
		PublicRelationBytes:         len(relationBytes),
		ProveMilliseconds:           float64(proveDuration.Microseconds()) / 1000,
		VerifyMilliseconds:          float64(verifyDuration.Microseconds()) / 1000,
		Valid:                       valid,
		ChangedContextRejected:      changedContextRejected,
		SecurityStatus:              "experimental; source implementation and application relation are not independently audited",
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}

func runVerify(proofPath, relationPath, trustedBaseRelationSHA256 string) error {
	if proofPath == "" || relationPath == "" || trustedBaseRelationSHA256 == "" {
		return errors.New("verify mode requires -proof-in, -relation-in, and -trusted-base-relation-sha256")
	}
	contextBytes, err := readCanonicalContext(os.Stdin)
	if err != nil {
		return fmt.Errorf("read canonical statement from stdin: %w", err)
	}
	proofBytes, err := readArtifactFile(proofPath)
	if err != nil {
		return fmt.Errorf("read proof artifact: %w", err)
	}
	relationBytes, err := readArtifactFile(relationPath)
	if err != nil {
		return fmt.Errorf("read relation artifact: %w", err)
	}
	return verifyCommand(contextBytes, relationBytes, proofBytes, trustedBaseRelationSHA256, os.Stdout)
}

func verifyCommand(contextBytes, relationBytes, proofBytes []byte, trustedBaseRelationSHA256 string, output io.Writer) error {
	if output == nil {
		return errors.New("verification result writer is required")
	}
	valid, err := verifySerializedArtifacts(contextBytes, relationBytes, proofBytes, trustedBaseRelationSHA256)
	if err != nil {
		return fmt.Errorf("verify serialized artifacts: %w", err)
	}
	if err := json.NewEncoder(output).Encode(struct {
		Backend                 string `json:"backend"`
		Valid                   bool   `json:"valid"`
		TrustedBaseRelationHash string `json:"trusted_base_relation_sha256"`
	}{
		Backend:                 "LNP22 experimental context-bound linear relation",
		Valid:                   valid,
		TrustedBaseRelationHash: trustedBaseRelationSHA256,
	}); err != nil {
		return fmt.Errorf("write verification result: %w", err)
	}
	if !valid {
		return errProofRejected
	}
	return nil
}

func readArtifactFile(path string) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, maxProbeArtifactBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || len(data) > maxProbeArtifactBytes {
		return nil, fmt.Errorf("artifact size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	return data, nil
}

func writeExclusive(path string, data []byte) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if _, err := file.Write(data); err != nil {
		closeErr := file.Close()
		removeErr := os.Remove(path)
		return errors.Join(err, cleanupErrors(closeErr, removeErr))
	}
	if err := file.Close(); err != nil {
		removeErr := os.Remove(path)
		return errors.Join(err, cleanupErrors(removeErr))
	}
	return nil
}

func cleanupErrors(errs ...error) error {
	var failures []error
	for _, err := range errs {
		if err != nil && !os.IsNotExist(err) {
			failures = append(failures, err)
		}
	}
	return errors.Join(failures...)
}
