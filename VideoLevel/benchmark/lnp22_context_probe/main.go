package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
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

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	proofPath := flag.String("proof-out", "", "write serialized proof JSON to this path")
	relationPath := flag.String("relation-out", "", "write augmented public relation JSON to this path")
	flag.Parse()
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
		baseParams.K,
		baseParams.L,
		len(units),
		contextDigest,
	)
	if err != nil {
		return fmt.Errorf("serialize public relation: %w", err)
	}
	serializedValid, err := verifySerializedArtifacts(contextBytes, relationBytes, proofBytes)
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
