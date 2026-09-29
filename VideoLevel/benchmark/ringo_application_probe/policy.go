package openingprobe

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

const maxOpeningSessions = 4096

type openingSession struct {
	statement        []byte
	commitmentDigest [32]byte
	expiresAt        time.Time
	pending          bool
	spent            bool
}

// openingVerifierPolicy is a process-local research policy gate. A production
// verifier needs durable, shared replay state and trusted session issuance.
type openingVerifierPolicy struct {
	mu       sync.Mutex
	rank     int
	sessions map[[32]byte]*openingSession
}

func newOpeningVerifierPolicy(rank int) *openingVerifierPolicy {
	return &openingVerifierPolicy{rank: rank, sessions: make(map[[32]byte]*openingSession)}
}

// Register pins the exact statement and canonical public commitment bytes plus
// a server-side expiry for one challenge. This registry state is verifier
// authority and must never be sourced from the incoming envelope.
func (p *openingVerifierPolicy) Register(statementBytes, expectedCommitmentBytes []byte, expiresAt, now time.Time) error {
	if p == nil {
		return errors.New("opening verifier policy is required")
	}
	if err := validateOpeningCommitmentRank(p.rank); err != nil {
		return err
	}
	statement, err := parseOpeningStatement(statementBytes)
	if err != nil {
		return fmt.Errorf("parse registered session statement: %w", err)
	}
	if !expiresAt.After(now) {
		return errors.New("opening session expiry must be in the future")
	}
	if _, err := decodeOpeningCommitment(expectedCommitmentBytes, p.rank); err != nil {
		return fmt.Errorf("decode verifier-registered public commitment: %w", err)
	}
	canonical, err := marshalOpeningStatement(statement)
	if err != nil || !bytes.Equal(canonical, statementBytes) {
		return errors.New("registered session statement is not canonical")
	}

	p.mu.Lock()
	defer p.mu.Unlock()
	if p.sessions == nil {
		p.sessions = make(map[[32]byte]*openingSession)
	}
	for challenge, session := range p.sessions {
		if !now.Before(session.expiresAt) && !session.pending {
			delete(p.sessions, challenge)
		}
	}
	if _, exists := p.sessions[statement.SessionChallenge]; exists {
		return errors.New("opening session challenge is already registered")
	}
	if len(p.sessions) >= maxOpeningSessions {
		return errors.New("opening verifier session limit reached")
	}
	p.sessions[statement.SessionChallenge] = &openingSession{
		statement:        append([]byte(nil), statementBytes...),
		commitmentDigest: sha256.Sum256(expectedCommitmentBytes),
		expiresAt:        expiresAt,
	}
	return nil
}

// VerifyAndConsume verifies a fixed-profile envelope under a verifier-pinned
// statement, enforcing expiry and one-time challenge use in this process.
// Failed/malformed proofs do not consume a session. Concurrent submissions of
// the same challenge cannot both enter proof verification.
func (p *openingVerifierPolicy) VerifyAndConsume(
	envelope []byte,
	verifier *buckler.Verifier[*zp.Uint],
	now func() time.Time,
) (bool, error) {
	if p == nil {
		return false, errors.New("opening verifier policy is required")
	}
	if now == nil {
		return false, errors.New("opening verifier clock is required")
	}
	if verifier == nil {
		return false, errors.New("opening proof verifier is required")
	}
	statementBytes, commitmentBytes, statement, err := peekOpeningTransportStatement(envelope, p.rank)
	if err != nil {
		return false, err
	}
	challenge := statement.SessionChallenge

	p.mu.Lock()
	session, exists := p.sessions[challenge]
	if !exists {
		p.mu.Unlock()
		return false, errors.New("opening session is unknown or no longer registered")
	}
	if !bytes.Equal(session.statement, statementBytes) {
		p.mu.Unlock()
		return false, errors.New("opening statement differs from verifier-pinned session policy")
	}
	if sha256.Sum256(commitmentBytes) != session.commitmentDigest {
		p.mu.Unlock()
		return false, errors.New("opening public commitment differs from verifier-registered target")
	}
	if !now().Before(session.expiresAt) {
		p.mu.Unlock()
		return false, errors.New("opening session has expired")
	}
	if session.pending || session.spent {
		p.mu.Unlock()
		return false, errors.New("opening session challenge was already used")
	}
	session.pending = true
	p.mu.Unlock()

	accepted := false
	defer func() {
		p.mu.Lock()
		session.pending = false
		if accepted {
			session.spent = true
		}
		p.mu.Unlock()
	}()

	decoded, err := decodeOpeningTransportEnvelope(envelope, p.rank)
	if err != nil {
		return false, err
	}
	valid, err := verifyOpeningAtRank(verifier, p.rank, decoded.StatementBytes,
		decoded.Commitment, decoded.Proof)
	if err != nil {
		return false, fmt.Errorf("verify opening proof: %w", err)
	}
	if !valid {
		return false, errors.New("opening proof was rejected")
	}
	if !now().Before(session.expiresAt) {
		return false, errors.New("opening session expired during proof verification")
	}
	accepted = true
	return true, nil
}
