#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "git_clean: not inside a git repository" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git_clean: git command is not available" >&2
  exit 1
fi

current_branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$current_branch" == "HEAD" ]]; then
  echo "git_clean: detached HEAD detected; aborting" >&2
  exit 1
fi

stash_created=0
if [[ -n "$(git status --porcelain)" ]]; then
  timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo "Stashing local changes ($timestamp)..."
  git stash push -u -m "git_clean auto-stash $timestamp" >/dev/null
  stash_created=1
fi

echo "Fetching remote..."
git fetch --all --prune

echo "Pulling latest changes for $current_branch..."
git pull --rebase --autostash || {
  echo "git pull failed; attempting to abort rebase" >&2
  git rebase --abort >/dev/null 2>&1 || true
  if [[ $stash_created -eq 1 ]]; then
    echo "Restoring stashed changes after pull failure..."
    git stash pop >/dev/null 2>&1 || true
  fi
  exit 1
}

if [[ $stash_created -eq 1 ]]; then
  echo "Restoring stashed changes..."
  if ! git stash pop >/dev/null; then
    echo "git_clean: automatic stash pop failed. Resolve conflicts manually." >&2
    exit 1
  fi
fi

echo "Repository is up to date on $current_branch."
