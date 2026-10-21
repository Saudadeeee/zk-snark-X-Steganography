# Pauses the v2 re-run when memory commit is critical and resumes it when the
# host has room again. The re-run skips finished cases, so a pause loses only
# the case in progress. Log: tmp/rerun_v2/supervisor.txt. Stop: delete tmp/rerun_v2/supervise.flag
$root = 'D:\Code\SourceCode\Project\zk-snark-X-Steganography\VideoLevel'
$log = Join-Path $root 'tmp\rerun_v2\supervisor.txt'
$flag = Join-Path $root 'tmp\rerun_v2\supervise.flag'
$done = Join-Path $root 'tmp\rerun_v2\progress.txt'
$bash = 'C:\Program Files\Git\bin\bash.exe'
$launcher = '/d/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/scripts/ops/launch_rerun_v2_eval.sh'
$sweepPattern = 'latticezk_q2_sweep|repro.py all|VideoLevel.tmp.q2.|latticezk_q2_cases|launch_rerun|rerun_v2.sh'
New-Item -ItemType File -Force -Path $flag | Out-Null
function Say($text) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $text) }
function Sweep { @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $sweepPattern -and $_.CommandLine -notmatch 'worktrees|sweep_supervisor' }) }
function Memory {
  $c = Get-Counter '\Memory\Available MBytes', '\Memory\% Committed Bytes In Use'
  @([int]$c.CounterSamples[0].CookedValue, [int]$c.CounterSamples[1].CookedValue)
}
Say 'supervisor started'
$calm = 0
while (Test-Path $flag) {
  if ((Test-Path $done) -and (Select-String -Path $done -Pattern 'ALL DONE' -Quiet)) { Say 'rerun finished; exiting'; break }
  $available, $commit = Memory
  $running = Sweep
  if ($running.Count -gt 0) {
    $calm = 0
    if ($commit -ge 97) {
      foreach ($p in $running) { & taskkill /F /T /PID $p.ProcessId 2>$null | Out-Null }
      Add-Content -Path $done -Value ("{0} PAUSED by supervisor: commit {1}%" -f (Get-Date -Format 'HH:mm:ss'), $commit)
      Say "paused (commit $commit%, available $available MB)"
    }
  } else {
    if ($available -ge 6000 -and $commit -lt 85) { $calm += 1 } else { $calm = 0 }
    if ($calm -ge 6) {
      Start-Process -FilePath $bash -ArgumentList '-l', $launcher -WindowStyle Hidden | Out-Null
      Say "resumed (commit $commit%, available $available MB)"
      $calm = 0
      Start-Sleep -Seconds 120
    }
  }
  Start-Sleep -Seconds 30
}
Say 'supervisor stopped'
