package openingprobe

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"testing"

	fiatshamir "github.com/consensys/gnark-crypto/fiat-shamir"
	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
	"github.com/sp301415/ringo-snark/math/bigpoly"
)

type diagnosticStatementCircuit struct {
	Public buckler.PublicWitness[*zp.Uint]
	Secret buckler.Witness[*zp.Uint]
}

func (c *diagnosticStatementCircuit) Define(ctx *buckler.Context[*zp.Uint]) {
	ctx.AddInfNormConstraint(c.Secret, 0)
	var equation buckler.ArithmeticConstraint[*zp.Uint]
	equation.AddTerm(c.Public)
	equation.AddTermWithConst(new(zp.Uint).SetInt64(-1), nil, c.Secret)
	ctx.AddArithmeticConstraint(equation)
}

// This regression test prevents post-challenge public-statement substitution.
func TestRejectStatementSubstitutionAfterFiatShamir(t *testing.T) {
	const rank = 256
	var crs [16]byte
	if _, err := rand.Read(crs[:]); err != nil {
		t.Fatal(err)
	}
	circuit := &diagnosticStatementCircuit{}
	prover, verifier, err := buckler.Compile(rank, circuit, crs[:])
	if err != nil {
		t.Fatal(err)
	}
	publicZero := make(buckler.PublicWitness[*zp.Uint], rank)
	for i := range publicZero {
		publicZero[i] = new(zp.Uint)
	}
	proof, err := prover.Prove(&diagnosticStatementCircuit{
		Public: publicZero,
		Secret: makeZeroWitness(rank),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(proof.Witness) != 2 {
		t.Fatalf("unexpected minimal arithmetic proof commitment count: %d", len(proof.Witness))
	}
	if !verifier.Verify(&diagnosticStatementCircuit{
		Public: publicZero,
		Secret: makeZeroWitness(rank),
	}, proof) {
		t.Fatal("verifier rejected the original valid all-zero statement")
	}

	transcript := fiatshamir.NewTranscript(sha256.New(),
		"projConst", "arithBatchConst", "linCheckBatchConst",
		"linCheckConst", "sumCheckBatchConst", "evalPoint",
	)
	// Reconstruct the vulnerable pre-patch transcript, which omitted public
	// witnesses, so the mutation targets the challenge the old verifier used.
	var encoded bytes.Buffer
	proof.Witness[0].WriteToBuf(&encoded)
	transcript.Bind("projConst", encoded.Bytes())
	encoded.Reset()
	if _, err := transcript.ComputeChallenge("projConst"); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"arithBatchConst", "linCheckBatchConst", "linCheckConst", "sumCheckBatchConst"} {
		if _, err := transcript.ComputeChallenge(name); err != nil {
			t.Fatal(err)
		}
	}
	proof.Witness[1].WriteToBuf(&encoded)
	transcript.Bind("evalPoint", encoded.Bytes())
	evalBytes, err := transcript.ComputeChallenge("evalPoint")
	if err != nil {
		t.Fatal(err)
	}
	evalPoint := new(zp.Uint).SetBytes(evalBytes)

	// In coefficient representation, x-evalPoint is nonzero, but it evaluates
	// to zero at the transcript's already-fixed challenge.
	deltaPoly := bigpoly.NewPoly[*zp.Uint](rank, false)
	deltaPoly.Coeffs[0].Neg(evalPoint)
	deltaPoly.Coeffs[1].SetInt64(1)
	deltaVector := make([]*zp.Uint, rank)
	for i := range deltaVector {
		deltaVector[i] = new(zp.Uint)
	}
	bigpoly.NewCyclicTransformer[*zp.Uint](rank).FwdNTTTo(deltaVector, deltaPoly.Coeffs)
	for i := range deltaVector {
		publicZero[i].Set(deltaVector[i])
	}

	// The only possible secret is zero, so this public vector is a false
	// statement at the coefficient level: Encode(Public)=X-evalPoint != 0.
	accepted := verifier.Verify(&diagnosticStatementCircuit{
		Public: publicZero,
		Secret: makeZeroWitness(rank),
	}, proof)
	if accepted {
		t.Fatal("verifier accepted a false public statement substituted after proof generation")
	}
	t.Logf("rejected false coefficient-level statement substituted after challenge %x", evalBytes)
}

func makeZeroWitness(rank int) buckler.Witness[*zp.Uint] {
	witness := make(buckler.Witness[*zp.Uint], rank)
	for i := range witness {
		witness[i] = new(zp.Uint)
	}
	return witness
}
