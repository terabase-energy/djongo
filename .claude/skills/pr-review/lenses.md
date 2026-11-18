# Labels, depth, lenses and verification

The review core. Two skills follow this file: `pr-review` (in CI and locally) and the personal `self-review`. Where they differ, this file says "as your mode settings say": each `SKILL.md` has a **Mode settings** table that gives the value for its mode.

## <a id="context"></a>Context

Collect the context that the author worked from:
- the spec `docs/plans/ISSUE-xxxx/spec.md`, if there is one: its Review Tier and its `## Implementation` section;
- `AGENTS.md`, and each `CLAUDE.md` in a directory that the diff touches or in its parents. Read them at the base (`git show <base>:AGENTS.md`): the change must meet the rules it started from, and a change to a rule file is a hunk to review;
- the repo runtime facts, for the verifiers: the supported Python and framework versions from `setup.py`, `requirements.txt` and `tox.ini`, and the installed versions when available.

## <a id="labels"></a>Labels

Put every hunk under one label:

| Label | What | Reader's effort |
|---|---|---|
| mechanical | moves, renames, formatting, regenerated files | skip: read the proof line |
| tests / spec | new or changed tests | read: they state what the code must do |
| core logic | behavior, SQL, locks, data writes, migrations | read |
| wiring | imports, settings, docstrings, plumbing | skim |

## <a id="proofs"></a>Proofs

Prove each mechanical group with a tool, in one line:
- a move: `git diff --color=always --color-moved=zebra --color-moved-ws=allow-indentation-change`, or an AST comparison of the moved code;
- a rename: the exact `sed` or `git grep` that reproduces it;
- formatting: the repository's configured formatter reproduces it, if there is one.

A hunk that no tool can prove is not mechanical: a reader skips mechanical hunks, and only the proof stands in for their reading. If your mode settings say that you run no repo code, only a move has a proof: a rename or a formatting hunk is then wiring.

## <a id="risk-list"></a>Risk list

At most 5 places where a bug costs the most, each as `path:start-end` with one line on why. A migration is always on it. The lenses and the verifiers start from it.

## <a id="depth"></a>Depth

The tier sets how much the review spends. Use the higher of two tiers: the spec's **Review Tier**, and the tier that the diff shows. The Review Tier definitions in the spec template of your mode settings decide both. A schema migration, a permission change and a dual write are risky changes: tier 2. A change under `.github/`, `helm/` or `scripts/` is at least tier 1, whatever its size: a workflow or a script has no test to catch it. Tier 0 is only for a diff with no core-logic hunk and no such file. Without a spec, use the diff's tier. A spec tier lower than the diff's is a finding.

| Tier | Lenses | You apply |
|---|---|---|
| 0 | No lens subagent. | The `rules` and `tests` sections, as your own pass. |
| 1 | `generic` and `domain`, plus `design` when the diff has a core-logic hunk (`labels`). The domain lens also gets the `rules` section. | The scope check of the `rules` section, in your own pass. |
| 2 | `generic`, `domain` and `design`. The domain lens also gets the `rules` section. | The scope check of the `rules` section, in your own pass. |

Write the tier on a line of its own, as `TIER: <n>`. On the next line, give one reason for the tier. In CI, the job reads this line: at tier 0, it lets you post with no lens.

## <a id="lenses.select"></a>Pick the checklist sections

Read [checklists.md](checklists.md), and the personal checklists if your mode settings allow them. A section applies when its lens runs at this tier (`depth`), and its "Applies when" line matches: "always", a changed file (the diff of your mode settings, with `--name-only`), the content of a changed file at the head (search it as your mode settings say), or an added or removed line. Name to each lens only the sections of that lens.

## <a id="lenses.roster"></a>Start the lenses

Start the lenses that `depth` asks for, in parallel, as your mode settings say. Start the description of each lens with `lens:`, for example `lens: domain`, and pass `model: "opus"` to the Agent tool. Give each lens:
- its name and the absolute path of this folder;
- these ids of `lenses.md`: `lenses.table`, `lenses.brief`, `lenses.dont-report`, `lenses.schema` and `verify.evidence`, plus `lenses.commands` if your mode settings give it;
- each checklist file with the ids of its sections (on a spec PR, the `spec.md` check numbers of the lens);
- what only you know: the PR title and body (if there is a PR), the head, the diff and how to read a file at the head (your mode settings), the risk list, the existing threads (in CI, the path of `.ci/review-threads.json`), the later PRs of a stack (if your mode settings have the stack check), the repo runtime facts, and whether the review runs repo code (your mode settings).

