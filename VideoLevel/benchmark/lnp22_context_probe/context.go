package main

import (
	"crypto/sha256"
	"crypto/sha3"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
)

const contextDomain = "zkstego/lazer-context-binding/v1/"
const maxCanonicalContextBytes = 1 << 20
const maxProbeArtifactBytes = 16 << 20
const pinnedLNP22ModuleVersion = "v0.1.1"
const pinnedLNP22ModuleSum = "h1:7iSrrkrzYDxOF8Dx34OSzNZ6o6GD0URS5DrTE5BjA3w="
const pinnedLNP22Revision = "878cf9d5bf73ae387b73a0843edc3364fd0f6be4"

type proofParameterManifest struct {
	Version            string  `json:"version"`
	Backend            string  `json:"backend"`
	Revision           string  `json:"revision"`
	ContextDomain      string  `json:"context_domain"`
	ContextDigest      string  `json:"context_digest_sha3_256"`
	BaseRelationSHA256 string  `json:"base_relation_sha256"`
	ContextUnitCount   int     `json:"context_unit_count"`
	Q                  int64   `json:"q"`
	N                  int     `json:"n"`
	BaseK              int     `json:"base_k"`
	BaseL              int     `json:"base_l"`
	K                  int     `json:"k"`
	L                  int     `json:"l"`
	Kappa              int     `json:"kappa"`
	Beta               int64   `json:"beta"`
	Sigma              float64 `json:"sigma"`
	BoundZ             int64   `json:"bound_z"`
}

type publicRelation struct {
	Protocol   string                 `json:"protocol"`
	Parameters proofParameterManifest `json:"parameters"`
	Statement  *nizk.Statement        `json:"statement"`
}

