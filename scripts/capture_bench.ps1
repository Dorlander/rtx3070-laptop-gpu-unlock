# capture_bench.ps1 - pinned-clock FP16 tensor A/B capture for the RTX 3070 Laptop unlock.
#
# Pins the SM clock to 1500 MHz, runs the raw-PTX microbench (tensor_bench.py, any
# Python) and the cuBLAS GEMM (torch_gemm.py, a PyTorch-capable Python it auto-finds),
# records the clock readback that proves the pin held, then restores the clock -
# logging everything to a timestamped file next to this script.
#
# Run it ONCE in each state and send both files:
#   LOCKED    = a normal Windows boot with NO USB unlock this power-cycle.
#   UNLOCKED  = after booting the USB unlock (press U) with the keep-alive holding.
# The printed VERDICT / TFLOPS tells you which state you captured (locked ~28-29,
# unlocked ~57 at the pinned 1500 MHz).
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File "<path>\capture_bench.ps1"
#   ...optionally  -ClockMHz 1500  -TorchPython "C:\path\to\python.exe"
param(
  [int]$ClockMHz = 1500,
  [string]$TorchPython = ''
)
$ErrorActionPreference = 'Continue'
$dir   = $PSScriptRoot
$bench = Join-Path $dir 'tensor_bench.py'
$gemm  = Join-Path $dir 'torch_gemm.py'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log   = Join-Path $dir "bench-capture-$stamp.txt"

function Log { param([string]$m) Write-Host $m; Add-Content -LiteralPath $log -Value $m -Encoding utf8 }

# Returns a Python invocation string that can import torch, or $null.
# 'py -3' is special-cased; everything else is an executable path.
function Find-TorchPython {
  param([string]$explicit)
  $cands = @()
  if ($explicit) { $cands += $explicit }
  $cands += 'py -3'
  $cands += 'python'
  $local = Join-Path $dir '..\..\py313\python\python.exe'   # author's local standalone, if present
  if (Test-Path $local) { $cands += $local }
  foreach ($c in $cands) {
    if ($c -eq 'py -3') { & py -3 -c "import torch" 2>$null }
    elseif ((Test-Path $c) -or ($c -eq 'python')) { & $c -c "import torch" 2>$null }
    else { continue }
    if ($LASTEXITCODE -eq 0) { return $c }
  }
  return $null
}

"=== RTX 3070 Laptop (10de:249d) tensor A/B capture  $stamp ===" | Set-Content -LiteralPath $log -Encoding utf8
Log "host=$env:COMPUTERNAME  scripts=$dir"
Log ""
Log ">>> pin SM clock to $ClockMHz MHz"
Log (nvidia-smi -lgc "$ClockMHz,$ClockMHz" 2>&1 | Out-String)
Log ">>> clock/power readback (pinned):"
Log (nvidia-smi --query-gpu=clocks.sm,clocks.gr,power.draw,temperature.gpu --format=csv 2>&1 | Out-String)
try {
  Log ">>> tensor_bench.py  (raw mma.sync microbench, py -3)"
  Log (& py -3 -P $bench 2>&1 | Out-String)

  $tp = Find-TorchPython $TorchPython
  if ($tp) {
    Log ">>> torch_gemm.py  (PyTorch cuBLAS GEMM, via: $tp)"
    if ($tp -eq 'py -3') { Log (& py -3 -P $gemm 2>&1 | Out-String) }
    else { Log (& $tp -P $gemm 2>&1 | Out-String) }
  } else {
    Log ">>> torch_gemm.py SKIPPED: no PyTorch-capable Python found."
    Log "    Re-run with:  -TorchPython `"C:\full\path\to\python.exe`"  (one that has torch)."
  }

  Log ">>> clock readback (still pinned, after the benches):"
  Log (nvidia-smi --query-gpu=clocks.sm --format=csv 2>&1 | Out-String)
}
finally {
  Log ">>> restore clocks"
  Log (nvidia-smi -rgc 2>&1 | Out-String)
}
Log ""
Log "Saved to: $log"
Write-Host ""
Write-Host "DONE. Send this file to Claude:  $log" -ForegroundColor Green
