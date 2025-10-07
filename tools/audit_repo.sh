#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

status=0

declare -a required_files=(
  ".github/workflows/ci.yml"
  "tools/build_products.py"
  "tools/audit_repo.sh"
  "app/data/products.schema.json"
  "app/catalog/handlers.py"
)

for path in "${required_files[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "MISS $path"
    status=1
  fi
done

python tools/build_products.py validate || status=1

python <<'PY' || status=1
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"https?://[^\s\"']*vilavi\.com[^\s\"']*", re.IGNORECASE)
REQUIRED = {"utm_source", "utm_medium", "utm_campaign"}
ALLOWED_EXT = {".py", ".json", ".md", ".txt", ".yml", ".yaml"}

failures: list[str] = []
for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    if path.suffix not in ALLOWED_EXT:
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for match in PATTERN.findall(text):
        url = match.rstrip(').,')
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if not REQUIRED.issubset({key for key, values in query.items() if values and values[0]}):
            failures.append(f"no_utm {path} {url}")

if failures:
    for line in failures:
        print(line)
    sys.exit(1)
print("UTM checks OK")
PY

[[ $status -eq 0 ]] && echo "All checks passed"
exit $status
