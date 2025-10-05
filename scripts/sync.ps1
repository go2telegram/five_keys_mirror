#!/usr/bin/env pwsh

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir '..')
Set-Location $repoRoot

$allowStash = $env:ALLOW_STASH -eq '1'
$stashCreated = $false
$exitCode = 0

function Has-Changes {
    $status = git status --porcelain
    return -not [string]::IsNullOrWhiteSpace($status)
}

function Restore-Stash {
    param([bool]$ShouldRestore)

    if ($ShouldRestore) {
        git stash pop --quiet | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'Restored local changes from stash.'
        }
        else {
            Write-Warning 'Failed to automatically pop stash. The stash entry has been kept.'
        }
    }
}

if ($allowStash -and (Has-Changes)) {
    git stash push --include-untracked --quiet -m 'sync.ps1 autostash' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'Unable to stash local changes.'
        exit 1
    }

    $stashCreated = $true
    Write-Host 'Saved local changes to stash.'
}

git fetch --prune | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error 'git fetch failed.'
    $exitCode = 1
}

if ($exitCode -eq 0) {
    git rev-parse --abbrev-ref --symbolic-full-name @{u} *> $null
    if ($LASTEXITCODE -eq 0) {
        git pull --ff-only | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'git pull failed.'
            $exitCode = 1
        }
    }
    else {
        Write-Host 'No upstream tracking branch configured; skipped pull.'
    }
}

if ($exitCode -eq 0) {
    Restore-Stash -ShouldRestore ($allowStash -and $stashCreated)
}
else {
    Write-Error 'Sync did not complete successfully.'
}

exit $exitCode
