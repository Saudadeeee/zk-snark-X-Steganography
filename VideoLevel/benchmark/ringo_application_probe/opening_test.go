package openingprobe

import (
	"testing"
	"time"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

func TestOpeningRelationAndCapacityProbe(t *testing.T) {
	fixture, err := newOpeningFixture([]byte("verifier-session-and-canonical-video-context-A"))
	if err != nil {
		t.Fatalf("build opening fixture: %v", err)
	}
	compileStart := time.Now()
	prover, verifier, err := buckler.Compile(openingRank, &openingCircuit[*zp.Uint]{
		NTTChecker: buckler.NewNTTChecker[*zp.Uint](openingRank),
	}, fixture.crs)
	if err != nil {
		t.Fatalf("compile verifier-pinned relation: %v", err)
	}
	compileDuration := time.Since(compileStart)
	proveStart := time.Now()
	proof, err := prover.Prove(&fixture.proverAssignment)
	if err != nil {
		t.Fatalf("prove valid opening: %v", err)
	}
	proveDuration := time.Since(proveStart)
	verifyStart := time.Now()
	commitment := fixture.publicAssignment.CommitmentNTT
	valid, err := verifyOpening(verifier, fixture.context, commitment, proof)
	if err != nil {
		t.Fatalf("derive verifier public input: %v", err)
	}
	if !valid {
		t.Fatal("verifier rejected valid bounded payload opening")
	}
	verifyDuration := time.Since(verifyStart)
	t.Logf("compile=%s prove=%s verify=%s (single test sample)", compileDuration, proveDuration, verifyDuration)
	t.Logf("Jindo commitment-plus-proof estimate: %.0f bytes (not serialized proof)", prover.JindoParams.Size()/8)

	changedCommitment := commitment
	changedCommitment[0] = cloneVector(commitment[0])
	changedCommitment[0][0].Add(
		changedCommitment[0][0], new(zp.Uint).New().SetInt64(1),
	)
	valid, err = verifyOpening(verifier, fixture.context, changedCommitment, proof)
	if err != nil {
		t.Fatalf("derive changed commitment: %v", err)
	}
	if valid {
		t.Fatal("accepted proof with changed public commitment")
	}

	valid, err = verifyOpening(verifier, []byte("verifier-session-and-canonical-video-context-B"), commitment, proof)
	if err != nil {
		t.Fatalf("verify with changed context: %v", err)
	}
	if valid {
		t.Fatal("accepted original proof under changed public context with fixed commitment")
	}

	// Matrix, message and tail mask are never accepted from the prover by
	// verifyOpening: changing their fixture copies cannot change verification.
	fixture.publicAssignment.TailMask = make([]*zp.Uint, openingRank)
	fixture.publicAssignment.MatrixNTT[0][0] = make([]*zp.Uint, openingRank)
	valid, err = verifyOpening(verifier, fixture.context, commitment, proof)
	if err != nil || !valid {
		t.Fatalf("verifier used prover-side public vectors: valid=%v err=%v", valid, err)
	}
	if _, err = verifyOpening(verifier, fixture.context, [openingRows]buckler.PublicWitness[*zp.Uint]{commitment[0]}, proof); err == nil {
		t.Fatal("accepted malformed public commitment length")
	}

	badBit := fixture.withBitCoefficient(0, 2)
	badProof, err := prover.Prove(&badBit.proverAssignment)
	if err == nil {
		valid, verifyErr := verifyOpening(verifier, badBit.context, badBit.publicAssignment.CommitmentNTT, badProof)
		if verifyErr != nil {
			t.Fatalf("verify non-boolean witness: %v", verifyErr)
		}
		if valid {
			t.Fatal("accepted proof with a non-boolean payload coefficient")
		}
	}
	if err != nil {
		t.Logf("non-boolean witness rejected by prover: %v", err)
	} else {
		t.Log("non-boolean witness proof rejected by verifier")
	}

	badTail := fixture.withBitCoefficient(openingPayloadBytes*8, 1)
	tailProof, err := prover.Prove(&badTail.proverAssignment)
	if err == nil {
		valid, verifyErr := verifyOpening(verifier, badTail.context, badTail.publicAssignment.CommitmentNTT, tailProof)
		if verifyErr != nil {
			t.Fatalf("verify nonzero tail witness: %v", verifyErr)
		}
		if valid {
			t.Fatal("accepted proof with nonzero coefficient past the 32-byte payload")
		}
	}
	if err != nil {
		t.Logf("nonzero tail witness rejected by prover: %v", err)
	} else {
		t.Log("nonzero tail witness proof rejected by verifier")
	}

	// A caller of the low-level API can disable this constraint by choosing
	// a zero public mask. The application verifier must never accept that mask.
	zeroMask := make(buckler.PublicWitness[*zp.Uint], openingRank)
	for i := range zeroMask {
		zeroMask[i] = new(zp.Uint).New()
	}
	badTail.proverAssignment.TailMask = zeroMask
	badTail.publicAssignment.TailMask = zeroMask
	forgedPolicyProof, err := prover.Prove(&badTail.proverAssignment)
	if err != nil {
		t.Fatalf("prove witness under deliberately weak public mask: %v", err)
	}
	if !verifier.Verify(&badTail.publicAssignment, forgedPolicyProof) {
		t.Fatal("low-level verifier unexpectedly rejected weak-mask diagnostic")
	}
	valid, err = verifyOpening(verifier, badTail.context, badTail.publicAssignment.CommitmentNTT, forgedPolicyProof)
	if err != nil || valid {
		t.Fatalf("application verifier accepted weak-mask proof: valid=%v err=%v", valid, err)
	}

	badRandomness := fixture.withRandomCoefficient(0, 0, 2)
	randomnessProof, err := prover.Prove(&badRandomness.proverAssignment)
	if err == nil {
		valid, verifyErr := verifyOpening(verifier, badRandomness.context, badRandomness.publicAssignment.CommitmentNTT, randomnessProof)
		if verifyErr != nil {
			t.Fatalf("verify out-of-bound randomness: %v", verifyErr)
		}
		if valid {
			t.Fatal("accepted proof with coefficient 2 outside ternary opening randomness")
		}
	}
	if err != nil {
		t.Logf("out-of-bound randomness rejected by prover: %v", err)
	} else {
		t.Log("out-of-bound randomness proof rejected by verifier")
	}
}
