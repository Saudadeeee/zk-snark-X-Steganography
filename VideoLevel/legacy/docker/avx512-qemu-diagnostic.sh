#!/bin/sh
# Diagnose whether this pinned QEMU TCG can execute the bundled AVX-512F test.
# This is not an emulator conformance or performance test.
set -eu

if /usr/bin/qemu-x86_64-static -L / /opt/avx512-smoke; then
    echo "QEMU executed this AVX-512F smoke binary. This is still not a LaZer validation."
    exit 0
else
    status=$?
fi

if [ "$status" -eq 132 ]; then
    echo "QEMU TCG cannot emulate the AVX-512F smoke binary (SIGILL, exit 132)."
    echo "Use Intel SDE for functional instruction emulation, or an AVX-512F host for LaZer."
    exit 0
fi

echo "QEMU diagnostic failed unexpectedly with exit $status." >&2
exit "$status"
