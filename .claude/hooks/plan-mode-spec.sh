#!/usr/bin/env bash
# UserPromptSubmit hook: remind Claude to follow the spec-pr skill when the session
# enters plan mode. Fires once per entry into plan mode, not on every prompt: the last
# seen mode is kept per session, and the reminder is only printed on the transition.
# On UserPromptSubmit, stdout is added to Claude's context.
input="$(cat)"
mode="$(jq -r '.permission_mode // empty' <<<"$input")"
session="$(jq -r '.session_id // empty' <<<"$input")"

state_dir="${TMPDIR:-/tmp}/claude-spec-pr"
mkdir -p "$state_dir"
state_file="$state_dir/${session:-unknown}"

previous="$(cat "$state_file" 2>/dev/null)"
echo "$mode" >"$state_file"

if [[ "$mode" == "plan" && "$previous" != "plan" ]]; then
  echo "Plan mode is active: invoke the spec-pr skill and write the plan as a spec with its required sections."
fi
exit 0
