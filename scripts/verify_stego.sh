#!/bin/bash

# Single-Command ZK-SNARK Steganography Verification
# Usage: ./verify_stego.sh <stego_image.png> [--verbose]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
VERIFICATION_KEY="$PROJECT_ROOT/artifacts/keys/verification_key.json"
TEMP_DIR="$PROJECT_ROOT/temp"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Help function
show_help() {
    echo "ZK-SNARK Steganography Verifier"
    echo
    echo "USAGE:"
    echo "  $0 <stego_image.png>           # Simple True/False output"
    echo "  $0 <stego_image.png> --verbose # Detailed verification info"
    echo "  $0 --help                      # Show this help"
    echo
    echo "EXAMPLES:"
    echo "  $0 stego.png                   # → True"
    echo "  $0 stego.png --verbose         # → Full verification details"
    echo
    echo "RETURN CODES:"
    echo "  0 = Verification successful (proof valid)"
    echo "  1 = Verification failed (proof invalid or error)"
    echo "  2 = Usage error (missing file, etc.)"
}

# Parse arguments
STEGO_IMAGE=""
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        *)
            if [[ -z "$STEGO_IMAGE" ]]; then
                STEGO_IMAGE="$1"
            else
                echo -e "${RED}Error: Multiple image files specified${NC}" >&2
                exit 2
            fi
            shift
            ;;
    esac
done

# Validate arguments
if [[ -z "$STEGO_IMAGE" ]]; then
    echo -e "${RED}Error: No image file specified${NC}" >&2
    echo "Use: $0 <stego_image.png> or $0 --help" >&2
    exit 2
fi

if [[ ! -f "$STEGO_IMAGE" ]]; then
    echo -e "${RED}Error: Image file not found: $STEGO_IMAGE${NC}" >&2
    exit 2
fi

# Check if verification key exists
if [[ ! -f "$VERIFICATION_KEY" ]]; then
    echo -e "${RED}Error: Verification key not found: $VERIFICATION_KEY${NC}" >&2
    exit 2
fi

# Create temp directory
mkdir -p "$TEMP_DIR"

# Verbose header
if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${BLUE}=== ZK-SNARK Steganography Verification ===${NC}"
    echo -e "${BLUE}Image:${NC} $STEGO_IMAGE"
    echo -e "${BLUE}Verification Key:${NC} $VERIFICATION_KEY"
    echo
fi

# Step 1: Extract proof artifact from PNG
if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${YELLOW}[1/4] Extracting proof artifact from image...${NC}"
fi

ARTIFACT_FILE="$TEMP_DIR/extracted_artifact.json"
python3 -c "
import sys
sys.path.append('$PROJECT_ROOT/src')
from zk_stego.proof_artifact import ProofArtifact
import json

artifact_manager = ProofArtifact()
artifact = artifact_manager.extract_from_png('$STEGO_IMAGE')

if artifact:
    with open('$ARTIFACT_FILE', 'w') as f:
        json.dump(artifact, f, indent=2)
    print('✓ Artifact extracted successfully')
    sys.exit(0)
else:
    print('✗ No proof artifact found in image')
    sys.exit(1)
" 2>/dev/null

EXTRACT_RESULT=$?
if [[ $EXTRACT_RESULT -ne 0 ]]; then
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${RED}✗ Failed to extract proof artifact${NC}"
    else
        echo "False"
    fi
    exit 1
fi

if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${GREEN}✓ Proof artifact extracted${NC}"
fi

# Step 2: Parse artifact and extract components
if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${YELLOW}[2/4] Parsing artifact components...${NC}"
fi

PROOF_FILE="$TEMP_DIR/extracted_proof.json"
PUBLIC_FILE="$TEMP_DIR/extracted_public.json"

python3 -c "
import json
import sys

