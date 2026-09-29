package openingprobe

import (
	"bytes"
	"testing"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

func TestOpeningRelationAcceptsCallerPayloadAndBindsItsCommitment(t *testing.T) {
	statement := validOpeningStatement()
	statement.CarrierCount = 16_000_000
	context, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal verifier-pinned statement: %v", err)
	}
	firstPayload := bytes.Repeat([]byte{0x35}, openingPayloadBytes)
	secondPayload := bytes.Repeat([]byte{0xCA}, openingPayloadBytes)
	firstFixture, err := newOpeningFixtureWithRankAndPayload(context, 512, firstPayload)
	if err != nil {
		t.Fatalf("build first payload opening: %v", err)
	}
	secondFixture, err := newOpeningFixtureWithRankAndPayload(context, 512, secondPayload)
	if err != nil {
		t.Fatalf("build second payload opening: %v", err)
	}
	firstCommitment, err := encodeOpeningCommitment(firstFixture.publicAssignment.CommitmentNTT, 512)
	if err != nil {
		t.Fatalf("encode first payload commitment: %v", err)
	}
	secondCommitment, err := encodeOpeningCommitment(secondFixture.publicAssignment.CommitmentNTT, 512)
	if err != nil {
		t.Fatalf("encode second payload commitment: %v", err)
	}
	if bytes.Equal(firstCommitment, secondCommitment) {
		t.Fatal("distinct caller payloads unexpectedly produced the same public commitment")
	}

	prover, verifier, err := buckler.Compile(512, &openingCircuit[*zp.Uint]{
		NTTChecker: buckler.NewNTTChecker[*zp.Uint](512),
	}, firstFixture.crs)
	if err != nil {
		t.Fatalf("compile payload-opening relation: %v", err)
	}
	for name, fixture := range map[string]*openingFixture{
		"first payload":  firstFixture,
		"second payload": secondFixture,
	} {
		proof, proveErr := prover.Prove(&fixture.proverAssignment)
		if proveErr != nil {
			t.Fatalf("prove %s: %v", name, proveErr)
		}
		valid, verifyErr := verifyOpeningAtRank(verifier, 512, context,
			fixture.publicAssignment.CommitmentNTT, proof)
		if verifyErr != nil || !valid {
			t.Fatalf("verify %s: valid=%v err=%v", name, valid, verifyErr)
		}
	}
	if _, err := newOpeningFixtureWithRankAndPayload(context, 512, firstPayload[:len(firstPayload)-1]); err == nil {
		t.Fatal("accepted payload with the wrong byte length")
	}
}
