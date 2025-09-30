param(
  [string]$WheelsDir = "$(Resolve-Path "$PSScriptRoot\..\wheels")"
)

Write-Host "Using wheels from: $WheelsDir"

if (-not (Get-Command pip -ErrorAction SilentlyContinue)) {
  Write-Error "Activate your venv first (.\\.venv\\Scripts\\Activate.ps1)"
  exit 1
}

pip install --isolated --no-index --find-links "$WheelsDir" `
  -r "$PSScriptRoot\..\requirements.txt" `
  -r "$PSScriptRoot\..\wheels-packages.txt"

Write-Host "Offline install: done"
