#!/usr/bin/env bash
# Provision the auto-merge.yml GitHub App credentials (APP_ID, APP_PRIVATE_KEY)
# on the GitHub repo of the git checkout containing the current directory, in
# both the Actions and Dependabot secret scopes. Usage: setup-automerge.sh [-h]
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") [-h]"
  echo
  echo "Set APP_ID and APP_PRIVATE_KEY (read from 1Password) as Actions and"
  echo "Dependabot secrets on the GitHub repo of the current directory's git checkout."
  echo "Set GH_REPO=owner/repo to target a different repo."
}

if (($# > 1)); then
  usage >&2
  exit 2
fi

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  "") ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != true ]]; then
  echo "$(basename "$0"): must be run from within a git repository" >&2
  exit 1
fi

# Resolved from the git remote rather than the directory name so a worktree
# checked out under a different name still targets the right repo.
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

app_id="$(op read "op://Personal/Github Automerge/app id")"
private_key="$(op read "op://Personal/Github Automerge/jluszcz-automerge.pem")"

# The key is piped on stdin rather than passed with -b so it never appears in
# the process list.
for app in actions dependabot; do
  gh secret set APP_ID -r "$repo" --app "$app" -b "$app_id"
  printf '%s' "$private_key" | gh secret set APP_PRIVATE_KEY -r "$repo" --app "$app"
done
