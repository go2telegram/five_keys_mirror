param([switch]$VerboseOut)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function W([string]$s,[string]$c='Gray'){ Write-Host $s -ForegroundColor $c }

W "`n================ HEALTHCHECK ================" Cyan

# venv / python
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  W " е найден venv: .venv\Scripts\python.exe" Red
  W "   Создай: py -3.11 -m venv .venv и установи зависимости в venv." Yellow
  exit 1
}
$pyPath = & $venvPy -c "import sys; print(sys.executable)"
$pyVer  = & $venvPy -c "import platform; print(platform.python_version())"
W (" python: " + $pyPath.Trim())
W (" version: " + $pyVer.Trim())

# pip proxy / config
$cfg = & $venvPy -m pip config debug 2>$null
$envProxy = (Get-ChildItem env: | Where-Object { $_.Name -match 'PROXY' -and $_.Name -ne 'PIP_NO_PROXY' })
$hasCfgProxy = ($cfg -match "proxy\s*=") -and ($cfg -match "://") -and ($cfg -notmatch "no-proxy")
if (($envProxy -and $envProxy.Count) -or $hasCfgProxy) {
  W "  бнаружены прокси-настройки pip/ENV. то может ломать pip." Yellow
  if ($VerboseOut) {
    W "`n-- env PROXY --" DarkGray
    $envProxy | % { W ("  " + $_.Name + "=" + $_.Value) DarkGray }
    W "`n-- pip config debug --" DarkGray
    W ($cfg) DarkGray
  }
} else {
  W " pip: прокси не найдены"
}

function TryImport([string]$module){
  $found = & $venvPy -c "import importlib.util as u; print('FOUND' if u.find_spec('$module') else 'MISS')" 2>$null
  if ($found.Trim() -ne 'FOUND'){ return @('MISS','') }
  $ver = & $venvPy -c "import importlib as i; m=i.import_module('$module'); print(getattr(m,'Version',getattr(m,'__version__','')))" 2>$null
  return @('FOUND', ($ver -join ''))
}

$ai = TryImport "aiogram"
if ($ai[0] -eq 'FOUND') { W (" aiogram: " + $ai[1]) } else { W " aiogram не установлен в venv" Red }
$rl = TryImport "reportlab"
if ($rl[0] -eq 'FOUND') { W (" reportlab: " + $rl[1]) } else { W " reportlab не установлен в venv" Red }

# .env
$envPath = Join-Path $root ".env"
$need = "BOT_TOKEN","ADMIN_ID","TRIBUTE_LINK_BASIC","TRIBUTE_LINK_PRO","DATABASE_URL"
$envText = Get-Content $envPath -Raw -ErrorAction SilentlyContinue
if ($null -eq $envText){
  W " .env не найден" Red
}else{
  $kv=@{}; foreach($l in ($envText -split "`n")){ if($l -match '^\s*#' -or -not $l.Contains('=')){continue}; $k,$v=$l.Split('=',2); $kv[$k.Trim()]=$v.Trim() }
  $miss=@(); foreach($k in $need){ if(-not $kv.ContainsKey($k) -or -not $kv[$k]){ $miss+=$k } }
  if($miss.Count){ W ("   .env отсутствуют: " + ($miss -join ', ')) Yellow } else { W " .env: ключи найдены" }
  if($kv["DATABASE_URL"] -like "sqlite*"){
    if (Test-Path (Join-Path $root "five_keys.sqlite3")) { W " SQLite: five_keys.sqlite3 существует" }
    else { W "  SQLite файл не найден: five_keys.sqlite3" Yellow }
  }
}

# импорт app.main
try{
  $r = & $venvPy -c "import importlib; importlib.import_module('app.main'); print('OK_MAIN')" 2>$null
  if (($r -split "`n") -contains "OK_MAIN"){ W " мпорт app.main прошёл" } else { W "  мпорт app.main не подтвердился" Yellow }
}catch{ W " мпорт app.main упал: $($_.Exception.Message)" Red }

W "================ END HEALTHCHECK ===============" Cyan
