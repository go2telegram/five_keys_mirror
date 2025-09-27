param(
  [string[]]$Paths = @(".")
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null
$utf8 = New-Object System.Text.UTF8Encoding($true)
$cp1251 = [System.Text.Encoding]::GetEncoding(1251)

# файлы, которые считаем текстовыми
$ext = @(".py",".txt",".md",".yml",".yaml",".json",".ini",".cfg",".toml",".sh",".ps1",".bat")

# словарь точечных замен (дополняем при необходимости)
$map = @{
  "ривет" = "ривет"
  "рофиль" = "рофиль"
  "оступ" = "оступ"
  "ефералы" = "ефералы"
  "риглашено" = "риглашено"
  "никальных переходов" = "никальных переходов"
  "плат" = "плат"
  "акоплено бонусных дней" = "акоплено бонусных дней"

  "ромокоды временно не активны" = "ромокоды временно не активны"
  "ведите промокод" = "ведите промокод"
  "еверный или неактивный промокод" = "еверный или неактивный промокод"
  "тот промокод уже использован" = "тот промокод уже использован"
  "ромокод применён" = "ромокод применён"
  "ромокод активирован" = "ромокод активирован"
  "аш материал" = "аш материал"

  "однимаем APScheduler" = "однимаем APScheduler"
}

function Convert-Fix([string]$text) {
  $fixed = $text
  # если видим признаки кракозябр
  if ($text -match 'Ð|Ñ|Ѓ|Ђ|Љ|Њ|Ћ|Ќ|Â|â') {
    try {
      # восстановление: трактуем текущие юникод-символы как cp1251-байты и повторно декодируем как UTF-8
      $bytes = $cp1251.GetBytes($text)
      $candidate = $utf8.GetString($bytes)
      # если в кандидатe больше кириллицы  принимаем
      $cyr1 = ([regex]::Matches($candidate, '[-Яа-яё]')).Count
      $cyr0 = ([regex]::Matches($text,      '[-Яа-яё]')).Count
      if ($cyr1 -gt $cyr0) { $fixed = $candidate }
    } catch { }
  }
  # точечные замены
  foreach ($kv in $map.GetEnumerator()) {
    $fixed = $fixed -replace [regex]::Escape($kv.Key), $kv.Value
  }
  return $fixed
}

function Process-File($path) {
  try {
    $extname = [IO.Path]::GetExtension($path).ToLower()
    if ($ext -notcontains $extname) { return }
    # читаем как текст; сохраняем обратно как UTF-8 (без BOM)
    $raw = Get-Content $path -Raw
    $new = Convert-Fix $raw
    if ($new -ne $raw) {
      Set-Content -Encoding UTF8 $path $new
      Write-Host "Fixed UTF-8: $path"
    }
  } catch {
    Write-Warning "Skip $path -> $($_.Exception.Message)"
  }
}

$files = foreach ($p in $Paths) { Get-ChildItem $p -Recurse -File | % FullName }
foreach ($f in $files) { Process-File $f }