Paste the text of each applicable checklist section into the brief **verbatim**, under its id, after the ids: never a summary and never a paraphrase, so that the lens starts reading code at its first turn. The lens may still open the files its brief names.

<a id="lenses.table"></a>**The lenses:**

| Lens | How | Looks for |
|---|---|---|
| **generic** | As your mode settings say. | Bugs a careful reader finds in the diff: logic, removed behavior, language pitfalls. **Callers:** for each changed signature, return shape, field name or constant, `git grep` every caller and reader at the head and check each one; a caller the diff did not update is a finding. **A function the diff edits is read whole:** a wrong value it computes is in scope even on a line the diff leaves. |
| **domain** | A subagent. | Its checklist sections. It reads outside the diff: callers, the framework, the migration history. **Existing data:** for every rule the diff adds or tightens (a policy, a filter, a validator, a required field, a lookup), it names which records or callers that exist today the rule would reject, and the query that counts them. |
| **design** | A subagent. | Its checklist sections. |

<a id="lenses.commands"></a>**Command rules.** These rules apply only when your mode settings give them, or your brief names them. CI denies these shapes, and each denial costs a turn.
- Run one plain command per call, from the current directory.
- Do not start a command with a shell variable (for example `B=origin/master; git diff $B`).
- Do not use `cd` or `git -C`.
- Do not run `python3`.

<a id="lenses.own-pass"></a>**Your own pass.** Read the hunks of the risk list, and apply the sections that `depth` gives you. Your own findings follow `lenses.schema`, each with a verdict and the evidence that `verify.evidence` asks for: you act as their lens. Write them in a message, one per line (in CI, the job reads them). Write your findings down before you read the lenses' output, so that theirs do not steer yours: while the lenses run in the background, or before you start them when they run in the foreground.

<a id="lenses.brief"></a>**The lens brief.** This block speaks to the lens.
- You are the lens that your brief names. Your task is the "Looks for" cell of your row in `lenses.table`.
- Read only the sections that your brief names, from the folder that it names.
- Read the code with `Read`, `Grep`, `Glob` and `git diff`, `git log` or `git show`. Do not edit any file, and do not post anything. Report to the session that started you.
- Start no subagent.
- If your brief names `lenses.commands`, run commands as it says.
- Also report a finding that an existing thread raises, and mark it `[in thread]`.
- Also report a finding that the PR title or body states as a risk, and mark it `[disclosed]`.
- Report each finding in `lenses.schema`, with the evidence that `verify.evidence` asks for.

<a id="lenses.dont-report"></a>**Do not report:**
- an issue in code that this change does not touch, does not newly call, and does not compute a value from (a wrong value computed by a function that the diff edits is in scope, on any line of it);
- what a linter or formatter catches;
- a pedantic nit;
- a rule that the code silences on purpose (a `noqa` with a reason);
- a decision that the spec or the ticket already made, unless there is new evidence. A risk that the PR title or body states is not such a decision: `lenses.brief` says how to report it;
- a performance concern without a number (a row count, a plan, a timing), unless an `AGENTS.md` rule or the `sql-perf` section names the shape (a query, a subquery, a `$lookup` or an external call inside a loop or per returned row);
- a coverage finding (`tests` checklist, "The risk list is covered" or "A removed test leaves no gap") without the coverage evidence of `verify.evidence`. "Only one test covers this" is not a coverage finding. A finding on a test rule (level, isolation, home, a futile test) is a rule finding.

<a id="lenses.schema"></a>**Finding schema:** one finding per line, in this order:
1. The severity, at the start of the line, with the team's definitions:
   - `[critical]`: breaks the feature in production for real users or data, or forces a major design change later (an access rule that rejects data a client reads today, a write to the wrong database, a crash on an existing record, a leaked secret);
   - `[major]`: a bug or a design issue that will cost a fix later (a wrong value, a race, a caller not updated, a rule broken, a copied fact);
   - `[minor]`: style, naming, a comment, nothing that affects production.
   When in doubt between two levels, take the higher: a reviewer downgrades more easily than a user reports an outage.
