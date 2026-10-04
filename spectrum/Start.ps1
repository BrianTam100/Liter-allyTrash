$ErrorActionPreference = 'Stop'
$spectrumRoot = $PSScriptRoot
$projectRoot = Split-Path -Parent $spectrumRoot
$logRoot = Join-Path $projectRoot 'BRH_Test/.instance'
$entry = Join-Path $spectrumRoot 'dist/index.js'
$pidFile = Join-Path $logRoot 'spectrum-worker.pid'

if (-not (Test-Path -LiteralPath $entry)) {
    throw 'Build the Spectrum worker first: cd spectrum; npm ci; npm run build'
}
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
if (Test-Path -LiteralPath $pidFile) {
    $workerId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    $worker = Get-CimInstance Win32_Process -Filter "ProcessId = $workerId"
    if ($worker -and $worker.Name -eq 'node.exe' -and $worker.CommandLine.Contains($entry)) {
        Write-Output "Spectrum worker is already running (PID $workerId)."
        exit 0
    }
}
$nodePath = (Get-Command node).Source
$worker = Start-Process -FilePath $nodePath -ArgumentList ('"' + $entry + '"') `
    -WorkingDirectory $spectrumRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logRoot 'spectrum-worker.out.log') `
    -RedirectStandardError (Join-Path $logRoot 'spectrum-worker.err.log') -PassThru
Set-Content -LiteralPath $pidFile -Value $worker.Id
Write-Output "Spectrum worker started (PID $($worker.Id)). Check the dashboard status and BRH_Test/.instance/spectrum-worker.err.log."
