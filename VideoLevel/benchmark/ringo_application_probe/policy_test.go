package openingprobe

import (
	"sync"
	"testing"
	"time"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

func TestOpeningVerifierPolicyExpiryReplayAndStatementPinning(t *testing.T) {
	statement := validOpeningStatement()
	statementBytes, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal session statement: %v", err)
	}
	fixture, err := newOpeningFixture(statementBytes)
	if err != nil {
		t.Fatalf("build opening fixture: %v", err)
	}
	prover, verifier, err := buckler.Compile(openingRank, &openingCircuit[*zp.Uint]{
		NTTChecker: buckler.NewNTTChecker[*zp.Uint](openingRank),
	}, fixture.crs)
	if err != nil {
		t.Fatalf("compile verifier-pinned relation: %v", err)
	}
	proof, err := prover.Prove(&fixture.proverAssignment)
	if err != nil {
		t.Fatalf("prove registered opening: %v", err)
	}
	registeredCommitment, err := encodeOpeningCommitment(fixture.publicAssignment.CommitmentNTT, openingRank)
	if err != nil {
		t.Fatalf("encode registered public commitment: %v", err)
	}
	envelope, err := encodeOpeningTransportEnvelope(statementBytes, fixture.publicAssignment.CommitmentNTT, proof, openingRank)
	if err != nil {
		t.Fatalf("encode registered proof envelope: %v", err)
	}

	const nowUnix = int64(1_800_000_000)
	now := time.Unix(nowUnix, 0)
	verifierPolicy := newOpeningVerifierPolicy(openingRank)
	if err := verifierPolicy.Register(statementBytes, registeredCommitment, now.Add(time.Minute), now); err != nil {
		t.Fatalf("register valid session: %v", err)
	}
	clock := func() time.Time { return now }
	type result struct {
		accepted bool
		err      error
	}
	start := make(chan struct{})
	results := make(chan result, 2)
	var workers sync.WaitGroup
	for range 2 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			<-start
			accepted, verifyErr := verifierPolicy.VerifyAndConsume(envelope, verifier, clock)
			results <- result{accepted: accepted, err: verifyErr}
		}()
	}
	close(start)
	workers.Wait()
	close(results)
	acceptedCount, rejectedCount := 0, 0
	for outcome := range results {
		if outcome.accepted && outcome.err == nil {
			acceptedCount++
		} else if !outcome.accepted && outcome.err != nil {
			rejectedCount++
		}
	}
	if acceptedCount != 1 || rejectedCount != 1 {
		t.Fatalf("same-challenge concurrent submissions: accepted=%d rejected=%d; want exactly one each", acceptedCount, rejectedCount)
	}

	expiredPolicy := newOpeningVerifierPolicy(openingRank)
	if err := expiredPolicy.Register(statementBytes, registeredCommitment, now.Add(time.Second), now); err != nil {
		t.Fatalf("register expiring session: %v", err)
	}
	expiredClock := func() time.Time { return now.Add(time.Second) }
	accepted, err := expiredPolicy.VerifyAndConsume(envelope, verifier, expiredClock)
	if err == nil || accepted {
		t.Fatalf("expired session accepted: valid=%v err=%v", accepted, err)
	}

	unregisteredPolicy := newOpeningVerifierPolicy(openingRank)
	accepted, err = unregisteredPolicy.VerifyAndConsume(envelope, verifier, clock)
	if err == nil || accepted {
		t.Fatalf("unregistered session accepted: valid=%v err=%v", accepted, err)
	}

	changed := statement
	changed.VideoCommitment[0] ^= 1
	changedStatementBytes, err := marshalOpeningStatement(changed)
	if err != nil {
		t.Fatalf("marshal mismatched video statement: %v", err)
	}
	changedEnvelope, err := encodeOpeningTransportEnvelope(changedStatementBytes, fixture.publicAssignment.CommitmentNTT, proof, openingRank)
	if err != nil {
		t.Fatalf("encode mismatched video envelope: %v", err)
	}
	accepted, err = verifierPolicy.VerifyAndConsume(changedEnvelope, verifier, clock)
	if err == nil || accepted {
		t.Fatalf("statement not pinned to registered video/session: valid=%v err=%v", accepted, err)
	}
}

func TestOpeningVerifierPolicyDoesNotSpendSessionOnInvalidProof(t *testing.T) {
	statement := validOpeningStatement()
	statementBytes, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal session statement: %v", err)
	}
	fixture, err := newOpeningFixture(statementBytes)
	if err != nil {
		t.Fatalf("build opening fixture: %v", err)
	}
	prover, verifier, err := buckler.Compile(openingRank, &openingCircuit[*zp.Uint]{
		NTTChecker: buckler.NewNTTChecker[*zp.Uint](openingRank),
	}, fixture.crs)
	if err != nil {
		t.Fatalf("compile verifier-pinned relation: %v", err)
	}
	proof, err := prover.Prove(&fixture.proverAssignment)
	if err != nil {
		t.Fatalf("prove registered opening: %v", err)
	}
	now := time.Unix(1_800_000_000, 0)
	policy := newOpeningVerifierPolicy(openingRank)
	registeredCommitment, err := encodeOpeningCommitment(fixture.publicAssignment.CommitmentNTT, openingRank)
	if err != nil {
		t.Fatalf("encode registered public commitment: %v", err)
	}
	if err := policy.Register(statementBytes, registeredCommitment, now.Add(time.Minute), now); err != nil {
		t.Fatalf("register valid session: %v", err)
	}
	clock := func() time.Time { return now }

	// Produce a cryptographically valid proof for another bit payload under the
	// same public session. It must fail because policy pins the enrolled target,
	// not merely because the proof bytes are invalid.
	alternatePayload := defaultOpeningPayload()
	alternatePayload[0] ^= 0x80
	changedFixture, err := newOpeningFixtureWithRankAndPayload(statementBytes, openingRank, alternatePayload)
	if err != nil {
		t.Fatalf("build alternate valid payload opening: %v", err)
	}
	alternateProof, err := prover.Prove(&changedFixture.proverAssignment)
	if err != nil {
		t.Fatalf("prove alternate valid opening: %v", err)
	}
	alternateValid, err := verifyOpening(verifier, statementBytes, changedFixture.publicAssignment.CommitmentNTT, alternateProof)
	if err != nil || !alternateValid {
		t.Fatalf("alternate commitment proof fixture is not cryptographically valid: valid=%v err=%v", alternateValid, err)
	}
	invalidEnvelope, err := encodeOpeningTransportEnvelope(statementBytes, changedFixture.publicAssignment.CommitmentNTT, alternateProof, openingRank)
	if err != nil {
		t.Fatalf("encode alternate valid proof envelope: %v", err)
	}
	accepted, err := policy.VerifyAndConsume(invalidEnvelope, verifier, clock)
	if err == nil || accepted {
		t.Fatalf("valid proof for unregistered commitment accepted: valid=%v err=%v", accepted, err)
	}

	validEnvelope, err := encodeOpeningTransportEnvelope(statementBytes, fixture.publicAssignment.CommitmentNTT, proof, openingRank)
	if err != nil {
		t.Fatalf("encode valid proof envelope: %v", err)
	}
	accepted, err = policy.VerifyAndConsume(validEnvelope, verifier, clock)
	if err != nil || !accepted {
		t.Fatalf("invalid proof consumed the registered session: valid=%v err=%v", accepted, err)
	}
}
