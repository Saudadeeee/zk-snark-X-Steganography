package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
	"github.com/KarpelesLab/lnp22/sampler"
	"golang.org/x/crypto/sha3"
)

const fixedRelationProtocol = "zkstego-lnp22-fixed-relation-v1"
const fixedWitnessProtocol = "zkstego-lnp22-private-witness-v1"
const fixedContextDomain = "zkstego/lnp22-fixed-relation-context/v1/"
const fixedProofMagic = "LNPF"
const fixedProofVersion = 1
const fixedCompactProofVersion = 2
const fixedProofHeaderBytes = 11
const fixedCompactContextDomain = "zkstego/lnp22-fixed-compact-context/v1/"

type fixedRelationParameters struct {
	Q      int64   `json:"q"`
	N      int     `json:"n"`
	K      int     `json:"k"`
	L      int     `json:"l"`
	Kappa  int     `json:"kappa"`
	Beta   int64   `json:"beta"`
	Sigma  float64 `json:"sigma"`
	BoundZ int64   `json:"bound_z"`
}

type fixedRelationArtifact struct {
	Protocol       string                  `json:"protocol"`
	Revision       string                  `json:"revision"`
	ContextDomain  string                  `json:"context_domain"`
	Parameters     fixedRelationParameters `json:"parameters"`
	RelationSHA256 string                  `json:"relation_sha256"`
	Statement      *nizk.Statement         `json:"statement"`
}

type fixedWitnessArtifact struct {
	Protocol       string        `json:"protocol"`
	Revision       string        `json:"revision"`
	RelationSHA256 string        `json:"relation_sha256"`
	Witness        *nizk.Witness `json:"witness"`
}

// createFixedRelation performs a one-time setup. The returned relation is
// public and must be pinned independently by each verifier. The witness bytes
// are secret setup output and must never be embedded or distributed publicly.
func createFixedRelation(random io.Reader) ([]byte, []byte, string, error) {
	if random == nil {
		return nil, nil, "", errors.New("setup randomness source is required")
	}
	params := nizk.DefaultParams()
	if err := params.Validate(); err != nil {
		return nil, nil, "", fmt.Errorf("validate default LNP22 parameters: %w", err)
	}
	baseMatrix := sampler.SampleUniformMat(params.Ring, params.K, params.L, random)
	baseWitness := sampler.SampleTernaryVec(params.Ring, params.L, random)
	baseTarget := params.Ring.MatVecMul(baseMatrix, baseWitness)
	statement := &nizk.Statement{A: baseMatrix, T: baseTarget}
	witness := &nizk.Witness{S: baseWitness}
	if params.Ring.VecInfNorm(witness.S) > params.Beta {
		return nil, nil, "", errors.New("setup witness exceeds the pinned coefficient norm bound")
	}
	digest, err := baseRelationDigest(params, statement)
	if err != nil {
		return nil, nil, "", fmt.Errorf("digest fixed base relation: %w", err)
	}
	relation := fixedRelationArtifact{
		Protocol:       fixedRelationProtocol,
		Revision:       pinnedLNP22Revision,
		ContextDomain:  fixedContextDomain,
		Parameters:     fixedRelationParametersFrom(params),
		RelationSHA256: digest,
		Statement:      statement,
	}
	relationBytes, err := json.Marshal(relation)
	if err != nil {
		return nil, nil, "", fmt.Errorf("serialize fixed public relation: %w", err)
	}
	privateWitness := fixedWitnessArtifact{
		Protocol:       fixedWitnessProtocol,
		Revision:       pinnedLNP22Revision,
		RelationSHA256: digest,
		Witness:        witness,
	}
	witnessBytes, err := json.Marshal(privateWitness)
	if err != nil {
		return nil, nil, "", fmt.Errorf("serialize private setup witness: %w", err)
	}
	return relationBytes, witnessBytes, digest, nil
}

