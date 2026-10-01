#!/usr/bin/env bash
# Provision the auto-merge.yml GitHub App credentials (APP_ID, APP_PRIVATE_KEY)
# on the repo in the current directory, in both the Actions and Dependabot
# secret scopes. Usage: setup-automerge.sh [owner/repo]
set -euo pipefail

# Resolved from the git remote rather than the directory name so a worktree
# checked out under a different name still targets the right repo.
repo="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"

app_id="$(op read "op://Personal/Github Automerge/app id")"
private_key="$(op read "op://Personal/Github Automerge/jluszcz-automerge.pem")"

for app in actions dependabot; do
  gh secret set APP_ID -r "$repo" --app "$app" -b "$app_id"
  gh secret set APP_PRIVATE_KEY -r "$repo" --app "$app" -b "$private_key"
done
