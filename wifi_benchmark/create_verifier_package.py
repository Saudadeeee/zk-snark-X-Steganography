#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tạo Verifier Package - Gói phần mềm để gửi cho verifier
Bao gồm: code, verification key, và hướng dẫn setup
"""

import shutil
import json
from pathlib import Path
import sys
import io

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def create_verifier_package(output_dir: str = "verifier_package"):
    """
    Tạo package đầy đủ cho verifier
    """
    project_root = Path(__file__).parent.parent
    output_path = Path(output_dir)
    
    # Xóa thư mục cũ nếu có
    if output_path.exists():
        shutil.rmtree(output_path)
    
    output_path.mkdir(exist_ok=True, parents=True)
    
    print("=" * 80)
    print("TẠO VERIFIER PACKAGE")
    print("=" * 80)
    
    # 1. Copy source code
    print("\n[1/5] Copy source code...")
    src_dir = project_root / "src" / "zk_stego"
    dest_src_dir = output_path / "src" / "zk_stego"
    dest_src_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy các file cần thiết
    required_files = [
        "hybrid_proof_artifact.py",
        "chaos_embedding.py",
        "zk_proof_generator.py"
    ]
    
    for file in required_files:
        src_file = src_dir / file
        if src_file.exists():
            shutil.copy2(src_file, dest_src_dir / file)
            print(f"   ✓ Copied: {file}")
        else:
            print(f"   ⚠ Warning: {file} not found")
    
    # Tạo __init__.py cho verifier (không cần MetadataMessageGenerator)
    init_content = '''"""
ZK-SNARK Steganography Core Module - Verifier Version
"""

from .chaos_embedding import (
    ChaosGenerator,
    ChaosEmbedding,
    ChaosProofArtifact,
    generate_chaos_key_from_secret,
    validate_chaos_parameters
)

from .zk_proof_generator import ZKProofGenerator

from .hybrid_proof_artifact import (
    HybridProofArtifact,
    embed_chaos_proof,
    extract_chaos_proof,
    verify_chaos_stego
)

__all__ = [
    'ChaosGenerator',
    'ChaosEmbedding',
    'ChaosProofArtifact',
    'ZKProofGenerator',
    'HybridProofArtifact',
    'generate_chaos_key_from_secret',
    'validate_chaos_parameters',
    'embed_chaos_proof',
    'extract_chaos_proof',
    'verify_chaos_stego'
]
'''
    init_file = dest_src_dir / "__init__.py"
    init_file.write_text(init_content, encoding='utf-8')
    print("   ✓ Created __init__.py (verifier version)")
    
    # 2. Copy verification key
    print("\n[2/5] Copy verification key...")
    vk_source = project_root / "circuits" / "compiled" / "build" / "verification_key.json"
    vk_dest_dir = output_path / "circuits" / "compiled" / "build"
    vk_dest_dir.mkdir(parents=True, exist_ok=True)
    
    if vk_source.exists():
        shutil.copy2(vk_source, vk_dest_dir / "verification_key.json")
        print(f"   ✓ Copied verification_key.json")
    else:
        # Thử file khác
        alt_vk = project_root / "circuits" / "compiled" / "build" / "chaos_zk_stego_verification_key.json"
        if alt_vk.exists():
            shutil.copy2(alt_vk, vk_dest_dir / "verification_key.json")
            print(f"   ✓ Copied chaos_zk_stego_verification_key.json as verification_key.json")
        else:
            print(f"   ✗ ERROR: Verification key not found!")
            print(f"      Expected: {vk_source}")
            print(f"      Or: {alt_vk}")
            return False
    
    # 3. Copy verification script
    print("\n[3/5] Copy verification script...")
    verify_script = project_root / "scripts" / "verify.py"
    scripts_dir = output_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    
    if verify_script.exists():
        shutil.copy2(verify_script, scripts_dir / "verify.py")
        print(f"   ✓ Copied verify.py")
    else:
        print(f"   ⚠ Warning: verify.py not found")
    
    # 4. Tạo requirements.txt
    print("\n[4/5] Tạo requirements.txt...")
    requirements = """# Python dependencies cho Verifier
pillow>=9.0.0
numpy>=1.21.0
"""
    (output_path / "requirements.txt").write_text(requirements, encoding='utf-8')
    print("   ✓ Created requirements.txt")
    
    # 5. Tạo README và setup script
    print("\n[5/5] Tạo documentation và setup script...")
    
    # README cho verifier
    readme_content = """# ZK-SNARK Steganography Verifier Package