func proveFixed(contextBytes, relationBytes, witnessBytes []byte, random io.Reader) ([]byte, error) {
	if random == nil {
		return nil, errors.New("proof randomness source is required")
	}
	if err := validateCanonicalJSON(contextBytes); err != nil {
		return nil, fmt.Errorf("validate canonical public context: %w", err)
	}
	params, statement, digest, err := parseFixedRelation(relationBytes, "")
	if err != nil {
		return nil, err
	}
	var artifact fixedWitnessArtifact
	if err := decodeCanonicalArtifact(witnessBytes, &artifact); err != nil {
		return nil, fmt.Errorf("decode private setup witness: %w", err)
	}
	if artifact.Protocol != fixedWitnessProtocol || artifact.Revision != pinnedLNP22Revision ||
		artifact.RelationSHA256 != digest || artifact.Witness == nil {
		return nil, errors.New("private witness artifact does not match the fixed relation")
	}
	witness := artifact.Witness
	if len(witness.S) != params.L || params.Ring.VecInfNorm(witness.S) > params.Beta ||
		!params.Ring.VecEqual(params.Ring.MatVecMul(statement.A, witness.S), statement.T) {
		return nil, errors.New("private witness does not satisfy the pinned short relation")
	}
	units, _, err := deriveUnitsWithDomain(contextBytes, params.Ring.Q, fixedContextDomain)
	if err != nil {
		return nil, fmt.Errorf("derive context units: %w", err)
	}
	proofParams, proofStatement, proofWitness, err := augmentLinearRelation(
		params, statement, witness, units,
	)
	if err != nil {
		return nil, fmt.Errorf("augment fixed relation with context: %w", err)
	}
	proof, err := nizk.ProveLinear(proofParams, proofStatement, proofWitness, random)
	if err != nil {
		return nil, fmt.Errorf("generate LNP22 fixed-relation proof: %w", err)
	}
	proofBytes, err := encodeFixedProof(proofParams, proof)
	if err != nil {
		return nil, fmt.Errorf("serialize fixed-relation proof: %w", err)
	}
	return proofBytes, nil
}