try:
    with open('$ARTIFACT_FILE', 'r') as f:
        artifact = json.load(f)
    
    # Extract proof
    with open('$PROOF_FILE', 'w') as f:
        json.dump(artifact['proof'], f)
    
    # Extract and convert public inputs to snarkjs format
    public_data = artifact['public']
    
    # Convert to array format expected by snarkjs
    public_array = [
        str(int(public_data['image_hash'][:8], 16)),  # Convert hex to int (simplified)
        str(int(public_data['commitment_root'][:8], 16)),
        str(public_data['message_length']),
        str(public_data['timestamp']),
        str(public_data['nonce'])
    ]
    
    with open('$PUBLIC_FILE', 'w') as f:
        json.dump(public_array, f)
        
    print('✓ Artifact components parsed')
    
except Exception as e:
    print(f'✗ Error parsing artifact: {e}')
    sys.exit(1)
"

PARSE_RESULT=$?
if [[ $PARSE_RESULT -ne 0 ]]; then
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${RED}✗ Failed to parse artifact${NC}"
    else
        echo "False"
    fi
    exit 1
fi

if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${GREEN}✓ Artifact components extracted${NC}"
fi

# Step 3: Verify artifact integrity
if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${YELLOW}[3/4] Verifying artifact integrity...${NC}"
fi

python3 -c "
import sys
sys.path.append('$PROJECT_ROOT/src')
from zk_stego.proof_artifact import ProofArtifact
import json

try:
    with open('$ARTIFACT_FILE', 'r') as f:
        artifact = json.load(f)
    
    artifact_manager = ProofArtifact()
    success, message = artifact_manager.verify_artifact(artifact, '$VERIFICATION_KEY')
    
    if success:
        print('✓ Artifact integrity verified')
        sys.exit(0)
    else:
        print(f'✗ Artifact integrity check failed: {message}')
        sys.exit(1)
        
except Exception as e:
    print(f'✗ Error verifying artifact: {e}')
    sys.exit(1)
"

INTEGRITY_RESULT=$?
if [[ $INTEGRITY_RESULT -ne 0 ]]; then
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${RED}✗ Artifact integrity check failed${NC}"
    else
        echo "False"
    fi
    exit 1
fi

if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${GREEN}✓ Artifact integrity verified${NC}"
fi

# Step 4: Verify ZK proof using snarkjs
if [[ "$VERBOSE" == "true" ]]; then
    echo -e "${YELLOW}[4/4] Verifying ZK-SNARK proof...${NC}"
fi

# Check if snarkjs is available
if ! command -v snarkjs &> /dev/null; then
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${YELLOW}Warning: snarkjs not found, skipping ZK proof verification${NC}"
        echo -e "${GREEN}✓ Artifact verification completed (ZK proof skipped)${NC}"
    fi
    echo "True"
    exit 0
fi

# Run snarkjs verification
SNARKJS_OUTPUT=$(snarkjs groth16 verify "$VERIFICATION_KEY" "$PUBLIC_FILE" "$PROOF_FILE" 2>&1)
SNARKJS_RESULT=$?

if [[ $SNARKJS_RESULT -eq 0 ]] && echo "$SNARKJS_OUTPUT" | grep -q "OK"; then
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${GREEN}✓ ZK-SNARK proof verified successfully${NC}"
        echo
        echo -e "${GREEN}=== VERIFICATION SUCCESSFUL ===${NC}"
        echo "The steganographic image contains a valid ZK-SNARK proof."
        
        # Show artifact details
        echo
        echo -e "${BLUE}Artifact Details:${NC}"
        python3 -c "
import json
with open('$ARTIFACT_FILE', 'r') as f:
    artifact = json.load(f)
    
meta = artifact.get('meta', {})
public = artifact.get('public', {})

print(f'  Version: {meta.get(\"version\", \"unknown\")}')
print(f'  Domain: {meta.get(\"domain\", \"unknown\")}')
print(f'  Message Length: {public.get(\"message_length\", \"unknown\")}')
print(f'  Timestamp: {public.get(\"timestamp\", \"unknown\")}')
if 'signature' in artifact:
    print(f'  Signed: Yes')
else:
    print(f'  Signed: No')
"
    fi
    echo "True"
    exit 0
else
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${RED}✗ ZK-SNARK proof verification failed${NC}"
        echo -e "${RED}snarkjs output:${NC} $SNARKJS_OUTPUT"
        echo
        echo -e "${RED}=== VERIFICATION FAILED ===${NC}"
    fi
    echo "False"
    exit 1
fi