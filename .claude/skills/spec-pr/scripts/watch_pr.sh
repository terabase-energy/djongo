#!/usr/bin/env bash
# Block until a spec PR needs the agent's attention, then print why and exit.
#
# Usage: watch_pr.sh [--include-author] [--no-approval] <pr-number> <since-iso8601> [interval-seconds]
#
#   --include-author  also wake on comments and reviews from the PR author (used once the
#                     code is pushed, so the author can give feedback on it)
#   --no-approval     don't check for the plan-approved label (it is already there once the
#                     code is pushed, and would end the watch at once)
#
# Exits 0 printing one of:
#   APPROVED <login>   someone other than the PR author added the plan-approved label
#   ACTIVITY           new comments or reviews since <since>, followed by their URLs
#   CLOSED <state>     the PR was merged or closed
#
# The agent posts through the author's gh credentials, so its own comments would wake it
# up. It tags every comment it posts with AGENT_MARKER, and those are always ignored. By
# default all author activity is ignored as well.
set -uo pipefail

INCLUDE_AUTHOR=0
CHECK_APPROVAL=1
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --include-author) INCLUDE_AUTHOR=1 ;;
    --no-approval) CHECK_APPROVAL=0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

PR="${1:?pr number required}"
SINCE="${2:?since timestamp required (e.g. 2026-10-30T12:00:00Z)}"
INTERVAL="${3:-60}"
LABEL="plan-approved"
AGENT_MARKER="<!-- spec-pr-agent -->"

AUTHOR="$(gh pr view "$PR" --json author --jq .author.login)" || exit 1

# jq filter keeping only the comments and reviews that should wake the agent.
keep="select((.body // \"\") | contains(\"$AGENT_MARKER\") | not)"
if [[ "$INCLUDE_AUTHOR" == 0 ]]; then
  keep="$keep | select(.user.login != \"$AUTHOR\")"
fi

while true; do
  # Transient gh/network failures fall through to the next tick rather than ending the watch.
  state="$(gh pr view "$PR" --json state,labels 2>/dev/null)" || { sleep "$INTERVAL"; continue; }

  pr_state="$(jq -r .state <<<"$state")"
  if [[ "$pr_state" != "OPEN" ]]; then
    echo "CLOSED $pr_state"
    exit 0
  fi

  if [[ "$CHECK_APPROVAL" == 1 ]] && jq -e --arg l "$LABEL" '.labels | map(.name) | index($l)' <<<"$state" >/dev/null; then
    # The label is present: check who applied it most recently.
    approver="$(gh api --paginate "repos/{owner}/{repo}/issues/$PR/events" \
      --jq ".[] | select(.event == \"labeled\" and .label.name == \"$LABEL\") | .actor.login" 2>/dev/null | tail -n 1)"
    if [[ -n "$approver" && "$approver" != "$AUTHOR" ]]; then
      echo "APPROVED $approver"
      exit 0
    fi
  fi

  activity="$(
    {
      gh api --paginate "repos/{owner}/{repo}/issues/$PR/comments?since=$SINCE" \
        --jq ".[] | $keep | select(.created_at > \"$SINCE\") | .html_url"
      gh api --paginate "repos/{owner}/{repo}/pulls/$PR/comments?since=$SINCE" \
        --jq ".[] | $keep | select(.created_at > \"$SINCE\") | .html_url"
      # A review with an empty body is only the container of inline comments, which the
      # call above already reports (replying to an inline comment creates one, too).
      gh api --paginate "repos/{owner}/{repo}/pulls/$PR/reviews" \
        --jq ".[] | $keep | select(.body != \"\" and .submitted_at > \"$SINCE\") | .html_url"
    } 2>/dev/null
  )"
  if [[ -n "$activity" ]]; then
    echo "ACTIVITY"
    echo "$activity"
    exit 0
  fi

  sleep "$INTERVAL"
done
