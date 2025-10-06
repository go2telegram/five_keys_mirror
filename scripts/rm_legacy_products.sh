#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_FILES=(
  "app/data/products.json"
  "app/data/products_old.json"
  "app/data/products.yml"
  "app/data/products.csv"
)

for file in "${LEGACY_FILES[@]}"; do
  target="${ROOT_DIR}/${file}"
  if [[ -e "${target}" ]]; then
    echo "Removing legacy catalog file: ${file}" >&2
    rm -f "${target}"
  else
    echo "Skipping missing file: ${file}" >&2
  fi
done
