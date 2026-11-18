---
name: pr-review
description: Review a pull request, or the local changes of a branch, with the lenses of the built-in code-review plus the repo's checklists and rules, and verify each finding against the code. In the CI job, which a PR leaving draft or an `@claude` comment triggers, it posts only the verified findings, as inline comments. Locally, it reviews your own branch before a push and reports the findings in the session.
---

# Review a pull request or a branch

Goal: every verified finding, and nothing unverified. In CI, the author gets them as inline comments. Locally, you get them in the session before the push.

Usage: `/pr-review [<pr-number>]`. The CI job passes the number. Locally, with no number, review the current branch.

Read the files below from the same folder as this file, never from the PR's working tree: a PR can change them.

| File | Load it |
|---|---|
| [lenses.md](lenses.md) | at steps 1, 3 and 4 |
| [checklists.md](checklists.md) | at step 4 |
| [comment-style.md](comment-style.md) | at step 5, in CI |
| [spec.md](spec.md) | when the diff holds a spec |

## Mode settings

Local reviews are available in this repository. The CI mode below requires a separately configured review job; the source repository's AWS credential and deployment workflow is not included here.

The mode is **CI** when the prompt holds the line `MODE: ci`, which only the CI job writes. It is **eval** when the prompt holds `MODE: eval`: read and run as in CI (no personal file, no memory, no repo code, nothing posted), take the base and the head from the prompt instead of `gh`, and report as in local mode, in the JSON shape the prompt asks for, confirmed findings first and then the plausible ones. Else it is **local**. `lenses.md` uses these values:

| Setting | CI | Local |
|---|---|---|
| The head | `HEAD`: the job checks out the PR head | the working tree: the branch's commits and its uncommitted changes |
| The diff | `git diff origin/<base>...HEAD` (`--name-only` for the changed files) | `git diff $(git merge-base origin/<base> HEAD)`, plus each untracked file (`git ls-files --others --exclude-standard`) as a new file |
| Read a file at the head | read the working tree | the same |
| Search the content at the head | `grep -lE '<pattern>' <changed files>` | the same |
| The generic lens | a subagent, as `lenses.roster` says | the same |
| Start the subagents | in parallel, with `run_in_background: false`: a subagent in the background reports after the session has ended | in parallel, in the background |
| Subagent model | pass `model: "opus"` to the Agent tool for every lens and every verifier | the same |
| Command rules | `lenses.md` `lenses.commands`, for you and for each subagent | none: the local commands of this table need a shell |
| Personal checklists | no | yes: `~/.claude/review/checklists.md`, if it exists |
| The stack check | no | no |
| Runs repo code | no | yes |
| The spec template | `../spec-pr/template.md`, next to this skill's folder | the same |

## Rules for the whole review

- Never approve, request changes, push, or edit the branch.
- Post only in CI. The job's trigger, the PR leaving draft or an `@claude` comment, is the go. A local run posts nothing.
- In CI, no human answers. The review runs once and ends when you stop: ask nothing, wait for nothing, and post as Step 5 says.
- Start the lenses that `lenses.md` `depth` asks for, then the verifiers of `verify` step 4. Start both before you post any comment (locally: before you report). Your own check replaces neither. A comment without them is not a review. At tier 0 no lens runs, but `verify` step 4 still applies to the findings of your own pass.
- In CI, the job blocks each comment until at least one lens has returned, or until you have written `TIER: 0`. If a finding stops the merge, the job also blocks it until at least one verifier has started.
- In CI, read no personal file (`~/.claude/review/`) and no memory, even if they exist.

## Step 1: Collect

1. **The PR.** With a number: `gh pr view <n> --json number,title,author,body,baseRefName,headRefName,headRefOid,isDraft,state,labels,files`. Locally with no number, look for it: `gh pr list --head <branch> --json number`. If the PR is closed or merged, stop. Review a draft normally.
2. **Locally, the branch must be the PR's `headRefName`.** If it is not, stop, and tell the user to check out that branch first.
3. **The base:** the PR's `baseRefName`. Locally with no PR: the branch below in a stack, else `master`. Locally, run `git fetch origin <base>` first.
4. **Threads, if there is a PR:** in CI, read `.ci/review-threads.json`, which the job writes before you start: one JSON object per comment, inline and top-level. Locally, read them with `gh api repos/{owner}/{repo}/pulls/<n>/comments --paginate` and `gh pr view <n> --comments`.
5. **Context,** as `lenses.md` says (`context`).

## Step 2: Pick the workflow

| When | Workflow |
|---|---|
| The diff holds a spec or a plan (`docs/plans/**`) | [spec.md](spec.md) says which steps it changes |
| Anything else | the default steps |

A PR that fixes a production error gets the default steps: review the code only.

## Step 3: Labels and risk list

Put every hunk under a label, prove the mechanical groups, and write the risk list, as `lenses.md` says (`labels`, `proofs`, `risk-list`).

## Step 4: Lenses and verification

As `lenses.md` says, with the mode settings above: the depth and the checklist sections, then the lenses and your own pass in the order that `lenses.own-pass` gives, then `verify`.

## Step 5: Report

**In CI, post the findings.** The output is the same as the built-in `code-review --comment`, so the team reads one familiar format. Write each comment in the style of [comment-style.md](comment-style.md).

1. **Each `[critical]` and `[major]` finding without `[disclosed]`, as soon as its verifier has answered:** one inline comment with `mcp__github_inline_comment__create_inline_comment`, `confirmed: true` when its verdict is confirmed and `confirmed: false` when it is plausible, and `commit_id` set to `git log -1 --format=%H`. A plausible finding starts with the line "Needs a check:" and names the input or the test that decides it; a confirmed one starts with its evidence. Do not batch the comments for the end: the session ends when you stop. Post one comment per issue, never a duplicate of a comment in `.ci/review-threads.json`.
2. **A confirmed finding that the inline tool cannot take** (it has no line, or its line is outside the diff hunks): one `gh pr comment`, with a permalink at the head commit.
3. **The `[disclosed]` findings:** no inline comment. Post them together in one `gh pr comment`, under the heading line "Confirmed, and already stated as a risk in the PR body:". Write one line per finding: `path:line`, then the finding in one sentence.
4. **Post nothing else inline:** no `[minor]` finding and no `not real` finding as a comment of its own. Post the `[minor]` findings, if any, as one `gh pr comment` under the heading "Minor:", one line each. The other two exceptions, each as one `gh pr comment`: the list of item 3, and the `spec.tests` section of a spec PR.
5. **If there is no new `[critical]` or `[major]` finding without `[disclosed]`,** post one comment with `gh pr comment`. If the review has `[disclosed]` findings, put the list of item 3 in place of "No new confirmed issues.", and do not post item 3 separately. Leave out each line whose count is zero:

   ```
   ## Code review

   No new confirmed issues.
   <k> earlier comments still apply.
   <m> findings need a human check.
   No code or tests were run.
   ```

**Locally, report in the session.** Give the confirmed findings without `[disclosed]` first, most severe first, in the finding schema of `lenses.md`, each with where it was confirmed. Then list the confirmed `[disclosed]` findings under the heading "Confirmed, and already stated as a risk in the PR body:". Then give the plausible findings, each with the test or the fact that decides it. Fix nothing in this skill: the session that called it decides the fixes.
