#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
INPUT_FILE="$1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}ZK-SNARK Steganography Prover${NC}"
echo "=================================="

if [ -z "$INPUT_FILE" ]; then
    echo -e "${RED}Error: Please provide input.json file${NC}"
    echo "Usage: ./prover.sh input.json"
    exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo -e "${RED}Error: Input file '$INPUT_FILE' not found${NC}"
    exit 1
fi

echo -e "${GREEN}Input file: $INPUT_FILE${NC}"

if [ ! -f "$BUILD_DIR/stego_check_v2.r1cs" ]; then
    echo -e "${YELLOW}Circuit not compiled. Compiling...${NC}"
    mkdir -p "$BUILD_DIR"
    
    echo "Running: ./circom stego_check_v2.circom --r1cs --wasm --sym -o build"
    ./circom stego_check_v2.circom --r1cs --wasm --sym -o "$BUILD_DIR"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}Circuit compilation failed!${NC}"
        exit 1
    fi
    echo -e "${GREEN}Circuit compiled successfully${NC}"
fi

# Check if trusted setup exists
if [ ! -f "$BUILD_DIR/circuit_0000.zkey" ]; then
    echo -e "${YELLOW}Trusted setup not found. Performing setup...${NC}"
    
    # Download powers of tau if not exists
    if [ ! -f "pot12_final.ptau" ]; then
        echo "Downloading powers of tau ceremony file..."
        wget https://storage.googleapis.com/zkevm/ptau/powersOfTau28_hez_final_12.ptau -O pot12_final.ptau
    fi
    
    echo "Running: snarkjs groth16 setup"
    snarkjs groth16 setup "$BUILD_DIR/stego_check_v2.r1cs" pot12_final.ptau "$BUILD_DIR/circuit_0000.zkey"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}Trusted setup failed!${NC}"
        exit 1
    fi
    
    echo "Exporting verification key..."
    snarkjs zkey export verificationkey "$BUILD_DIR/circuit_0000.zkey" verification_key.json
    
    echo -e "${GREEN}Trusted setup completed${NC}"
fi

# Generate witness
echo -e "${YELLOW}Generating witness...${NC}"
echo "Running: node build/stego_check_v2_js/generate_witness.js"

node "$BUILD_DIR/stego_check_v2_js/generate_witness.js" "$BUILD_DIR/stego_check_v2_js/stego_check_v2.wasm" "$INPUT_FILE" witness.wtns

if [ $? -ne 0 ]; then
    echo -e "${RED}Witness generation failed!${NC}"
    exit 1
fi
echo -e "${GREEN}Witness generated: witness.wtns${NC}"

# Generate proof
echo -e "${YELLOW}Generating proof...${NC}"
echo "Running: snarkjs groth16 prove"

snarkjs groth16 prove "$BUILD_DIR/circuit_0000.zkey" witness.wtns proof.json public.json

if [ $? -ne 0 ]; then
    echo -e "${RED}Proof generation failed!${NC}"
    exit 1
fi

echo -e "${GREEN}Proof generated successfully!${NC}"
echo -e "${GREEN}Files created:${NC}"
echo "  - proof.json (the zero-knowledge proof)"
echo "  - public.json (public inputs)"
echo "  - witness.wtns (witness file)"

if command -v jq &> /dev/null; then
    echo -e "\n${YELLOW}Proof summary:${NC}"
    echo "Public inputs:"
    jq . public.json
fi

echo -e "\n${GREEN}Ready for verification! Run: ./verifier.sh${NC}"