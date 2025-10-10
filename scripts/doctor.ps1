param(
  [switch]$FixCrLf
)

$ErrorActionPreference = 'Stop'

$script:DoctorCheckResults = @()

function Write-Check {
  param(
    [string]$Label,
    [bool]$Condition,
    [string]$Hint = ''
  )
  $result = [pscustomobject]@{
    Label = $Label
    Passed = [bool]$Condition
    Hint = $Hint
  }
  $script:DoctorCheckResults += $result
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
$mainText = [string]::Join("`n", $mainContent)
Write-Check 'S1 marker present' ($mainText -match 'S1: setup_logging done') 'ensure setup marker is logged'
Write-Check 'S2-start marker present' ($mainText -match 'S2-start: init_db') 'log init_db start marker'
Write-Check 'S2-done marker present' ($mainText -match 'S2-done: init_db') 'log init_db completion marker'
Write-Check 'S3 marker present' ($mainText -match 'S3: bot/dispatcher created') 'log dispatcher creation marker'
Write-Check 'audit middleware registration invoked' ($mainText -match '_register_audit_middleware\(dp\)') 'call _register_audit_middleware in main.py'
Write-Check 'S4 marker present' ($mainText -match 'S4: audit middleware registered') 'ensure startup logger prints S4'
Write-Check 'S6 marker present' ($mainText -match 'S6: allowed_updates=') 'pass ALLOWED_UPDATES to start_polling'
Write-Check 'S7 marker present' ($mainText -match 'S7: start_polling enter') 'log polling entry'
Write-Check 'S0 marker present' ($mainText -match 'S0: startup event fired') 'include startup router logging'
Write-Check 'allowed updates constant configured' ($mainText -match 'ALLOWED_UPDATES\s*=\s*\[\s*"message"\s*,\s*"callback_query"\s*\]') 'define ALLOWED_UPDATES for polling'
Write-Check 'audit middleware covers message updates' ($mainText -match 'dp\.message\.middleware\(audit_middleware\)') 'attach audit middleware to message handler'
Write-Check 'audit middleware covers callback updates' ($mainText -match 'dp\.callback_query\.middleware\(audit_middleware\)') 'attach audit middleware to callback handler'
Write-Check 'audit middleware covers raw updates' ($mainText -match 'dp\.update\.outer_middleware\(audit_middleware\)') 'attach audit middleware to dispatcher update handler'

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
  if ($hasLfOnly -and $FixCrLf) {
    try {
      $content = Get-Content $ps.FullName -Raw -Encoding UTF8
      $normalized = $content -replace "`r?`n", "`r`n"
      $encoding = New-Object System.Text.UTF8Encoding($false)
      [IO.File]::WriteAllText($ps.FullName, $normalized, $encoding)
      $hasLfOnly = $false
    } catch {
      Write-Host ("[WARN] failed to rewrite {0}: {1}" -f $ps.Name, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
  $hint = "rewrite the file with CRLF endings"
  if (-not $FixCrLf) {
    $hint += " (run: pwsh -File scripts/doctor.ps1 -FixCrLf)"
  }
  Write-Check ("CRLF check: {0}" -f $ps.Name) (-not $hasLfOnly) $hint
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

$catalogLinkLog = Join-Path $logDir 'catalog_linkcheck.log'
if (Test-Path $catalogLinkLog) {
  $summaries = @()
  foreach ($line in Get-Content $catalogLinkLog -Encoding UTF8 -ErrorAction SilentlyContinue) {
    if (-not $line) { continue }
    try {
      $entry = $line | ConvertFrom-Json -ErrorAction Stop
    } catch {
      continue
    }
    if ($entry.kind -eq 'summary') {
      $summaries += $entry
    }
  }
  if ($summaries.Count -gt 0) {
    $latest = $summaries[-1]
    $status = ($latest.status | Out-String).Trim()
    $broken = 0
    $total = 0
    if ($latest.PSObject.Properties.Name -contains 'broken') {
      [void][int]::TryParse(($latest.broken | Out-String).Trim(), [ref]$broken)
    }
    if ($latest.PSObject.Properties.Name -contains 'total') {
      [void][int]::TryParse(($latest.total | Out-String).Trim(), [ref]$total)
    }
    $hint = "status={0} broken={1} total={2}" -f $status, $broken, $total
    $passed = ($status -eq 'ok' -and $broken -eq 0)
    Write-Check 'catalog linkcheck recent run' $passed $hint
  } else {
    Write-Check 'catalog linkcheck recent run' $false 'logs/catalog_linkcheck.log has no summary entries'
  }
} else {
  Write-Check 'catalog linkcheck recent run' $false 'run python tools/catalog_linkcheck.py'
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

$failedChecks = $script:DoctorCheckResults | Where-Object { -not $_.Passed }
if (-not $failedChecks -or $failedChecks.Count -eq 0) {
  Write-Host "VERDICT: OK" -ForegroundColor Green
} else {
  Write-Host ("VERDICT: FAIL ({0} issues)" -f $failedChecks.Count) -ForegroundColor Red
  $fixes = $failedChecks | Where-Object { $_.Hint }
  if ($fixes.Count -gt 0) {
    Write-Host "Fix suggestions:" -ForegroundColor Yellow
    foreach ($fix in $fixes) {
      Write-Host (" - {0}: {1}" -f $fix.Label, $fix.Hint)
    }
  }
}
