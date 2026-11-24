# One-time developer setup on Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[audio,vosk,windows,calendar,dev]"

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

& .\.venv\Scripts\python.exe scripts\download_models.py vosk en
& .\.venv\Scripts\python.exe -m meeting_notes doctor
Write-Host "`nSetup done. Start the app with:  .\.venv\Scripts\meeting-notes"
