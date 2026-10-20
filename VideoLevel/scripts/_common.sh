# Sourced by the POSIX wrappers: cd to VideoLevel/ and pick an interpreter.
# Override the interpreter with PYTHON=/path/to/python.
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
VIDEOLEVEL=$(dirname -- "$SCRIPT_DIR")
cd -- "$VIDEOLEVEL" || exit 1
if [ -z "${PYTHON:-}" ]; then
    for candidate in .venv312/bin/python .venv312/Scripts/python.exe .venv/bin/python python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON=$candidate
            break
        fi
    done
fi
if [ -z "${PYTHON:-}" ]; then
    echo "error: no Python interpreter found; set PYTHON=/path/to/python" >&2
    exit 1
fi
PYTHONUTF8=1
export PYTHONUTF8
