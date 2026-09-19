# Starts PocketMind from a repository checkout.
# On a prepared drive, use START_POCKETMIND.cmd at the drive root instead.

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host ''
    Write-Host '  PocketMind is not installed yet. Run these three commands first:'
    Write-Host ''
    Write-Host '    python -m venv .venv'
    Write-Host '    .\.venv\Scripts\Activate.ps1'
    Write-Host '    pip install -e .'
    Write-Host ''
    exit 1
}

& $python -m pocketmind
