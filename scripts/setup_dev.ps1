param(
    [switch]$InstallOnly
)

Write-Host "Setting up pre-commit hooks..."
python -m pip install --upgrade pip
python -m pip install pre-commit
pre-commit install
if (-not $InstallOnly) {
    pre-commit run --all-files
}
Write-Host "Pre-commit hooks ready."
