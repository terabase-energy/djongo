---
name: spec-pr
description: Write an implementation spec, publish it as the first commit of a draft PR, wait for the plan-approved label, then implement it on the same branch, so the spec merges with its code. Use whenever planning or designing a non-trivial change (plan mode, or a planning step in auto mode), or when the user asks for a spec or a plan.
---

# Spec → PR → approval → implementation

A plan in this repo is called a **spec**: it specifies how a feature will be implemented. It is the first commit of the PR that implements it, so there is no separate spec PR. That PR is reviewed in two phases: first the spec alone, then, after approval, the code. Implementation starts only once the spec is approved, and the spec merges with its code, in one squash commit. A spec never reaches `master` alone, so the spec and its implementation are reviewed and merged together.

Use `gh` for all GitHub operations.

## 1. Write the spec

Every spec is tied to a Linear issue (`ISSUE-xxxx`). If you don't know the issue number, ask the user for it, or offer the `linear-issue` skill to create one.

Investigate the code first, then write the spec using exactly the sections in [template.md](template.md), in that order. Rules for some sections:

- **Open questions**: anything unresolved. If one blocks the design, ask the user before publishing instead of guessing.
- **Acceptance criteria → tests**: one row per criterion, and the test level for each (unit / integration / acceptance), following the Testing Strategy in AGENTS.md.
- **Review Tier**: pick 0, 1 or 2 using the definitions in the template, and justify it in one line. When unsure, pick the higher tier.
- Do **not** add an `## Implementation` section yet. It only exists once the implementation departs from the spec (step 5).

**In plan mode**, the plan you present with `ExitPlanMode` is the spec itself, with these sections. Nothing can be written to the repo until the user accepts it.
**In auto mode**, write the spec straight to its file. Still have the user approve the plan before publishing.

## 2. Offer a review of the spec

Once the spec is written, and before you present it (in plan mode, before `ExitPlanMode`), ask the user with `AskUserQuestion` whether to run `/pr-review` on the spec.

If they say no, go on. If they say yes:

1. Start a subagent (`Agent`, in the foreground) with this brief: load the `pr-review` skill and review the spec at `<path>` with its spec workflow (`spec.md`), in local mode. Review only that file: there is no PR yet, and the rest of the branch is not part of the review. Post nothing, and report the verified findings and the tests to implement. `<path>` is the spec's file, or in plan mode the plan file, since nothing is in the repo yet.
2. Go through the findings and improve the spec:
   - A finding you agree with: change the spec.
   - A decision only the user can make: add it to **Open questions**, or ask the user now if it blocks the design.
   - A finding you disagree with: leave the spec as it is, and keep a one-line reason.
   - The tests to implement: fold them into **Acceptance criteria → tests**.
3. Tell the user what changed, and which findings you rejected and why. Then present the spec as step 1 says.

Run one review round. Run another only if the user asks.

## 3. Open the PR with the spec as its first commit

Once the spec is accepted locally (or right away in auto mode):

1. Branch from an up-to-date `master`: `git switch -c issue-xxxx-<short-slug> origin/master` (after `git fetch origin master`).
2. Write the spec to `docs/plans/ISSUE-xxxx/spec.md`.
3. Commit only that file: `docs: [ISSUE-xxxx] add spec for <feature>`.
4. Push, then open a **draft** PR:
   - Title: `[ISSUE-xxxx] <feature>`
   - Body: a 2–3 line summary, the review tier, a link to the spec file, and this line: *"Phase 1: spec review. Add the `plan-approved` label to approve the spec. The implementation commits then follow on this branch, and the spec merges with them."*
5. Give the user the PR URL.

## 4. Wait for approval

Approval is the `plan-approved` label added by **someone other than the PR author**. If the author adds it, that is not approval.

Start the watcher as a **background** Bash command (`run_in_background: true`, `timeout: 7200000`), with `<since>` set to the current UTC time (`date -u +%Y-%m-%dT%H:%M:%SZ`):

```bash
.claude/skills/spec-pr/scripts/watch_pr.sh <pr-number> <since> 60
```

It exits, and you get re-invoked, when one of these happens:

| Output | What to do |
|---|---|
| `ACTIVITY` + URLs | Read the new comments and reviews (`gh pr view <n> --comments`, `gh api repos/{owner}/{repo}/pulls/<n>/comments`). Update the spec and commit it (`docs: [ISSUE-xxxx] address spec review`), push, reply to each comment with `gh`, then restart the watcher with a fresh `<since>`. |
| `APPROVED <login>` | Read any comments you haven't handled yet. Keep the PR a draft: it holds no code yet. Go to step 5. |
| `CLOSED <state>` | Stop and tell the user. |
| Timed out with no output | Restart the watcher with the same `<since>`. |

Tell the user that the watch stops when this session ends. If the session is closed and later resumed, restart the watcher.

**Every comment or reply you post on a PR must end with the line `<!-- spec-pr-agent -->`.** You post through the author's `gh` login, and the watcher uses this marker to tell your comments apart from the author's. Without it, your own replies would wake you up.

## 5. Implement on the same branch

Push the implementation commits on top of the spec commit, on the same branch, so the PR carries the spec and its code. When the change splits into self-sufficient parts, this PR is the bottom of a `gh stack` and holds the first part; each later PR stacks on it. Each PR depends only on `master` and the PRs below it. Follow AGENTS.md (tests, imports, commit conventions such as `feat: [ISSUE-xxxx] ...`). Each later PR body links the spec.

**Departures from the spec**: when a commit implements something differently from the spec, the **same commit** must update `docs/plans/ISSUE-xxxx/spec.md`. Add an `## Implementation` section at the end if it doesn't exist yet, and for each departure say what was specified, what was done instead, and why. Do not rewrite the original sections; the approved spec stays as it was approved.

## 6. Verify and hand off

Run the checks listed in the spec's **Verification** section and the relevant tests. Report the results faithfully, including failures. When everything passes, mark the PRs ready with `gh pr ready <n>` and give the user a short summary: what was done, any `## Implementation` notes, and the test results. The PR squash-merges as usual, with the spec in the same commit as its code.

## 7. Watch the code review

Once the code is pushed, keep watching the PR (and each later PR of the stack), this time including the author's own comments, and without checking the label, which is already on the spec's PR and would end the watch at once:

```bash
.claude/skills/spec-pr/scripts/watch_pr.sh --include-author --no-approval <pr-number> <since> 60
```

Run one watcher per open PR, the same way as in step 4 (background, fresh `<since>`). On `ACTIVITY`, address the comments: fix the code (with an `## Implementation` note in the same commit if the fix departs from the spec), rerun the relevant tests, push, reply to each comment (with the marker), then restart that PR's watcher. On `CLOSED`, stop watching that PR and tell the user.
