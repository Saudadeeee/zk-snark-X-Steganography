package main

import (
	"crypto/sha3"
	"encoding/binary"
	"errors"
	"fmt"
	"math/big"

	"github.com/KarpelesLab/lnp22/nizk"
	"github.com/KarpelesLab/lnp22/ring"
)

const contextDomain = "zkstego/lazer-context-binding/v1/"

// deriveUnits encodes a SHA3-256 digest of canonical statement bytes as
// nonzero field elements. The encoding is injective for the returned length.
func deriveUnits(statement []byte, modulus int64) ([]int64, [32]byte, error) {
	var zeroDigest [32]byte
	if modulus < 3 || !big.NewInt(modulus).ProbablyPrime(64) {
		return nil, zeroDigest, errors.New("context modulus must be an odd prime")
	}
	if statement == nil {
		return nil, zeroDigest, errors.New("canonical statement must not be nil")
	}

	hash := sha3.New256()
	_, _ = hash.Write([]byte(contextDomain))
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