## Setup

### 1. Cài đặt Node.js và snarkjs

```bash
# Cài đặt Node.js (nếu chưa có)
# Download từ: https://nodejs.org/

# Cài đặt snarkjs
npm install -g snarkjs
```

### 2. Cài đặt Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Kiểm tra setup

```bash
python scripts/verify.py --help
```

## Sử dụng

### Verify ảnh stego

```bash
python scripts/verify.py path/to/stego_image.png
```

### Verify với verbose output

```bash
python scripts/verify.py path/to/stego_image.png -v
```

### Verify và output JSON

```bash
python scripts/verify.py path/to/stego_image.png --json
```

## Cấu trúc Package

```
verifier_package/
├── src/zk_stego/          # Source code để extract/verify
├── circuits/compiled/build/
│   └── verification_key.json  # Public key (không cần bảo mật)
├── scripts/
│   └── verify.py          # Script verify
├── requirements.txt        # Python dependencies
└── README.md              # File này
```

## Lưu ý

- **Verification key** là public key, không cần bảo mật
- **Secret key** KHÔNG cần thiết để verify proof (chỉ cần để extract message)
- Tất cả thông tin cần thiết đã có trong ảnh stego (metadata + proof)
"""
    
    (output_path / "README.md").write_text(readme_content, encoding='utf-8')
    print("   ✓ Created README.md")
    
    # Setup script
    setup_script = """#!/bin/bash
# Setup script cho Verifier

echo "Setting up ZK-SNARK Steganography Verifier..."

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js not found. Please install Node.js first."
    exit 1
fi

# Check npm
if ! command -v npm &> /dev/null; then
    echo "ERROR: npm not found. Please install npm first."
    exit 1
fi

# Install snarkjs
echo "Installing snarkjs..."
npm install -g snarkjs

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3 first."
    exit 1
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

echo ""
echo "✓ Setup completed!"
echo ""
echo "You can now verify stego images with:"
echo "  python3 scripts/verify.py <stego_image.png>"
"""
    
    setup_file = output_path / "setup.sh"
    setup_file.write_text(setup_script, encoding='utf-8')
    try:
        setup_file.chmod(0o755)  # Make executable (Unix only)
    except:
        pass  # Windows doesn't support chmod
    print("   ✓ Created setup.sh")
    
    # Windows setup script
    setup_win = """@echo off
REM Setup script cho Verifier (Windows)

echo Setting up ZK-SNARK Steganography Verifier...

REM Check Node.js
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Node.js not found. Please install Node.js first.
    exit /b 1
)

REM Check npm
where npm >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: npm not found. Please install npm first.
    exit /b 1
)

REM Install snarkjs
echo Installing snarkjs...
call npm install -g snarkjs

REM Check Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found. Please install Python first.
    exit /b 1
)

REM Install Python dependencies
echo Installing Python dependencies...
call pip install -r requirements.txt

echo.
echo Setup completed!
echo.
echo You can now verify stego images with:
echo   python scripts\\verify.py ^<stego_image.png^>
pause
"""
    
    (output_path / "setup.bat").write_text(setup_win, encoding='utf-8')
    print("   ✓ Created setup.bat")
    
    # Tạo file .gitignore
    gitignore = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
"""
    (output_path / ".gitignore").write_text(gitignore, encoding='utf-8')
    
    print("\n" + "=" * 80)
    print("HOÀN THÀNH!")
    print("=" * 80)
    print(f"\nVerifier package đã được tạo tại: {output_path.absolute()}")
    print("\nPackage bao gồm:")
    print("  ✓ Source code (src/zk_stego/)")
    print("  ✓ Verification key (circuits/compiled/build/verification_key.json)")
    print("  ✓ Verification script (scripts/verify.py)")
    print("  ✓ Requirements (requirements.txt)")
    print("  ✓ Setup scripts (setup.sh, setup.bat)")
    print("  ✓ Documentation (README.md)")
    print("\nCách gửi cho verifier:")
    print("  1. Zip folder verifier_package/")
    print("  2. Gửi qua email/USB/cloud")
    print("  3. Verifier giải nén và chạy setup.sh (Linux/Mac) hoặc setup.bat (Windows)")
    print("  4. Sau đó có thể verify ảnh stego ngay!")
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Tạo Verifier Package')
    parser.add_argument('--output', '-o', default='verifier_package',
                       help='Thư mục output (default: verifier_package)')
    
    args = parser.parse_args()
    
    success = create_verifier_package(args.output)
    sys.exit(0 if success else 1)

