package openingprobe

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"fmt"
	"math/bits"
	"reflect"
	"strconv"
	"testing"
	"time"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

func TestOpeningRelationAndCapacityProbe(t *testing.T) {
	statement := validOpeningStatement()
	context, err := marshalOpeningStatement(statement)
	if err != nil {
		t.Fatalf("marshal verifier-pinned public statement: %v", err)
	}
	fixture, err := newOpeningFixture(context)
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
	encodeStart := time.Now()
	encodedProof, err := encodeOpeningProof(proof)
	if err != nil {
		t.Fatalf("encode complete opening proof: %v", err)
	}
	encodeDuration := time.Since(encodeStart)
	decodeStart := time.Now()
	decodedProof, err := decodeOpeningProof(encodedProof)
	if err != nil {
		t.Fatalf("decode complete opening proof: %v", err)
	}
	decodeDuration := time.Since(decodeStart)
	canonicalProof, err := encodeOpeningProof(decodedProof)
	if err != nil || !bytes.Equal(encodedProof, canonicalProof) {
		t.Fatalf("proof codec failed canonical round trip: err=%v", err)
	}
	binaryEncodeStart := time.Now()
	binaryProof, err := encodeBinaryOpeningProof(proof)
	if err != nil {
		t.Fatalf("encode compact binary proof: %v", err)
	}
	binaryEncodeDuration := time.Since(binaryEncodeStart)
	binaryDecodeStart := time.Now()
	decodedBinaryProof, err := decodeBinaryOpeningProof(binaryProof)
	if err != nil {
		t.Fatalf("decode compact binary proof: %v", err)
	}
	binaryDecodeDuration := time.Since(binaryDecodeStart)
	canonicalBinary, err := encodeBinaryOpeningProof(decodedBinaryProof)
	if err != nil || !bytes.Equal(binaryProof, canonicalBinary) {
		t.Fatalf("binary proof codec failed canonical round trip: err=%v", err)
	}
	var compressed bytes.Buffer
	gzipWriter, err := gzip.NewWriterLevel(&compressed, gzip.BestCompression)
	if err != nil {
		t.Fatalf("create proof compression probe: %v", err)
	}
	gzipWriter.Header.ModTime = time.Time{}
	if _, err := gzipWriter.Write(encodedProof); err != nil {
		t.Fatalf("compress proof JSON: %v", err)
	}
	if err := gzipWriter.Close(); err != nil {
		t.Fatalf("finish proof compression probe: %v", err)
	}
	var compressedBinary bytes.Buffer
	binaryGzipWriter, err := gzip.NewWriterLevel(&compressedBinary, gzip.BestCompression)
	if err != nil {
		t.Fatalf("create binary proof compression probe: %v", err)
	}
	binaryGzipWriter.Header.ModTime = time.Time{}
	if _, err := binaryGzipWriter.Write(binaryProof); err != nil {
		t.Fatalf("compress binary proof: %v", err)
	}
	if err := binaryGzipWriter.Close(); err != nil {
		t.Fatalf("finish binary proof compression probe: %v", err)
	}
	for name, malformed := range map[string][]byte{
		"empty":               nil,
		"truncated":           encodedProof[:len(encodedProof)/2],
		"trailing whitespace": append(append([]byte(nil), encodedProof...), ' '),
		"second JSON value":   append(append([]byte(nil), encodedProof...), []byte(`{}`)...),
		"empty proof object":  []byte(`{"protocol":"zkstego-ringo-opening-probe-v1","proof":{}}`),
	} {
		if _, err := decodeOpeningProof(malformed); err == nil {
			t.Errorf("proof codec accepted malformed input (%s)", name)
		}
	}
	for name, malformed := range map[string][]byte{
		"empty":            nil,
		"truncated":        binaryProof[:len(binaryProof)/2],
		"trailing byte":    append(append([]byte(nil), binaryProof...), 0),
		"wrong magic":      append([]byte("BAD1"), binaryProof[len(openingBinaryMagic):]...),
		"empty proof body": append([]byte(openingBinaryMagic), 1, 0),
	} {
		if _, err := decodeBinaryOpeningProof(malformed); err == nil {
			t.Errorf("binary codec accepted malformed input (%s)", name)
		}
	}
	commitment := fixture.publicAssignment.CommitmentNTT
	commitmentBytes, err := encodeOpeningCommitment(commitment, openingRank)
	if err != nil {
		t.Fatalf("encode public commitment: %v", err)
	}
	decodedCommitment, err := decodeOpeningCommitment(commitmentBytes, openingRank)
	if err != nil {
		t.Fatalf("decode public commitment: %v", err)
	}
	transportEnvelope, err := encodeOpeningTransportEnvelope(fixture.context, decodedCommitment, proof, openingRank)
	if err != nil {
		t.Fatalf("encode complete in-band proof envelope: %v", err)
	}
	transportStart := time.Now()
	decodedTransport, err := decodeOpeningTransportEnvelope(transportEnvelope, openingRank)
	if err != nil {
		t.Fatalf("decode complete in-band proof envelope: %v", err)
	}
	transportDecodeDuration := time.Since(transportStart)
	verifyStart := time.Now()
	valid, err := verifyOpeningAtRank(verifier, openingRank, decodedTransport.StatementBytes,
		decodedTransport.Commitment, decodedTransport.Proof)
	if err != nil {
		t.Fatalf("verify decoded in-band envelope: %v", err)
	}
	if !valid {
		t.Fatal("verifier rejected valid opening decoded from the in-band envelope")
	}
	verifyDuration := time.Since(verifyStart)
	minimumEnvelopeBytes := openingTransportHeaderSize + len(fixture.context) + len(commitmentBytes) + len(binaryProof)
	if minimumEnvelopeBytes > len(transportEnvelope) {
		t.Fatalf("minimum transport fields (%d bytes) exceed fixed carrier profile (%d bytes)", minimumEnvelopeBytes, len(transportEnvelope))
	}
	badEnvelopeMagic := append([]byte(nil), transportEnvelope...)
	badEnvelopeMagic[0] ^= 1
	badEnvelopeLength := append([]byte(nil), transportEnvelope...)
	badEnvelopeLength[len(openingTransportMagic)+4+3]-- // commitment length, big-endian
	badEnvelopePadding := append([]byte(nil), transportEnvelope...)
	badEnvelopePadding[len(badEnvelopePadding)-1] = 1
	for name, malformed := range map[string][]byte{
		"truncated":         transportEnvelope[:len(transportEnvelope)-1],
		"bad magic":         badEnvelopeMagic,
		"forged field size": badEnvelopeLength,
		"nonzero padding":   badEnvelopePadding,
	} {
		if _, err := decodeOpeningTransportEnvelope(malformed, openingRank); err == nil {
			t.Errorf("accepted malformed fixed-profile envelope (%s)", name)
		}
	}
	changedSessionStatement := statement
	changedSessionStatement.SessionChallenge[0] ^= 1
	changedSessionContext, err := marshalOpeningStatement(changedSessionStatement)
	if err != nil {
		t.Fatalf("marshal changed-session statement: %v", err)
	}
	changedSessionEnvelope, err := encodeOpeningTransportEnvelope(changedSessionContext, decodedTransport.Commitment, decodedTransport.Proof, openingRank)
	if err != nil {
		t.Fatalf("encode changed-session envelope: %v", err)
	}
	changedSessionDecoded, err := decodeOpeningTransportEnvelope(changedSessionEnvelope, openingRank)
	if err != nil {
		t.Fatalf("decode changed-session envelope: %v", err)
	}
	valid, err = verifyOpeningAtRank(verifier, openingRank, changedSessionDecoded.StatementBytes,
		changedSessionDecoded.Commitment, changedSessionDecoded.Proof)
	if err != nil || valid {
		t.Fatalf("in-band envelope accepted under a changed session: valid=%v err=%v", valid, err)
	}
	t.Logf("compile=%s prove=%s verify=%s (single test sample)", compileDuration, proveDuration, verifyDuration)
	t.Logf("serialized complete Buckler proof: %d bytes", len(encodedProof))
	t.Logf("gzip JSON size at BestCompression: %d bytes", compressed.Len())
	t.Logf("gzip binary size at BestCompression: %d bytes", compressedBinary.Len())
	t.Logf("canonical binary size: %d bytes", len(binaryProof))
	proofValue := reflect.ValueOf(proof).Elem()
	for i := 0; i < proofValue.NumField(); i++ {
		field := proofValue.Type().Field(i)
		var fieldBytes bytes.Buffer
		if err := encodeProofValue(&fieldBytes, proofValue.Field(i)); err != nil {
			t.Fatalf("measure proof field %s: %v", field.Name, err)
		}
		t.Logf("binary proof field %s: %d bytes", field.Name, fieldBytes.Len())
		if field.Name == "EvalProof" {
			evaluation := proofValue.Field(i).Elem()
			for nested := 0; nested < evaluation.NumField(); nested++ {
				var nestedBytes bytes.Buffer
				if err := encodeProofValue(&nestedBytes, evaluation.Field(nested)); err != nil {
					t.Fatalf("measure evaluation field %s: %v", evaluation.Type().Field(nested).Name, err)
				}
				t.Logf("binary EvalProof.%s: %d bytes", evaluation.Type().Field(nested).Name, nestedBytes.Len())
			}
		}
		if field.Name == "Witness" {
			t.Logf("proof witness commitments: %d", proofValue.Field(i).Len())
		}
	}
	t.Logf("binary encode=%s decode=%s (single test sample)", binaryEncodeDuration, binaryDecodeDuration)
	t.Logf("JSON encode=%s decode=%s (single test sample)", encodeDuration, decodeDuration)
	t.Logf("canonical public commitment: %d bytes; minimum statement+commitment+proof envelope: %d bytes; fixed carrier envelope: %d bytes",
		len(commitmentBytes), minimumEnvelopeBytes, len(transportEnvelope))
	t.Logf("fixed in-band envelope decode=%s; decoded envelope proof verified (single test sample)", transportDecodeDuration)
	t.Logf("Jindo commitment-plus-proof estimate: %.0f bytes (separate estimate)", prover.JindoParams.Size()/8)
	for i, modulus := range prover.JindoParams.Operator().Modulus() {
		t.Logf("inner CRT modulus[%d] width: %d bits", i, bits.Len64(modulus.Value()))
	}
	for i, modulus := range prover.JindoParams.OutOperator().Modulus() {
		t.Logf("outer CRT modulus[%d] width: %d bits", i, bits.Len64(modulus.Value()))
	}

	changedCommitment := decodedTransport.Commitment
	changedCommitment[0] = cloneVector(commitment[0])
	changedCommitment[0][0].Add(
		changedCommitment[0][0], new(zp.Uint).New().SetInt64(1),
	)
	changedCommitmentEnvelope, err := encodeOpeningTransportEnvelope(fixture.context, changedCommitment, proof, openingRank)
	if err != nil {
		t.Fatalf("encode changed public commitment envelope: %v", err)
	}
	changedTransport, err := decodeOpeningTransportEnvelope(changedCommitmentEnvelope, openingRank)
	if err != nil {
		t.Fatalf("decode changed public commitment envelope: %v", err)
	}
	valid, err = verifyOpeningAtRank(verifier, openingRank, changedTransport.StatementBytes,
		changedTransport.Commitment, changedTransport.Proof)
	if err != nil {
		t.Fatalf("verify changed commitment envelope: %v", err)
	}
	if valid {
		t.Fatal("accepted in-band proof envelope with changed public commitment")
	}

	for name, mutate := range map[string]func(*openingStatement){
		"session challenge": func(s *openingStatement) { s.SessionChallenge[0] ^= 1 },
		"video commitment":  func(s *openingStatement) { s.VideoCommitment[0] ^= 1 },
		"carrier positions": func(s *openingStatement) { s.PositionsHash[0] ^= 1 },
		"codec policy":      func(s *openingStatement) { s.CodecPolicyID[0] ^= 1 },
		"registry epoch":    func(s *openingStatement) { s.RegistryEpoch++ },
		"carrier count":     func(s *openingStatement) { s.CarrierCount += 8 },
	} {
		changedStatement := statement
		mutate(&changedStatement)
		changedContext, marshalErr := marshalOpeningStatement(changedStatement)
		if marshalErr != nil {
			t.Fatalf("marshal statement with changed %s: %v", name, marshalErr)
		}
		valid, err = verifyOpening(verifier, changedContext, commitment, proof)
		if err != nil {
			t.Fatalf("verify with changed %s: %v", name, err)
		}
		if valid {
			t.Errorf("accepted original proof with changed %s and fixed commitment", name)
		}
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
	malformedProof := *decodedProof
	malformedProof.Witness = decodedProof.Witness[:1]
	if valid, err = verifyOpening(verifier, fixture.context, commitment, &malformedProof); err == nil || valid {
		t.Fatalf("malformed proof shape was not rejected safely: valid=%v err=%v", valid, err)
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

func TestOpeningRankSizeSweep(t *testing.T) {
	for _, rank := range []int{256, 512, 1024, 2048, 4096} {
		t.Run(strconv.Itoa(rank), func(t *testing.T) {
			statement := validOpeningStatement()
			statement.ParameterID = sha256.Sum256([]byte(fmt.Sprintf("ringo-probe-parameter-rank-%d", rank)))
			context, err := marshalOpeningStatement(statement)
			if err != nil {
				t.Fatalf("marshal rank-%d statement: %v", rank, err)
			}
			fixture, err := newOpeningFixtureWithRank(context, rank)
			if err != nil {
				t.Fatalf("build rank-%d fixture: %v", rank, err)
			}
			compileStart := time.Now()
			prover, verifier, err := buckler.Compile(rank, &openingCircuit[*zp.Uint]{
				NTTChecker: buckler.NewNTTChecker[*zp.Uint](rank),
			}, fixture.crs)
			if err != nil {
				t.Fatalf("compile rank-%d relation: %v", rank, err)
			}
			compileDuration := time.Since(compileStart)
			proveStart := time.Now()
			proof, err := prover.Prove(&fixture.proverAssignment)
			if err != nil {
				t.Fatalf("prove rank-%d opening: %v", rank, err)
			}
			proveDuration := time.Since(proveStart)
			encoded, err := encodeBinaryOpeningProof(proof)
			if err != nil {
				t.Fatalf("encode rank-%d proof: %v", rank, err)
			}
			var compressed bytes.Buffer
			gzipWriter, err := gzip.NewWriterLevel(&compressed, gzip.BestCompression)
			if err != nil {
				t.Fatalf("create rank-%d proof compressor: %v", rank, err)
			}
			if _, err := gzipWriter.Write(encoded); err != nil {
				t.Fatalf("compress rank-%d proof: %v", rank, err)
			}
			if err := gzipWriter.Close(); err != nil {
				t.Fatalf("finish rank-%d proof compression: %v", rank, err)
			}
			decoded, err := decodeBinaryOpeningProof(encoded)
			if err != nil {
				t.Fatalf("decode rank-%d proof: %v", rank, err)
			}
			verifyStart := time.Now()
			valid, err := verifyOpeningAtRank(verifier, rank, fixture.context,
				fixture.publicAssignment.CommitmentNTT, decoded)
			if err != nil || !valid {
				t.Fatalf("verify rank-%d decoded proof: valid=%v err=%v", rank, valid, err)
			}
			verifyDuration := time.Since(verifyStart)
			t.Logf("rank=%d compile=%s prove=%s verify=%s binary=%d bytes gzip=%d bytes Jindo-estimate=%.0f bytes",
				rank, compileDuration, proveDuration, verifyDuration, len(encoded), compressed.Len(), prover.JindoParams.Size()/8)
		})
	}
}
