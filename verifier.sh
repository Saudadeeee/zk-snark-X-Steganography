#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROOF_FILE="${1:-proof.json}"
PUBLIC_FILE="${2:-public.json}"
VKEY_FILE="verification_key.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}ZK-SNARK Steganography Verifier${NC}"
echo "===================================="

# Check if required files exist
if [ ! -f "$VKEY_FILE" ]; then
    echo -e "${RED}Error: Verification key '$VKEY_FILE' not found${NC}"
    echo "Please run the prover first to generate the verification key"
    exit 1
fi

if [ ! -f "$PROOF_FILE" ]; then
    echo -e "${RED}Error: Proof file '$PROOF_FILE' not found${NC}"
    echo "Usage: ./verifier.sh [proof.json] [public.json]"
    exit 1
fi

if [ ! -f "$PUBLIC_FILE" ]; then
    echo -e "${RED}Error: Public inputs file '$PUBLIC_FILE' not found${NC}"
    echo "Usage: ./verifier.sh [proof.json] [public.json]"
    exit 1
fi

echo -e "${GREEN}Verification key: $VKEY_FILE${NC}"
echo -e "${GREEN}Proof file: $PROOF_FILE${NC}"
echo -e "${GREEN}Public inputs: $PUBLIC_FILE${NC}"

# Show public inputs if jq is available
if command -v jq &> /dev/null; then
    echo -e "\n${YELLOW}Public inputs summary:${NC}"
    jq . "$PUBLIC_FILE"
fi

# Verify the proof
echo -e "\n${YELLOW}Verifying proof...${NC}"
echo "Running: snarkjs groth16 verify verification_key.json public.json proof.json"

if snarkjs groth16 verify "$VKEY_FILE" "$PUBLIC_FILE" "$PROOF_FILE"; then
    echo -e "\n${GREEN}✓ PROOF VERIFICATION SUCCESSFUL!${NC}"
    echo -e "${GREEN}The steganographic embedding has been proven without revealing the secret.${NC}"
    exit 0
else
    echo -e "\n${RED}✗ PROOF VERIFICATION FAILED!${NC}"
    echo -e "${RED}The proof is invalid or the files are corrupted.${NC}"
    exit 1
fi