func verifyFixed(contextBytes, relationBytes, proofBytes []byte, trustedRelationSHA256 string) (bool, error) {
	if err := validateCanonicalJSON(contextBytes); err != nil {
		return false, fmt.Errorf("validate canonical public context: %w", err)
	}
	if !isSHA256Hex(trustedRelationSHA256) {
		return false, errors.New("verifier requires an out-of-band SHA-256 pin for the fixed relation")
	}
	params, baseStatement, digest, err := parseFixedRelation(relationBytes, trustedRelationSHA256)
	if err != nil {
		return false, err
	}
	if len(proofBytes) == 0 || len(proofBytes) > maxProbeArtifactBytes {
		return false, fmt.Errorf("proof size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	units, _, err := deriveUnitsWithDomain(contextBytes, params.Ring.Q, fixedContextDomain)
	if err != nil {
		return false, fmt.Errorf("derive context units: %w", err)
	}
	proofParams, proofStatement, err := augmentFixedPublicStatement(params, baseStatement, units)
	if err != nil {
		return false, fmt.Errorf("rebuild context-bound public statement: %w", err)
	}
	proof, err := decodeFixedProof(proofBytes, proofParams)
	if err != nil {
		return false, fmt.Errorf("decode LNP22 proof: %w", err)
	}
	_ = digest // parseFixedRelation already checked this against the out-of-band pin.
	return nizk.VerifyLinear(proofParams, proofStatement, proof), nil
}

// proveFixedCompact binds canonical context through an invertible public
// statement transform. It avoids adding one witness polynomial per context
// limb while preserving the fixed short-relation witness and proof dimensions.
func proveFixedCompact(contextBytes, relationBytes, witnessBytes []byte, random io.Reader) ([]byte, error) {
	if random == nil {
		return nil, errors.New("proof randomness source is required")
	}
	if err := validateCanonicalJSON(contextBytes); err != nil {
		return nil, fmt.Errorf("validate canonical public context: %w", err)
	}
	var artifact fixedWitnessArtifact
	if err := decodeCanonicalArtifact(witnessBytes, &artifact); err != nil {
		return nil, fmt.Errorf("decode private setup witness: %w", err)
	}
	if artifact.Protocol != fixedWitnessProtocol || artifact.Revision != pinnedLNP22Revision ||
		!isSHA256Hex(artifact.RelationSHA256) || artifact.Witness == nil {
		return nil, errors.New("private witness artifact does not match the fixed relation")
	}
	params, baseStatement, _, err := parseFixedRelation(relationBytes, artifact.RelationSHA256)
	if err != nil {
		return nil, fmt.Errorf("private witness artifact does not match the fixed relation: %w", err)
	}
	witness := artifact.Witness
	if len(witness.S) != params.L || params.Ring.VecInfNorm(witness.S) > params.Beta ||
		!params.Ring.VecEqual(params.Ring.MatVecMul(baseStatement.A, witness.S), baseStatement.T) {
		return nil, errors.New("private witness does not satisfy the pinned short relation")
	}
	contextBoundStatement, err := transformFixedStatementByContext(params, baseStatement, contextBytes)
	if err != nil {
		return nil, fmt.Errorf("bind canonical context to fixed relation: %w", err)
	}
	proof, err := nizk.ProveLinear(params, contextBoundStatement, witness, random)
	if err != nil {
		return nil, fmt.Errorf("generate compact LNP22 fixed-relation proof: %w", err)
	}
	proofBytes, err := encodeFixedCompactProof(params, proof)
	if err != nil {
		return nil, fmt.Errorf("serialize compact fixed-relation proof: %w", err)
	}
	return proofBytes, nil
}

// verifyFixedCompact rebuilds the same context-derived invertible statement
// transform from public inputs before verifying the compact proof.
func verifyFixedCompact(
	contextBytes, relationBytes, proofBytes []byte,
	trustedRelationSHA256 string,
) (bool, error) {
	if err := validateCanonicalJSON(contextBytes); err != nil {
		return false, fmt.Errorf("validate canonical public context: %w", err)
	}
	if !isSHA256Hex(trustedRelationSHA256) {
		return false, errors.New("verifier requires an out-of-band SHA-256 pin for the fixed relation")
	}
	params, baseStatement, _, err := parseFixedRelation(relationBytes, trustedRelationSHA256)
	if err != nil {
		return false, err
	}
	if len(proofBytes) == 0 || len(proofBytes) > maxProbeArtifactBytes {
		return false, fmt.Errorf("proof size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	contextBoundStatement, err := transformFixedStatementByContext(params, baseStatement, contextBytes)
	if err != nil {
		return false, fmt.Errorf("rebuild context-bound public statement: %w", err)
	}
	proof, err := decodeFixedCompactProof(proofBytes, params)
	if err != nil {
		return false, fmt.Errorf("decode compact LNP22 proof: %w", err)
	}
	return nizk.VerifyLinear(params, contextBoundStatement, proof), nil
}

// transformFixedStatementByContext applies the determinant-one row operation
// row0 <- row0 + p(context)*rowR to both A and t. The transform is invertible
// over R_q for every p, so (A*s=t) iff (A'*s=t'); it changes the public
// statement, and therefore the LNP22 Fiat-Shamir challenge, without changing
// the witness or adding proof dimensions. The SHA3-256 digest is injectively
// represented as base-q polynomial coefficients. A unit entry in rowR is
// required so distinct digest polynomials produce distinct public statements.
// This is an experimental context-binding construction and has not received an
// independent cryptographic review.
func transformFixedStatementByContext(
	params *nizk.Params,
	baseStatement *nizk.Statement,
	contextBytes []byte,
) (*nizk.Statement, error) {
	if params == nil || params.Ring == nil || baseStatement == nil {
		return nil, errors.New("fixed parameters and public statement are required")
	}
	if err := params.Validate(); err != nil {
		return nil, fmt.Errorf("validate fixed LNP22 parameters: %w", err)
	}
	if err := validateCanonicalJSON(contextBytes); err != nil {
		return nil, fmt.Errorf("validate canonical public context: %w", err)
	}
	if params.K < 2 || len(baseStatement.A) != params.K || len(baseStatement.T) != params.K {
		return nil, errors.New("fixed linear statement has invalid dimensions for context binding")
	}
	for row, values := range baseStatement.A {
		if len(values) != params.L {
			return nil, fmt.Errorf("fixed matrix row %d has invalid width", row)
		}
		for column, polynomial := range values {
			if len(polynomial) != params.Ring.N {
				return nil, fmt.Errorf("fixed matrix entry (%d,%d) has invalid degree", row, column)
			}
		}
	}
	for row, polynomial := range baseStatement.T {
		if len(polynomial) != params.Ring.N {
			return nil, fmt.Errorf("fixed target entry %d has invalid degree", row)
		}
	}

	contextPolynomial, err := contextDigestPolynomial(params, contextBytes)
	if err != nil {
		return nil, err
	}
	contextRow, err := contextBindingRow(params, baseStatement)
	if err != nil {
		return nil, err
	}
	transformed := &nizk.Statement{
		A: params.Ring.NewPolyMat(params.K, params.L),
		T: params.Ring.NewPolyVec(params.K),
	}
	for row := range baseStatement.A {
		transformed.T[row] = append(ring.Poly(nil), baseStatement.T[row]...)
		for column := range baseStatement.A[row] {
			transformed.A[row][column] = append(ring.Poly(nil), baseStatement.A[row][column]...)
		}
	}
	for column := range transformed.A[0] {
		transformed.A[0][column] = params.Ring.Add(
			transformed.A[0][column],
			params.Ring.Mul(contextPolynomial, baseStatement.A[contextRow][column]),
		)
	}
	transformed.T[0] = params.Ring.Add(
		transformed.T[0],
		params.Ring.Mul(contextPolynomial, baseStatement.T[contextRow]),
	)
	return transformed, nil
}

func contextBindingRow(params *nizk.Params, statement *nizk.Statement) (int, error) {
	if params.Ring.Q%int64(2*params.Ring.N) != 1 {
		return 0, errors.New("compact context binding requires an NTT-friendly cyclotomic ring")
	}
	for row := 1; row < params.K; row++ {
		for _, polynomial := range statement.A[row] {
			evaluations := params.Ring.NTT(polynomial)
			isUnit := true
			for _, evaluation := range evaluations {
				if evaluation == 0 {
					isUnit = false
					break
				}
			}
			if isUnit {
				return row, nil
			}
		}
	}
	return 0, errors.New("fixed relation has no nonzero row entry that is a ring unit")
}

func contextDigestPolynomial(params *nizk.Params, contextBytes []byte) (ring.Poly, error) {
	hash := sha3.New256()
	_, _ = hash.Write([]byte(fixedCompactContextDomain))
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(contextBytes)))
	_, _ = hash.Write(length[:])
	_, _ = hash.Write(contextBytes)
	digestInteger := new(big.Int).SetBytes(hash.Sum(nil))
	digestInteger.Add(digestInteger, big.NewInt(1))
	modulus := big.NewInt(params.Ring.Q)
	capacity := new(big.Int).Exp(modulus, big.NewInt(int64(params.Ring.N)), nil)
	if digestInteger.Cmp(capacity) >= 0 {
		return nil, errors.New("ring polynomial cannot encode the complete context digest")
	}
	polynomial := params.Ring.NewPoly()
	for index := range polynomial {
		quotient := new(big.Int)
		remainder := new(big.Int)
		quotient.QuoRem(digestInteger, modulus, remainder)
		polynomial[index] = remainder.Int64()
		digestInteger = quotient
	}
	if digestInteger.Sign() != 0 {
		return nil, errors.New("context digest encoding was truncated")
	}
	return polynomial, nil
}

// encodeFixedProof serializes the proof's canonical coefficients as big-endian
// uint32 values. The fixed header pins dimensions; the verifier still checks
// every coefficient is below q before passing it to LNP22.
func encodeFixedProof(params *nizk.Params, proof *nizk.LinearProof) ([]byte, error) {
	return encodeLinearProof(params, proof, fixedProofVersion)
}

func encodeFixedCompactProof(params *nizk.Params, proof *nizk.LinearProof) ([]byte, error) {
	return encodeLinearProof(params, proof, fixedCompactProofVersion)
}

func encodeLinearProof(params *nizk.Params, proof *nizk.LinearProof, version byte) ([]byte, error) {
	size, err := fixedProofEncodedSize(params)
	if err != nil {
		return nil, err
	}
	if proof == nil {
		return nil, errors.New("proof is required")
	}
	if !validProofShape(*proof, params.K, params.L, params.Ring.N, params.Ring.Q) {
		return nil, errors.New("proof has invalid dimensions or non-canonical coefficients")
	}
	encoded := make([]byte, size)
	copy(encoded[:4], fixedProofMagic)
	encoded[4] = version
	binary.BigEndian.PutUint16(encoded[5:7], uint16(params.K))
	binary.BigEndian.PutUint16(encoded[7:9], uint16(params.L))
	binary.BigEndian.PutUint16(encoded[9:11], uint16(params.Ring.N))
	offset := fixedProofHeaderBytes
	for _, vector := range [][]ring.Poly{proof.W, proof.Z} {
		for _, polynomial := range vector {
			for _, coefficient := range polynomial {
				binary.BigEndian.PutUint32(encoded[offset:offset+4], uint32(coefficient))
				offset += 4
			}
		}
	}
	return encoded, nil
}

func decodeFixedProof(encoded []byte, params *nizk.Params) (*nizk.LinearProof, error) {
	return decodeLinearProof(encoded, params, fixedProofVersion)
}

func decodeFixedCompactProof(encoded []byte, params *nizk.Params) (*nizk.LinearProof, error) {
	return decodeLinearProof(encoded, params, fixedCompactProofVersion)
}

func decodeLinearProof(encoded []byte, params *nizk.Params, version byte) (*nizk.LinearProof, error) {
	expectedSize, err := fixedProofEncodedSize(params)
	if err != nil {
		return nil, err
	}
	if len(encoded) != expectedSize {
		return nil, errors.New("fixed proof has an invalid or oversized byte length")
	}
	if string(encoded[:4]) != fixedProofMagic || encoded[4] != version ||
		int(binary.BigEndian.Uint16(encoded[5:7])) != params.K ||
		int(binary.BigEndian.Uint16(encoded[7:9])) != params.L ||
		int(binary.BigEndian.Uint16(encoded[9:11])) != params.Ring.N {
		return nil, errors.New("fixed proof header does not match protocol dimensions")
	}
	w := params.Ring.NewPolyVec(params.K)
	z := params.Ring.NewPolyVec(params.L)
	offset := fixedProofHeaderBytes
	for _, vector := range [][]ring.Poly{w, z} {
		for _, polynomial := range vector {
			for index := range polynomial {
				coefficient := int64(binary.BigEndian.Uint32(encoded[offset : offset+4]))
				if coefficient >= params.Ring.Q {
					return nil, errors.New("fixed proof contains a coefficient outside the canonical field range")
				}
				polynomial[index] = coefficient
				offset += 4
			}
		}
	}
	proof := &nizk.LinearProof{W: w, Z: z}
	if !validProofShape(*proof, params.K, params.L, params.Ring.N, params.Ring.Q) {
		return nil, errors.New("fixed proof has invalid polynomial dimensions")
	}
	return proof, nil
}

func fixedProofEncodedSize(params *nizk.Params) (int, error) {
	if params == nil || params.Ring == nil || params.K <= 0 || params.L <= 0 ||
		params.K > 0xffff || params.L > 0xffff || params.Ring.N <= 0 || params.Ring.N > 0xffff ||
		params.Ring.Q <= 0 || params.Ring.Q > int64(^uint32(0)) {
		return 0, errors.New("proof parameters are not representable by the fixed binary format")
	}
	coefficientCount := uint64(params.K+params.L) * uint64(params.Ring.N)
	maximumCoefficients := uint64(maxProbeArtifactBytes-fixedProofHeaderBytes) / 4
	if coefficientCount == 0 || coefficientCount > maximumCoefficients {
		return 0, errors.New("fixed proof exceeds the configured size limit")
	}
	return fixedProofHeaderBytes + int(coefficientCount*4), nil
}

func parseFixedRelation(data []byte, trustedDigest string) (*nizk.Params, *nizk.Statement, string, error) {
	if len(data) == 0 || len(data) > maxProbeArtifactBytes {
		return nil, nil, "", fmt.Errorf("fixed relation size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	var artifact fixedRelationArtifact
	if err := decodeCanonicalArtifact(data, &artifact); err != nil {
		return nil, nil, "", fmt.Errorf("decode fixed relation: %w", err)
	}
	params := nizk.DefaultParams()
	if artifact.Protocol != fixedRelationProtocol || artifact.Revision != pinnedLNP22Revision ||
		artifact.ContextDomain != fixedContextDomain || artifact.Parameters != fixedRelationParametersFrom(params) {
		return nil, nil, "", errors.New("fixed relation protocol or parameter pin is unsupported")
	}
	if artifact.Statement == nil {
		return nil, nil, "", errors.New("fixed relation is missing its statement")
	}
	digest, err := baseRelationDigest(params, artifact.Statement)
	if err != nil {
		return nil, nil, "", err
	}
	if digest != artifact.RelationSHA256 {
		return nil, nil, "", errors.New("fixed relation digest does not match its matrix/target")
	}
	if trustedDigest != "" && (!isSHA256Hex(trustedDigest) || digest != trustedDigest) {
		return nil, nil, "", errors.New("fixed relation does not match the verifier's out-of-band digest pin")
	}
	return params, artifact.Statement, digest, nil
}

func fixedRelationParametersFrom(params *nizk.Params) fixedRelationParameters {
	return fixedRelationParameters{
		Q: params.Ring.Q, N: params.Ring.N, K: params.K, L: params.L,
		Kappa: params.Kappa, Beta: params.Beta, Sigma: params.Sigma, BoundZ: params.BoundZ,
	}
}

func augmentFixedPublicStatement(
	params *nizk.Params,
	statement *nizk.Statement,
	units []int64,
) (*nizk.Params, *nizk.Statement, error) {
	if params == nil || statement == nil || len(units) == 0 ||
		len(statement.A) != params.K || len(statement.T) != params.K {
		return nil, nil, errors.New("complete fixed relation and context units are required")
	}
	if err := params.Validate(); err != nil {
		return nil, nil, fmt.Errorf("validate fixed LNP22 parameters: %w", err)
	}
	for _, row := range statement.A {
		if len(row) != params.L {
			return nil, nil, errors.New("fixed relation matrix is not rectangular")
		}
	}
	for _, unit := range units {
		if unit <= 0 || unit >= params.Ring.Q {
			return nil, nil, errors.New("context units must be nonzero elements below q")
		}
	}
	augmentedParams := *params
	augmentedParams.K += len(units)
	augmentedParams.L += len(units)
	augmentedMatrix := params.Ring.NewPolyMat(augmentedParams.K, augmentedParams.L)
	augmentedTarget := params.Ring.NewPolyVec(augmentedParams.K)
	for row := range statement.A {
		augmentedTarget[row] = append(ring.Poly(nil), statement.T[row]...)
		for column := range statement.A[row] {
			augmentedMatrix[row][column] = append(ring.Poly(nil), statement.A[row][column]...)
		}
	}
	for index, unit := range units {
		row := params.K + index
		column := params.L + index
		constant := params.Ring.NewPoly()
		constant[0] = unit
		augmentedMatrix[row][column] = constant
		augmentedTarget[row] = append(ring.Poly(nil), constant...)
	}
	return &augmentedParams, &nizk.Statement{A: augmentedMatrix, T: augmentedTarget}, nil
}

func validateCanonicalJSON(data []byte) error {
	if len(data) == 0 || len(data) > maxCanonicalContextBytes || !json.Valid(data) {
		return errors.New("public context must be a non-empty JSON value within the configured size limit")
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	canonical, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("canonicalize public context: %w", err)
	}
	if !bytes.Equal(canonical, data) {
		return errors.New("public context JSON is not in canonical encoding")
	}
	return nil
}

func decodeCanonicalArtifact(data []byte, destination any) error {
	if len(data) == 0 || len(data) > maxProbeArtifactBytes {
		return fmt.Errorf("artifact size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	if err := json.Unmarshal(data, destination); err != nil {
		return err
	}
	canonical, err := json.Marshal(destination)
	if err != nil {
		return fmt.Errorf("canonicalize artifact: %w", err)
	}
	if !bytes.Equal(canonical, data) {
		return errors.New("artifact is not in canonical JSON encoding")
	}
	return nil
}
