# становить все процессы python, исполняющие run.py из этого корня
$root = (Resolve-Path .).Path
$procs = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    try {
      $_.Path -and (Get-Content -Path $_.Path -ErrorAction SilentlyContinue | Out-Null; $true)
    } catch { $true }
}
if ($procs) {
  Write-Host " станавливаю процессы python (если бот запущен)..." -ForegroundColor Yellow
  $procs | Stop-Process -Force -ErrorAction SilentlyContinue
  Write-Host " становлено."
} else {
  Write-Host "ℹ  роцессов python не найдено."
}
