#!/usr/bin/env bash
# Wait until the machine has >= MIN_FREE_MB of free RAM for GRACE consecutive
# polls, then run scripts/ops/system_e2e_v3.sh.  Launch detached, e.g.
#   powershell Start-Process bash -ArgumentList '-c "bash scripts/ops/launch_system_e2e_v3_when_free.sh"'
# Progress: tmp/system_e2e_v3/launcher.txt, then tmp/system_e2e_v3/progress.txt.
set -u
cd "$(dirname "$0")/../.." || exit 1
MIN_FREE_MB=${MIN_FREE_MB:-6000}
GRACE=${GRACE:-3}
POLL=${POLL:-60}
mkdir -p tmp/system_e2e_v3
LOG=tmp/system_e2e_v3/launcher.txt
free_mb() { powershell -NoProfile -Command "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"; }
ok=0
while :; do
  f=$(free_mb)
  if [ "${f:-0}" -ge "$MIN_FREE_MB" ]; then ok=$((ok + 1)); else ok=0; fi
  echo "$(date +%H:%M:%S) free=${f} MB ok=$ok/$GRACE" >> "$LOG"
  [ "$ok" -ge "$GRACE" ] && break
  sleep "$POLL"
done
echo "$(date +%H:%M:%S) starting system_e2e_v3.sh" >> "$LOG"
ZKSTEGO_ANALYSIS_WORKERS="${ZKSTEGO_ANALYSIS_WORKERS:-3}" bash scripts/ops/system_e2e_v3.sh >> tmp/system_e2e_v3/run.out 2>&1
echo "$(date +%H:%M:%S) system_e2e_v3.sh finished exit=$?" >> "$LOG"
