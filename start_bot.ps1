param([switch]$NoVenv)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not $NoVenv -and (Test-Path $venvPy)) {
    & $venvPy .\run.py
} else {
    Write-Warning " venv не найден или отключён флагом -NoVenv  запускаю глобальный Python."
    python .\run.py
}
