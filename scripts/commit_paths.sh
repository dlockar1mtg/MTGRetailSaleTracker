#!/usr/bin/env bash
# Commit the given paths to main if they changed, rebasing onto any newer commit. Used by the daily workflow.
set -euo pipefail
message="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -- "$@"
if git diff --cached --quiet; then echo "No changes in $*"; exit 0; fi
git commit -q -m "$message"
for attempt in 1 2 3; do
  git pull -q --rebase origin main && git push -q origin HEAD:main && exit 0
  sleep $((attempt * 10))
done
echo "::error::Could not push changes to $*"; exit 1