2. `[must fix]`, on each `[major]` from the design lens or under a rule of the `sql-perf` section.
3. `[in thread]`, when an existing thread raises the finding.
4. `[disclosed]`, when the PR title or body already states this risk.
5. `file:line` · rule (quoted, or the checklist id) · failure (one concrete input or state → the wrong result, as `verify.evidence` says for its kind) · smallest fix · lens · the verdict and the evidence that `verify.evidence` asks for (for each `[critical]` and `[major]`).

For example: `[major] [must fix] path/file.py:42 · design: one home per fact · … · design · confirmed: …`.

## <a id="verify"></a>Verify every finding

Do steps 1 to 3 before you start a verifier, so that no verifier checks a finding that is then dropped.

1. **Merge duplicates,** and mark which lens found each one. A merged finding keeps the highest severity, any `[must fix]` or `[disclosed]` tag, and the strongest verdict that carries evidence (confirmed over plausible over not real). Two lenses that report the same defect is itself evidence: mark the merged finding `[two lenses]`.
2. **Drop** a finding that an existing comment already makes.
3. **In a stack,** if your mode settings have the stack check: read the same code at the top of the stack, as they say. If a later PR removes the defect, mark it **fixed later in #m**. Such a finding is not a comment, unless this PR is unsafe to merge or deploy alone.
4. **One verifier per serious finding.** At every tier, start one subagent per `[critical]` and per `[major]` finding, as your mode settings say. A `[disclosed]` tag does not change this. A verifier produces evidence; it is not a gate: its verdict is attached to the finding, and the finding is reported whatever the verdict, unless the verdict is not real with the evidence that `verify.evidence` asks for. Also start one for a merged finding whose verdicts include both confirmed and not real, whatever its tags are. Start its description with `verify:`, and pass `model: "opus"` to the Agent tool. It edits no file, posts nothing and starts no subagent. Give it:
   - the absolute path of this folder;
   - the PR title and body (if there is a PR), the head and how to read it, the base, the repo runtime facts, and whether the review runs repo code (your mode settings);
   - the claim only (`file:line`, rule, failure), not the lens's verdict or evidence;
   - the id `verify.evidence` of `lenses.md`, plus `lenses.commands` if your mode settings give it.

   It reports in at most 5 lines: a verdict with the evidence that `verify.evidence` asks for. Its verdict wins. Every other finding keeps the verdict of its lens.
5. **Check only that each verdict carries the evidence** that `verify.evidence` asks for. Without it, the finding is plausible. Do not change a severity, a tag or a verdict for another reason. Steps 1 to 3 can drop a finding. After them, drop a finding only when the `spec.md` filter drops it, or when its verifier says not real with the trace that `verify.evidence` asks for. A lens's own not real does not drop a `[critical]` or `[major]` finding: a verifier decides. A `[disclosed]` tag is no reason to drop a finding.

<a id="verify.evidence"></a>**Evidence and verdicts.** This block is the only home of the evidence rules. Each finding needs the evidence of its kind:

| Kind | Evidence |
|---|---|
| A behavior finding | One concrete input or state traced through the code at the head, with the `path:line` steps, and the same input or state at the base to show that this change brings the failure. |
| A rule finding (a checklist item or an `AGENTS.md` rule) | The quoted rule, the diff line that breaks it, and the state that exposes it (for example, an older Django version or an existing database record). It needs no wrong output today. |
| A coverage finding | A concrete mutation or input, and for each test that reaches the hunk, the assert (`path:line`) that still passes under it. For a removed test, add its assert at the base that fails under the mutation. It needs no test run. |

Give each finding one verdict:
- **confirmed:** the evidence of its kind shows the failure or the rule break. Say where: the code, a test run, Sentry, logs.
- **plausible:** the evidence is not complete, so the finding needs the author or a test.
- **not real:** the code shows that the failure cannot occur, and the evidence is the same as for confirmed, in reverse: the concrete input the finding names, traced through the code at the head with `path:line` steps, ending in the right result. A `not real` without that trace is `plausible`. A rule finding is never not real on the ground that the break has no visible effect today.

A finding is never dropped or demoted for being small, unlikely, out of the ticket's scope, or "low value": those are the author's calls. The only reasons to drop are the ones above.

Findings are a triage, not a fix order. The reviewer and the author decide what is fixed.
