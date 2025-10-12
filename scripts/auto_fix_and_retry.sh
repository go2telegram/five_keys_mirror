#!/usr/bin/env bash
# soft fixer: не падает, просто нормализует финальные перевод строки
set -euo pipefail
file="${1:-docs/menu_map.mmd}"
[ -f "$file" ] || { echo "no file $file"; exit 0; }
# Удаляем не-UTF символы, нормализуем перевод строки
iconv -f utf-8 -t utf-8 -c "$file" > "$file.tmp" || cp "$file" "$file.tmp"
tr -d '\r' < "$file.tmp" > "$file"
rm -f "$file.tmp"
echo "[auto_fix_and_retry] soft-fix applied to $file"
