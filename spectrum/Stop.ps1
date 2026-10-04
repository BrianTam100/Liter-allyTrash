$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'dist/index.js'
$pidFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'BRH_Test/.instance/spectrum-worker.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'No background Spectrum worker recorded.'; exit 0 }
$workerId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
$worker = Get-CimInstance Win32_Process -Filter "ProcessId = $workerId"
if ($worker -and $worker.Name -eq 'node.exe' -and $worker.CommandLine.Contains($entry)) {
    Stop-Process -Id $workerId
    Write-Output 'Spectrum worker stopped. The dashboard status expires within 45 seconds.'
} elseif ($worker) { throw 'PID belongs to a different process; refusing to stop it.' }
Remove-Item -LiteralPath $pidFile
