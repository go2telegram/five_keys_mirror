param([string]$WheelsDir=".\wheels")
$ErrorActionPreference = 'Stop'
function Fail([string]$m){ Write-Host ("ERROR: {0}" -f $m); exit 1 }
Write-Host ("Offline install from: {0}" -f $WheelsDir)

if (-not (Test-Path $WheelsDir)) { Fail ("No wheels dir: " + $WheelsDir) }
$whl = Get-ChildItem $WheelsDir -Filter *.whl -ErrorAction SilentlyContinue
if (-not $whl -or $whl.Count -lt 1) { Fail ("No .whl files in " + $WheelsDir) }

if (Test-Path ".\wheels-packages.txt") {
  pip install --isolated --no-index --find-links "$WheelsDir" -r .\wheels-packages.txt
}
if (Test-Path ".\requirements.txt") {
  pip install --isolated --no-index --find-links "$WheelsDir" -r .\requirements.txt
}

$need = @('SQLAlchemy','alembic','aiosqlite','aiogram','python-dotenv')
foreach ($p in $need) {
  if (-not (pip show $p 2>$null)) { pip install --isolated --no-index --find-links "$WheelsDir" $p }
}
foreach ($p in $need) {
  if (-not (pip show $p 2>$null)) { Fail ("Missing package: " + $p) }
}
Write-Host "Offline install: done."
