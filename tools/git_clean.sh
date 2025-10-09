#!/usr/bin/env bash
set -euo pipefail

git status
read -r -p "Stash local changes? (y/N) " answer
if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
    git stash push -u -m "WIP: auto"
fi

git pull --ff-only
