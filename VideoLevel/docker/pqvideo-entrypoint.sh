#!/usr/bin/env sh
set -eu

case "${1:-test}" in
  test)
    ctest --test-dir native/build --output-on-failure
    python3 src/runtest/test_native_relay_ffmpeg.py
    python3 src/runtest/test_hardening.py
    python3 src/runtest/test_lattice_pq_stack.py
    python3 src/runtest/test_lattice_zkp.py
    python3 src/runtest/test_lazer_backend.py
    python3 src/runtest/test_video_zkp_contract.py
    python3 src/runtest/test_zkp_registry.py
    python3 src/runtest/test_cost_guided_matrix_embedding.py
    python3 src/runtest/test_realtime_transport.py
    python3 src/runtest/test_ffmpeg_fixture.py
    ;;
  preflight)
    exec python3 -c 'import json, platform; from src.lazer_backend import _linux_cpu_flags, assess_lazer_host; result = assess_lazer_host(system_name=platform.system(), machine=platform.machine(), cpu_flags=_linux_cpu_flags(), docker_available=True); print(json.dumps(result.to_dict(), sort_keys=True))'
    ;;
  shell)
    exec /bin/sh
    ;;
  *)
    exec "$@"
    ;;
esac
