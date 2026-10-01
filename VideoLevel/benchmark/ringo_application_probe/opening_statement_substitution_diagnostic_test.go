package openingprobe

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"testing"
	"time"

	fiatshamir "github.com/consensys/gnark-crypto/fiat-shamir"
	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
	"github.com/sp301415/ringo-snark/math/bigpoly"
)

// This regression test checks public-instance binding on the application's
// commitment-opening circuit, not only on a toy circuit.
func TestOpeningRejectsStatementSubstitutionAfterFiatShamir(t *testing.T) {
	const rank = 256
	context, err := marshalOpeningStatement(validOpeningStatement())
	if err != nil {
		t.Fatal(err)
	}
	fixture, err := newOpeningFixtureWithRank(context, rank)
	if err != nil {
		t.Fatal(err)
	}
	var crs [16]byte
	if _, err := rand.Read(crs[:]); err != nil {
		t.Fatal(err)
	}
	prover, verifier, err := buckler.Compile(rank, &openingCircuit[*zp.Uint]{
		NTTChecker: buckler.NewNTTChecker[*zp.Uint](rank),
	}, crs[:])
	if err != nil {
		t.Fatal(err)
	}
	proof, err := prover.Prove(&fixture.proverAssignment)
	if err != nil {
		t.Fatal(err)
	}
	if len(proof.Witness) != 13 {
		t.Fatalf("unexpected opening proof commitment count: got %d, want 13", len(proof.Witness))
	}
	if !verifier.Verify(&fixture.publicAssignment, proof) {
		t.Fatal("verifier rejected the original valid opening statement")
	}

	// openingCircuit has eight first-round private witnesses, one linear mask,
	// one arithmetic quotient, and three linear-check polynomials.
	transcript := fiatshamir.NewTranscript(sha256.New(),
		"projConst", "arithBatchConst", "linCheckBatchConst",
		"linCheckConst", "sumCheckBatchConst", "evalPoint",
	)
	// Deliberately reproduce the old transcript that omitted public witness
	// values; the patch must make the verifier reject this legacy substitution.
	var encoded bytes.Buffer
	for i := 0; i < 8; i++ {
		proof.Witness[i].WriteToBuf(&encoded)
		transcript.Bind("projConst", encoded.Bytes())
		encoded.Reset()
	}
	if _, err := transcript.ComputeChallenge("projConst"); err != nil {
		t.Fatal(err)
	}
	proof.Witness[8].WriteToBuf(&encoded)
	transcript.Bind("arithBatchConst", encoded.Bytes())
	encoded.Reset()
	transcript.Bind("arithBatchConst", proof.LinCheckMaskSum.Marshal())
	for _, name := range []string{"arithBatchConst", "linCheckBatchConst", "linCheckConst", "sumCheckBatchConst"} {
		if _, err := transcript.ComputeChallenge(name); err != nil {
			t.Fatal(err)
		}
	}
	for i := 9; i < len(proof.Witness); i++ {
		proof.Witness[i].WriteToBuf(&encoded)
		transcript.Bind("evalPoint", encoded.Bytes())
		encoded.Reset()
	}
	evalBytes, err := transcript.ComputeChallenge("evalPoint")
	if err != nil {
		t.Fatal(err)
	}
	evalPoint := new(zp.Uint).SetBytes(evalBytes)

	// Encode X-evalPoint in Buckler's cyclic NTT representation and add it to
	// a public commitment row. The changed commitment is coefficient-wise
	// different, but its decoded polynomial evaluates to zero at evalPoint.
	deltaPoly := bigpoly.NewPoly[*zp.Uint](rank, false)
	deltaPoly.Coeffs[0].Neg(evalPoint)
	deltaPoly.Coeffs[1].SetInt64(1)
	deltaVector := make([]*zp.Uint, rank)
	for i := range deltaVector {
		deltaVector[i] = new(zp.Uint)
	}
	bigpoly.NewCyclicTransformer[*zp.Uint](rank).FwdNTTTo(deltaVector, deltaPoly.Coeffs)
	changedCommitment := fixture.publicAssignment.CommitmentNTT
	changedCommitment[0] = cloneVector(changedCommitment[0])
	for i := range deltaVector {
		changedCommitment[0][i].Add(changedCommitment[0][i], deltaVector[i])
	}
	originalCommitmentBytes, err := encodeOpeningCommitment(fixture.publicAssignment.CommitmentNTT, rank)
	if err != nil {
		t.Fatal(err)
	}
	changedCommitmentBytes, err := encodeOpeningCommitment(changedCommitment, rank)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(originalCommitmentBytes, changedCommitmentBytes) {
		t.Fatal("statement-substitution diagnostic did not change the commitment")
	}
	accepted, err := verifyOpeningAtRank(verifier, rank, context, changedCommitment, proof)
	if err != nil {
		t.Fatal(err)
	}
	if accepted {
		t.Fatal("opening verifier accepted a changed commitment with the original proof")
	}
	attackEnvelope, err := encodeOpeningTransportEnvelope(context, changedCommitment, proof, rank)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Unix(1_800_000_000, 0)
	policy := newOpeningVerifierPolicy(rank)
	if err := policy.Register(context, originalCommitmentBytes, now.Add(time.Minute), now); err != nil {
		t.Fatal(err)
	}
	policyAccepted, policyErr := policy.VerifyAndConsume(attackEnvelope, verifier, func() time.Time { return now })
	if policyErr == nil || policyAccepted {
		t.Fatalf("session policy accepted altered commitment: valid=%v err=%v", policyAccepted, policyErr)
	}
	t.Logf("rejected altered opening commitment at challenge %x", evalBytes)
	t.Log("verifier-pinned session policy rejected the same altered commitment")
}
