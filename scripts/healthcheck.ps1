param(
  [switch]$VerboseOut
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function W([string]$msg,[string]$color='Gray'){ Write-Host $msg -ForegroundColor $color }

W "`n================ HEALTHCHECK ================" Cyan

# 1) venv / python
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  W " е найден venv: .venv\Scripts\python.exe" Red
  W "   Создай: py -3.11 -m venv .venv и поставь зависимости в venv." Yellow
  exit 1
}
$pyPath = & $venvPy -c "import sys; print(sys.executable)"
$pyVer  = & $venvPy -c "import platform; print(platform.python_version())"
W (" python: " + $pyPath.Trim())
W (" version: " + $pyVer.Trim())

# 2) pip proxy / pip configs
$cfg = & $venvPy -m pip config debug 2>$null
$envProxy = (Get-ChildItem env: | Where-Object { $_.Name -match 'PROXY' })
if ($envProxy -or ($cfg -match 'proxy')) {
  W "  бнаружены прокси-переменные/настройки pip. то может ломать установку пакетов." Yellow
  if ($VerboseOut) {
    W "`n-- env PROXY --" DarkGray
    $envProxy | ForEach-Object { W ("  "+$_.Name+"="+$_.Value) DarkGray }
    W "`n-- pip config debug --" DarkGray
    W ($cfg) DarkGray
  }
} else {
  W " pip: прокси не найдены"
}

# helper: пробуем импорт модуля и печатаем версию
function TryImport([string]$module) {
  $code = "import importlib; m=importlib.util.find_spec('$module');print('FOUND' if m else 'MISS');" +
          "import importlib as _il; " +
          "print(getattr(_il.import_module('$module'),'Version',getattr(_il.import_module('$module'),'__version__','')) if m else '')"
  $out = & $venvPy -c $code 2>$null
  return $out -split "`n"
}

# 3) пакеты
$ai = TryImport "aiogram"
if ($ai[0].Trim() -eq "FOUND") { W (" aiogram: " + $ai[1].Trim()) } else { W " aiogram не установлен в venv" Red }

$rl = TryImport "reportlab"
if ($rl[0].Trim() -eq "FOUND") { W (" reportlab: " + $rl[1].Trim()) } else { W " reportlab не установлен в venv" Red }

# 4) .env / ключи
$envPath = Join-Path $root ".env"
$keysNeed = "BOT_TOKEN","ADMIN_ID","TRIBUTE_LINK_BASIC","TRIBUTE_LINK_PRO","DATABASE_URL"
$envText = (Get-Content $envPath -Raw -ErrorAction SilentlyContinue)
if ($null -eq $envText) {
  W " .env не найден" Red
} else {
  $kv = @{}
  foreach($line in ($envText -split "`n")){
    if($line -match '^\s*#' -or -not $line.Contains('=')) { continue }
    $k,$v = $line.Split('=',2); $kv[$k.Trim()] = $v.Trim()
  }
  $miss = @()
  foreach($k in $keysNeed){ if(-not $kv.ContainsKey($k) -or -not $kv[$k]){ $miss += $k } }
  if($miss.Count){ W ("   .env отсутствуют: " + ($miss -join ", ")) Yellow } else { W " .env: ключи найдены" }
  if($kv["DATABASE_URL"] -like "sqlite*"){
    $db = Join-Path $root "five_keys.sqlite3"
    if (Test-Path $db) { W " SQLite: five_keys.sqlite3 существует" } else { W "  SQLite файл не найден: five_keys.sqlite3" Yellow }
  }
}

# 5) импорт app.main
try {
  $r = & $venvPy -c "import importlib; importlib.import_module('app.main'); print('OK_MAIN')" 2>$null
  if (($r -split "`n") -contains "OK_MAIN") { W " мпорт app.main прошёл" } else { W "  мпорт app.main не подтвердился" Yellow }
} catch {
  W " мпорт app.main упал:" Red
  W ($_.Exception.Message) DarkGray
}

W "================ END HEALTHCHECK ===============" Cyan

