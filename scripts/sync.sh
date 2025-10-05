#!/usr/bin/env bash

set -u

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
cd "${REPO_ROOT}"

ALLOW_STASH=${ALLOW_STASH:-0}
STASH_CREATED=0
EXIT_CODE=0

status_has_changes() {
  test -n "$(git status --porcelain)"
}

pop_stash_if_needed() {
  if [ "$ALLOW_STASH" = "1" ] && [ $STASH_CREATED -eq 1 ]; then
    if git stash pop --quiet; then
      echo "Restored local changes from stash."
    else
      echo "Failed to automatically pop stash. The stash entry has been kept." >&2
    fi
  fi
}

if [ "$ALLOW_STASH" = "1" ] && status_has_changes; then
  if git stash push --include-untracked --quiet -m "sync.sh autostash"; then
    STASH_CREATED=1
    echo "Saved local changes to stash."
  else
    echo "Unable to stash local changes." >&2
    exit 1
  fi
fi

if ! git fetch --prune; then
  echo "git fetch failed." >&2
  EXIT_CODE=1
fi

if [ $EXIT_CODE -eq 0 ]; then
  if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    if ! git pull --ff-only; then
      echo "git pull failed." >&2
      EXIT_CODE=1
    fi
  else
    echo "No upstream tracking branch configured; skipped pull."
  fi
fi

if [ $EXIT_CODE -eq 0 ]; then
  pop_stash_if_needed
else
  echo "Sync did not complete successfully." >&2
fi

exit $EXIT_CODE
