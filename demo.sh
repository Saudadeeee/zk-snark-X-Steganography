#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🚀 ZK-SNARK Steganography Complete Demo${NC}"
echo "================================================="
echo

SECRET="1010110011010101"
MESSAGE="10110011"
COVER_IMG="testvectors/cover_16x16.png"
STEGO_IMG="stego_demo.png"

echo -e "${YELLOW}Demo Parameters:${NC}"
echo "Secret:  $SECRET (binary) = $((2#$SECRET)) (decimal)"
echo "Message: $MESSAGE (binary) = $((2#$MESSAGE)) (decimal)"
echo "Cover:   $COVER_IMG"
echo

# Step 1: Embed message
echo -e "${YELLOW}Step 1: Embedding message into cover image...${NC}"
python3 embed_message.py "$COVER_IMG" "$STEGO_IMG" "$SECRET" "$MESSAGE"
echo

# Step 2: Extract slots and generate input
echo -e "${YELLOW}Step 2: Extracting LSB slots and generating circuit input...${NC}"
python3 extract_slots.py "$STEGO_IMG" "$SECRET" "$MESSAGE" > input_demo.json
echo "✅ Circuit input generated: input_demo.json"
echo

# Show some input statistics
if command -v jq &> /dev/null; then
    echo -e "${BLUE}Input statistics:${NC}"
    echo "- Slots array length: $(jq '.slots | length' input_demo.json)"
    echo "- Message array length: $(jq '.message | length' input_demo.json)"
    echo "- Secret array length: $(jq '.secret | length' input_demo.json)"
    echo "- Message bits: $(jq -c '.message' input_demo.json)"
    echo "- First 10 slots: $(jq -c '.slots[:10]' input_demo.json)"
    echo
fi

# Step 3: Generate proof
echo -e "${YELLOW}Step 3: Generating zero-knowledge proof...${NC}"
./prover.sh input_demo.json
echo

# Step 4: Verify proof
echo -e "${YELLOW}Step 4: Verifying the proof...${NC}"
./verifier.sh
echo

# Demo success
echo -e "${GREEN}🎉 Demo completed successfully!${NC}"
echo
echo -e "${BLUE}What just happened:${NC}"
echo "1. ✅ Message '$MESSAGE' was embedded into image using secret '$SECRET'"
echo "2. ✅ Secret determined embedding positions: starting at position $((2#$SECRET))"
echo "3. ✅ Circuit proved that LSBs at those positions equal the claimed message"
echo "4. ✅ Proof was verified WITHOUT revealing the secret!"
echo
echo -e "${BLUE}Files created:${NC}"
echo "- $STEGO_IMG (steganographic image with embedded message)"
echo "- input_demo.json (circuit input with public/private signals)"
echo "- proof.json (zero-knowledge proof)"
echo "- public.json (public inputs: slots + message)" 
echo "- verification_key.json (public verification key)"
echo
echo -e "${YELLOW}🔒 Privacy preserved: The secret '$SECRET' was never revealed!${NC}"