param()

$ErrorActionPreference = 'Stop'

function Write-Check {
  param(
    [string]$Label,
    [bool]$Condition,
    [string]$Hint = ''
  )
  if ($Condition) {
    Write-Host ("[OK] {0}" -f $Label) -ForegroundColor Green
  } else {
    if ($Hint) {
      Write-Host ("[FAIL] {0} :: {1}" -f $Label, $Hint) -ForegroundColor Red
    } else {
      Write-Host ("[FAIL] {0}" -f $Label) -ForegroundColor Red
    }
  }
}

Write-Host "=== five_keys_bot doctor ==="
$cwd = Get-Location
Write-Host ("cwd: {0}" -f $cwd)

try {
  $pyVersion = &(python --version)
  Write-Host ("python: {0}" -f $pyVersion.Trim())
  $pyCommand = Get-Command python -ErrorAction Stop
  Write-Host ("python path: {0}" -f $pyCommand.Path)
} catch {
  Write-Host "python: not available" -ForegroundColor Yellow
}

$venv = $env:VIRTUAL_ENV
if ($venv) {
  Write-Host ("VIRTUAL_ENV: {0}" -f $venv)
} elseif (Test-Path '.\.venv') {
  Write-Host "VIRTUAL_ENV: .\.venv (not activated)" -ForegroundColor Yellow
} else {
  Write-Host "VIRTUAL_ENV: not detected" -ForegroundColor Yellow
}

$branch = (git rev-parse --abbrev-ref HEAD 2>$null)
$branch = if ($branch) { $branch.Trim() } else { 'unknown' }
$localHead = (git rev-parse HEAD 2>$null)
$originHead = (git rev-parse ("origin/" + $branch) 2>$null)
Write-Host ("git branch: {0}" -f $branch)
Write-Host ("git status: {0}" -f (git status -sb))
if ($localHead -and $originHead) {
  Write-Check "HEAD matches origin/$branch" ($localHead.Trim() -eq $originHead.Trim()) "run git fetch && git reset --hard origin/$branch"
} else {
  Write-Host "[WARN] unable to compare local and origin commits" -ForegroundColor Yellow
}

$requiredFiles = @(
  'app/middlewares/audit.py',
  'app/logging_config.py',
  'app/build_info.py'
)
foreach ($file in $requiredFiles) {
  Write-Check "$file exists" (Test-Path $file) "restore the file from git"
}

$mainContent = Get-Content 'app/main.py' -Encoding UTF8 -ErrorAction SilentlyContinue
$mainText = $mainContent -join "`n"
Write-Check 'outer middleware registered' ($mainText -match 'outer_middleware\(AuditMiddleware\(\)\)') 'call _register_audit_middleware in main.py'
Write-Check 'audit marker logged' ($mainText -match 'Audit middleware registered') 'ensure startup logger prints the marker'
Write-Check 'allowed updates fixed list' ($mainText -match "allowed_updates=\['message', 'callback_query'\]") 'pass ALLOWED_UPDATES to start_polling'
Write-Check 'startup marker present' ($mainText -match 'startup event fired') 'include startup router logging'

$psFiles = Get-ChildItem 'scripts' -Filter '*.ps1' -File -Recurse -ErrorAction SilentlyContinue
foreach ($ps in $psFiles) {
  $bytes = [IO.File]::ReadAllBytes($ps.FullName)
  $hasLfOnly = $false
  for ($i = 0; $i -lt $bytes.Length; $i++) {
    if ($bytes[$i] -eq 10) {
      if ($i -eq 0 -or $bytes[$i-1] -ne 13) {
        $hasLfOnly = $true
        break
      }
    }
  }
  Write-Check ("CRLF check: {0}" -f $ps.Name) (-not $hasLfOnly) "rewrite the file with CRLF endings"
}

$logDir = 'logs'
$botLog = Join-Path $logDir 'bot.log'
$errLog = Join-Path $logDir 'errors.log'
Write-Check 'logs directory exists' (Test-Path $logDir) 'create the directory or run the bot once'
Write-Check 'bot.log present' (Test-Path $botLog) 'run the bot to generate logs'
Write-Check 'errors.log present' (Test-Path $errLog) 'run the bot to generate logs'
if (Test-Path $botLog) {
  $size = (Get-Item $botLog).Length
  Write-Host ("bot.log size: {0} bytes" -f $size)
}
if (Test-Path $errLog) {
  $size = (Get-Item $errLog).Length
  Write-Host ("errors.log size: {0} bytes" -f $size)
}

if ($env:BOT_TOKEN) {
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri ("https://api.telegram.org/bot{0}/getWebhookInfo" -f $env:BOT_TOKEN)
    Write-Host "getWebhookInfo:"
    Write-Host $resp.Content
  } catch {
    Write-Host ("[WARN] webhook check failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
  }
} else {
  Write-Host "BOT_TOKEN not set; skipping webhook check" -ForegroundColor Yellow
}

Write-Host "=== doctor finished ==="
