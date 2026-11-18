# Workflow: a spec or a plan

Use this file when the diff holds a spec (`docs/plans/ISSUE-xxxx/spec.md`, see the `spec-pr` skill) or a plan.

## <a id="spec.approved"></a>Which review

The spec is the first commit of the PR that implements it. The `plan-approved` label decides the review:

| The PR | Review |
|---|---|
| No `plan-approved` label | The spec, with the rest of this file. Code, if there is any, with the default steps. |
| `plan-approved` label | The code, with the default steps. Read the spec as context, and review only its `## Implementation` changes, as departures from the spec. Skip the rest of this file. |

## Why a spec review is different

An agent implements the spec, and a review of the implementation PR finds the code-level defects. So a spec comment must change a decision, or give a fact that the implementer cannot find.

## What changes from the default

The labels, the lenses and the report change:

- **Labels:** no labels and no hunk groups.
- **Lenses:** no `generic` lens, and no checklist sections; use the checks below. The domain lens takes checks 2–10, and the design lens takes checks 1 and 11–13, so the design lens always runs on a spec. Tell them to check each claim in the code, not only to read the spec.
- **Data checks (check 6):** a read-only script that prints only aggregates, with no names or emails. The user opens any production access. Skip them when your mode settings say that you run no repo code.
- **Filter, after check 12** (because check 12 shows whether the planned test can catch the bug): keep only a finding that is a decision, a fact that the implementer cannot find, or a bug that the spec prescribes. Drop a bug that fails visibly while the implementer works: an existing or planned test fails, or the first run crashes. Except in CI, tell the user which findings the filter drops, after the findings.
- **Missing test:** if no existing or planned test catches a bug, the comment names the issue and suggests the test that catches it. Trace it through one concrete request, and leave the fix to the implementer.

## <a id="spec.tests"></a>Tests to implement

After the findings, because it needs the lenses' checks, give the user one section that lists the tests that matter most for this spec, at most 7, most important first. Build it from the risk list, from checks 4, 5, 7, 8 and 12, and from the spec's "Acceptance criteria → tests" table.

Apply the test sections of `AGENTS.md` to each test for its level, shape and isolation. Search the tests first. If an existing test case has the same setup, extend it with an assert, or extend a scenario with a small step. Propose a new case only when no existing one fits, and a new file only when no subject file exists.

For each test, give one line per field:
- **Test:** what it does, in domain words (the given, the action, the expected result).
- **Level:** unit, integration or acceptance, as `AGENTS.md` "Testing Strategy" says.
- **Where:** the existing test to extend (`path::test_name`), or the subject file for a new case, with one line on why no existing case fits.
- **Catches:** the concrete failure it stops, traced through one request.
- **Must not mock:** the boundary where the trap is, if there is one (for example the real serializer, the real database, the replica routing).
- **In the spec:** "yes", "yes, but too weak" (say why), or "missing".

Leave out a test that the spec already plans correctly, unless it is one of the top 3 risks. A test the spec is missing becomes a comment only if the filter keeps it (the "Missing test" rule above); otherwise it stays in this section as a suggestion for the author.

## Checks

| # | Check | Spec section |
|---|---|---|
| 1 | **Scope.** The spec does what the ticket asks, and nothing more. It names each departure from the ticket, with a reason. | Context |
| 2 | **Consumers and contracts.** The spec names each client of the change (Django applications, management commands, other libraries) and what each one reads: the field, the values, the meaning of null, the endpoint. Check the client repos, when they are on this machine. | Changes |
| 3 | **Claims about the current code are true.** Check each statement about how a path works and which roles reach it. | Context, Changes |
| 4 | **The prescribed mechanism has no trap.** Trace one concrete request through the text, as the implementer will copy it. | Changes |
| 5 | **Every path that reads or writes the data is listed,** also the indirect ones: copies at sign-up, nested serializers, raw-document loads (`Model(**doc)`), the data refresh. | Changes |
| 6 | **Data assumptions hold on staging and prod,** checked read-only. Local seed data proves nothing. | Data and migrations |
| 7 | **Existing records.** The spec says what old rows get (a backfill or an absent key), and every reader handles that value. | Data and migrations |
| 8 | **Deploy and rollback.** Old pods read the new data during the deploy, so every new data shape loads in the old code. The rollback order is explicit and safe. | Risks and rollback |
| 9 | **Compatibility.** The spec accounts for the supported Django and PyMongo versions and existing database records affected by the change. | Changes |
| 10 | **Access.** The spec says who can read and write the new data, also through endpoints without authentication or across companies. | Changes, Risks and rollback |
| 11 | **Decisions and manual steps have an owner.** Read past "Open questions: None." and look for silent choices and work after the deploy. | Open questions |
| 12 | **Each criterion's test can catch its failure.** A test that mocks the boundary where the trap is cannot catch the trap. | Acceptance criteria → tests |
| 13 | **The Review Tier fits the change, and each planned PR is self-sufficient:** it carries the tests for its own change, a helper lands beside its first caller, and no PR imports code that a later PR deletes. | Review Tier, Changes |

**Not for spec comments,** because the implementation review finds them: the call order inside a function, a missing attribute, a wrong line number, a migration number clash, and nits.