// readCanonicalContext bounds stdin before allocating the complete statement.
func readCanonicalContext(source io.Reader) ([]byte, error) {
	if source == nil {
		return nil, errors.New("canonical statement reader is required")
	}
	data, err := io.ReadAll(io.LimitReader(source, maxCanonicalContextBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read canonical statement: %w", err)
	}
	if len(data) == 0 {
		return nil, errors.New("canonical statement must not be empty")
	}
	if len(data) > maxCanonicalContextBytes {
		return nil, fmt.Errorf("canonical statement exceeds %d bytes", maxCanonicalContextBytes)
	}
	return data, nil
}

// validateOutputPaths prevents one artifact path from overwriting the other.
func validateOutputPaths(proofPath, relationPath string) error {
	if strings.TrimSpace(proofPath) == "" || strings.TrimSpace(relationPath) == "" {
		return errors.New("proof and relation output paths are required")
	}
	proofAbs, err := filepath.Abs(proofPath)
	if err != nil {
		return fmt.Errorf("resolve proof output path: %w", err)
	}
	relationAbs, err := filepath.Abs(relationPath)
	if err != nil {
		return fmt.Errorf("resolve relation output path: %w", err)
	}
	proofAbs = filepath.Clean(proofAbs)
	relationAbs = filepath.Clean(relationAbs)
	same := proofAbs == relationAbs
	if runtime.GOOS == "windows" {
		same = strings.EqualFold(proofAbs, relationAbs)
	}
	if same {
		return errors.New("proof and relation output paths must be different")
	}
	for _, path := range []string{proofAbs, relationAbs} {
		if _, err := os.Stat(path); err == nil {
			return fmt.Errorf("refusing to overwrite existing artifact: %s", path)
		} else if !os.IsNotExist(err) {
			return fmt.Errorf("check output path %s: %w", path, err)
		}
	}
	return nil
}

func marshalPublicRelation(
	params *nizk.Params,
	statement *nizk.Statement,
	baseStatement *nizk.Statement,
	baseK, baseL, unitCount int,
	contextDigest [32]byte,
) ([]byte, error) {
	if params == nil || statement == nil || baseStatement == nil || baseK <= 0 || baseL <= 0 || unitCount <= 0 {
		return nil, errors.New("complete proof parameters, statement, and base dimensions are required")
	}
	baseParams := *params
	baseParams.K, baseParams.L = baseK, baseL
	baseDigest, err := baseRelationDigest(&baseParams, baseStatement)
	if err != nil {
		return nil, err
	}
	manifest := proofParameterManifest{
		Version:            "lnp22-context-probe-artifact-v1",
		Backend:            "LNP22",
		Revision:           pinnedLNP22Revision,
		ContextDomain:      contextDomain,
		ContextDigest:      hex.EncodeToString(contextDigest[:]),
		BaseRelationSHA256: baseDigest,
		ContextUnitCount:   unitCount,
		Q:                  params.Ring.Q,
		N:                  params.Ring.N,
		BaseK:              baseK,
		BaseL:              baseL,
		K:                  params.K,
		L:                  params.L,
		Kappa:              params.Kappa,
		Beta:               params.Beta,
		Sigma:              params.Sigma,
		BoundZ:             params.BoundZ,
	}
	return json.Marshal(publicRelation{
		Protocol:   "lnp22-linear-context-probe-v1",
		Parameters: manifest,
		Statement:  statement,
	})
}

// verifySerializedArtifacts reconstructs pinned public parameters, checks the
// context augmentation shape, then verifies a proof using only serialized
// relation/proof artifacts and canonical public context bytes.
func verifySerializedArtifacts(contextBytes, relationBytes, proofBytes []byte, trustedBaseRelationSHA256 string) (bool, error) {
	if len(contextBytes) == 0 || len(contextBytes) > maxCanonicalContextBytes {
		return false, fmt.Errorf("context bytes size must be between 1 and %d bytes", maxCanonicalContextBytes)
	}
	if len(relationBytes) == 0 || len(relationBytes) > maxProbeArtifactBytes {
		return false, fmt.Errorf("relation artifact size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	if len(proofBytes) == 0 || len(proofBytes) > maxProbeArtifactBytes {
		return false, fmt.Errorf("proof artifact size must be between 1 and %d bytes", maxProbeArtifactBytes)
	}
	var relation publicRelation
	if err := json.Unmarshal(relationBytes, &relation); err != nil {
		return false, fmt.Errorf("decode relation artifact: %w", err)
	}
	manifest := relation.Parameters
	if relation.Protocol != "lnp22-linear-context-probe-v1" ||
		manifest.Version != "lnp22-context-probe-artifact-v1" ||
		manifest.Backend != "LNP22" || manifest.Revision != pinnedLNP22Revision ||
		manifest.ContextDomain != contextDomain {
		return false, errors.New("relation artifact protocol or backend pin is unsupported")
	}
	if relation.Statement == nil {
		return false, errors.New("relation artifact is missing its public statement")
	}
	units, digest, err := deriveUnits(contextBytes, manifest.Q)
	if err != nil {
		return false, err
	}
	if manifest.ContextDigest != hex.EncodeToString(digest[:]) || manifest.ContextUnitCount != len(units) {
		return false, errors.New("canonical context does not match relation artifact digest")
	}
	if !isSHA256Hex(trustedBaseRelationSHA256) || manifest.BaseRelationSHA256 != trustedBaseRelationSHA256 {
		return false, errors.New("relation artifact does not match verifier trusted base relation digest")
	}
	if manifest.Q != 8_380_417 || manifest.N != 256 || manifest.BaseK != 4 || manifest.BaseL != 5 ||
		manifest.K != manifest.BaseK+len(units) || manifest.L != manifest.BaseL+len(units) ||
		manifest.Kappa != 60 || manifest.Beta != 1 || manifest.Sigma != 350 || manifest.BoundZ != 1400 {
		return false, errors.New("relation artifact does not match the pinned LNP22 probe parameter set")
	}
	if len(relation.Statement.A) != manifest.K || len(relation.Statement.T) != manifest.K {
		return false, errors.New("relation artifact matrix dimensions do not match its parameter manifest")
	}
	for row := 0; row < manifest.K; row++ {
		if len(relation.Statement.A[row]) != manifest.L {
			return false, errors.New("relation artifact matrix is not rectangular")
		}
		for column := 0; column < manifest.L; column++ {
			if !canonicalPolynomial(relation.Statement.A[row][column], manifest.N, manifest.Q) {
				return false, errors.New("relation artifact contains a non-canonical polynomial")
			}
		}
		if !canonicalPolynomial(relation.Statement.T[row], manifest.N, manifest.Q) {
			return false, errors.New("relation artifact target contains an invalid polynomial")
		}
	}
	proofRing, err := ring.New(manifest.N, manifest.Q)
	if err != nil {
		return false, fmt.Errorf("rebuild proof ring: %w", err)
	}
	baseParams := *paramsForManifest(manifest, proofRing)
	baseParams.K, baseParams.L = manifest.BaseK, manifest.BaseL
	baseStatement := &nizk.Statement{
		A: make(ring.PolyMat, manifest.BaseK),
		T: make(ring.PolyVec, manifest.BaseK),
	}
	for row := 0; row < manifest.BaseK; row++ {
		baseStatement.A[row] = append(ring.PolyVec(nil), relation.Statement.A[row][:manifest.BaseL]...)
		baseStatement.T[row] = relation.Statement.T[row]
	}
	actualBaseDigest, err := baseRelationDigest(&baseParams, baseStatement)
	if err != nil {
		return false, err
	}
	if actualBaseDigest != trustedBaseRelationSHA256 || actualBaseDigest != manifest.BaseRelationSHA256 {
		return false, errors.New("relation artifact does not match verifier trusted base relation digest")
	}
	if !contextAugmentationMatches(relation.Statement, manifest, units) {
		return false, errors.New("relation artifact context rows do not match the canonical statement")
	}

	params := paramsForManifest(manifest, proofRing)
	if err := params.Validate(); err != nil {
		return false, fmt.Errorf("validate proof parameter manifest: %w", err)
	}
	var proof nizk.LinearProof
	if err := json.Unmarshal(proofBytes, &proof); err != nil {
		return false, fmt.Errorf("decode proof artifact: %w", err)
	}
	if !validProofShape(proof, manifest.K, manifest.L, manifest.N, manifest.Q) {
		return false, errors.New("proof artifact has invalid dimensions")
	}
	return nizk.VerifyLinear(params, relation.Statement, &proof), nil
}

func paramsForManifest(manifest proofParameterManifest, proofRing *ring.Ring) *nizk.Params {
	return &nizk.Params{
		Ring: proofRing, K: manifest.K, L: manifest.L, Kappa: manifest.Kappa,
		Beta: manifest.Beta, Sigma: manifest.Sigma, BoundZ: manifest.BoundZ,
	}
}

func isSHA256Hex(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && hex.EncodeToString(decoded) == value
}

func baseRelationDigest(params *nizk.Params, statement *nizk.Statement) (string, error) {
	if params == nil || params.Ring == nil || statement == nil || params.K <= 0 || params.L <= 0 ||
		len(statement.A) != params.K || len(statement.T) != params.K {
		return "", errors.New("complete base relation parameters and statement are required")
	}
	for row := 0; row < params.K; row++ {
		if len(statement.A[row]) != params.L || !canonicalPolynomial(statement.T[row], params.Ring.N, params.Ring.Q) {
			return "", errors.New("base relation dimensions or target polynomial are invalid")
		}
		for column := 0; column < params.L; column++ {
			if !canonicalPolynomial(statement.A[row][column], params.Ring.N, params.Ring.Q) {
				return "", errors.New("base relation contains a non-canonical polynomial")
			}
		}
	}
	descriptor := struct {
		Protocol string          `json:"protocol"`
		Q        int64           `json:"q"`
		N        int             `json:"n"`
		K        int             `json:"k"`
		L        int             `json:"l"`
		Kappa    int             `json:"kappa"`
		Beta     int64           `json:"beta"`
		Sigma    float64         `json:"sigma"`
		BoundZ   int64           `json:"bound_z"`
		A        *nizk.Statement `json:"statement"`
	}{
		Protocol: "lnp22-registered-base-linear-relation-v1",
		Q:        params.Ring.Q, N: params.Ring.N, K: params.K, L: params.L,
		Kappa: params.Kappa, Beta: params.Beta, Sigma: params.Sigma, BoundZ: params.BoundZ,
		A: statement,
	}
	encoded, err := json.Marshal(descriptor)
	if err != nil {
		return "", fmt.Errorf("encode canonical base relation: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:]), nil
}

func contextAugmentationMatches(statement *nizk.Statement, manifest proofParameterManifest, units []int64) bool {
	for row := 0; row < manifest.BaseK; row++ {
		for column := manifest.BaseL; column < manifest.L; column++ {
			if !zeroPolynomial(statement.A[row][column]) {
				return false
			}
		}
	}
	for index, unit := range units {
		row := manifest.BaseK + index
		contextColumn := manifest.BaseL + index
		for column := 0; column < manifest.L; column++ {
			for coefficient, value := range statement.A[row][column] {
				if column == contextColumn && coefficient == 0 {
					if value != unit {
						return false
					}
				} else if value != 0 {
					return false
				}
			}
		}
		for coefficient, value := range statement.T[row] {
			if coefficient == 0 {
				if value != unit {
					return false
				}
			} else if value != 0 {
				return false
			}
		}
	}
	return true
}

func zeroPolynomial(polynomial ring.Poly) bool {
	for _, coefficient := range polynomial {
		if coefficient != 0 {
			return false
		}
	}
	return true
}

func canonicalPolynomial(polynomial ring.Poly, degree int, modulus int64) bool {
	if len(polynomial) != degree {
		return false
	}
	for _, coefficient := range polynomial {
		if coefficient < 0 || coefficient >= modulus {
			return false
		}
	}
	return true
}

func validProofShape(proof nizk.LinearProof, rows, columns, degree int, modulus int64) bool {
	if len(proof.W) != rows || len(proof.Z) != columns {
		return false
	}
	for _, polynomial := range proof.W {
		if !canonicalPolynomial(polynomial, degree, modulus) {
			return false
		}
	}
	for _, polynomial := range proof.Z {
		if !canonicalPolynomial(polynomial, degree, modulus) {
			return false
		}
	}
	return true
}

// deriveUnits encodes a SHA3-256 digest of canonical statement bytes as
// nonzero field elements. The encoding is injective for the returned length.
func deriveUnits(statement []byte, modulus int64) ([]int64, [32]byte, error) {
	return deriveUnitsWithDomain(statement, modulus, contextDomain)
}

// deriveUnitsWithDomain encodes a SHA3-256 digest of canonical statement
// bytes under a protocol-specific domain as nonzero field elements. The
// encoding is injective for the returned length.
func deriveUnitsWithDomain(statement []byte, modulus int64, domain string) ([]int64, [32]byte, error) {
	var zeroDigest [32]byte
	if modulus < 3 || !big.NewInt(modulus).ProbablyPrime(64) {
		return nil, zeroDigest, errors.New("context modulus must be an odd prime")
	}
	if statement == nil {
		return nil, zeroDigest, errors.New("canonical statement must not be nil")
	}
	if domain == "" {
		return nil, zeroDigest, errors.New("context domain must not be empty")
	}

	hash := sha3.New256()
	_, _ = hash.Write([]byte(domain))
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(statement)))
	_, _ = hash.Write(length[:])
	_, _ = hash.Write(statement)
	digestBytes := hash.Sum(nil)
	var digest [32]byte
	copy(digest[:], digestBytes)

	base := big.NewInt(modulus - 1)
	capacity := big.NewInt(1)
	unitCount := 0
	target := new(big.Int).Lsh(big.NewInt(1), 8*uint(len(digest)))
	for capacity.Cmp(target) < 0 {
		capacity.Mul(capacity, base)
		unitCount++
	}

	remaining := new(big.Int).SetBytes(digest[:])
	units := make([]int64, 0, unitCount)
	for range unitCount {
		quotient, digit := new(big.Int), new(big.Int)
		quotient.QuoRem(remaining, base, digit)
		units = append(units, digit.Int64()+1)
		remaining = quotient
	}
	if remaining.Sign() != 0 {
		return nil, zeroDigest, errors.New("context digest did not fit in its field limbs")
	}
	return units, digest, nil
}

// augmentLinearRelation adds equations h_i*b_i = h_i, with b_i fixed to one.
// Each h_i is a nonzero field element and therefore invertible. This makes the
// public linear statement depend on the canonical context without changing the
// original relation. It remains an experimental construction, not an audited
// protocol adaptation.
func augmentLinearRelation(
	params *nizk.Params,
	statement *nizk.Statement,
	witness *nizk.Witness,
	units []int64,
) (*nizk.Params, *nizk.Statement, *nizk.Witness, error) {
	if params == nil || statement == nil || witness == nil {
		return nil, nil, nil, errors.New("parameters, statement, and witness are required")
	}
	if len(units) == 0 {
		return nil, nil, nil, errors.New("at least one context unit is required")
	}
	if err := params.Validate(); err != nil {
		return nil, nil, nil, fmt.Errorf("validate base parameters: %w", err)
	}
	if params.Beta < 1 || len(statement.A) != params.K || len(statement.T) != params.K || len(witness.S) != params.L {
		return nil, nil, nil, errors.New("base relation dimensions or witness bound are invalid")
	}
	for _, row := range statement.A {
		if len(row) != params.L {
			return nil, nil, nil, errors.New("base relation matrix is not rectangular")
		}
	}
	if params.Ring.VecInfNorm(witness.S) > params.Beta || !params.Ring.VecEqual(params.Ring.MatVecMul(statement.A, witness.S), statement.T) {
		return nil, nil, nil, errors.New("base witness does not satisfy the short linear relation")
	}
	for _, unit := range units {
		if unit <= 0 || unit >= params.Ring.Q {
			return nil, nil, nil, errors.New("context units must be nonzero elements below q")
		}
	}

	augmentedParams := *params
	augmentedParams.K += len(units)
	augmentedParams.L += len(units)
	augmentedMatrix := params.Ring.NewPolyMat(augmentedParams.K, augmentedParams.L)
	augmentedTarget := params.Ring.NewPolyVec(augmentedParams.K)
	augmentedWitness := params.Ring.NewPolyVec(augmentedParams.L)
	for row := range statement.A {
		augmentedTarget[row] = append(ring.Poly(nil), statement.T[row]...)
		for column := range statement.A[row] {
			augmentedMatrix[row][column] = append(ring.Poly(nil), statement.A[row][column]...)
		}
	}
	for column := range witness.S {
		augmentedWitness[column] = append(ring.Poly(nil), witness.S[column]...)
	}
	for index, unit := range units {
		row := params.K + index
		column := params.L + index
		constant := params.Ring.NewPoly()
		constant[0] = unit
		augmentedMatrix[row][column] = constant
		augmentedTarget[row] = append(ring.Poly(nil), constant...)
		augmentedWitness[column] = params.Ring.One()
	}
	if params.Ring.VecInfNorm(augmentedWitness) > augmentedParams.Beta || !params.Ring.VecEqual(params.Ring.MatVecMul(augmentedMatrix, augmentedWitness), augmentedTarget) {
		return nil, nil, nil, errors.New("augmented witness does not satisfy the augmented relation")
	}

	return &augmentedParams,
		&nizk.Statement{A: augmentedMatrix, T: augmentedTarget},
		&nizk.Witness{S: augmentedWitness}, nil
}
