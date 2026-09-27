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

type publicRelation struct {
	Protocol string          `json:"protocol"`
	Q        int64           `json:"q"`
	N        int             `json:"n"`
	K        int             `json:"k"`
	L        int             `json:"l"`
	A        *nizk.Statement `json:"statement"`
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
	contextBytes, err := io.ReadAll(os.Stdin)
	if err != nil {
		return fmt.Errorf("read canonical statement from stdin: %w", err)
	}
	if len(contextBytes) == 0 {
		return errors.New("canonical statement on stdin must not be empty")
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

	relationBytes, err := json.Marshal(publicRelation{
		Protocol: "lnp22-linear-context-probe-v1",
		Q:        params.Ring.Q,
		N:        params.Ring.N,
		K:        params.K,
		L:        params.L,
		A:        statement,
	})
	if err != nil {
		return fmt.Errorf("serialize public relation: %w", err)
	}
	if err := os.WriteFile(*proofPath, proofBytes, 0o600); err != nil {
		return fmt.Errorf("write proof artifact: %w", err)
	}
	if err := os.WriteFile(*relationPath, relationBytes, 0o600); err != nil {
		return fmt.Errorf("write public relation artifact: %w", err)
	}
	proofHash := sha256.Sum256(proofBytes)
	contextHash := sha256.Sum256(contextBytes)
	result := report{
		Backend:                     "LNP22 experimental linear relation",
		PinnedRevision:              "878cf9d5bf73ae387b73a0843edc3364fd0f6be4",
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
