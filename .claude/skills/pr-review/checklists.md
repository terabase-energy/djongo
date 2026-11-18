# Checklists

One section per topic. The line under each heading says which lens gets it and when it applies (see `lenses.select` in `lenses.md`). The tier decides which lenses run (`depth`), so a section has no tier of its own. A personal `~/.claude/review/checklists.md` uses the same format: a section with the same id replaces the team one, and a new id adds one.

To add a topic, add a section here with its own id and its "Applies when" line. Split this file again only if it grows past about 300 lines.


## <a id="data"></a>Data, deploy and concurrency

Lens: domain · Applies when: a changed file is a migration, a `models.py`, a management command or a file under `scripts/`, or an added line matches `transaction\.atomic`, `select_for_update`, `FOR UPDATE`, `mongo_transaction`, `RunPython`, `AddField`, `RemoveField`, `delete_many`, `\.delete\(` or `update_many`.

- [ ] **Old pods, new data:** during the deploy, old pods read what the new code writes. Does every new data shape load in the old code? Does an absent Mongo key have a defined meaning?
- [ ] **Existing rows:** what do old rows get, a backfill or an absent key, and does every reader handle that value?
- [ ] **Migration order and rollback:** is the rollback order explicit, and safe with the data that the new code already wrote?
- [ ] **Lock order:** are locks taken in one fixed order? Does the read that decides a write run under the lock?
- [ ] **The right database:** does each read, write or transaction use the intended database alias and connection?
- [ ] **Read, then act:** does a delete, a cleanup or a bulk update decide from a read taken outside the transaction or the lock? Between the read and the write, a row can appear, change or be claimed by another worker. The decision must be re-read inside the transaction, or the write must carry the condition it relies on.
- [ ] **Lock scope:** does a lock or a transaction span only the write it protects? A lock held across an external call, a loop over all rows or a long read blocks every other writer for that time.

## <a id="sql-perf"></a>SQL and performance

Lens: domain · Applies when: an added line matches `cursor\.execute`, `\bSELECT\b`, `\bJOIN\b`, `executemany`, `\.raw\(` or `aggregate\(`.

- [ ] **Set-based:** is there a per-row query, or an `executemany`, on a path that a large write uses?
- [ ] **Indexes:** does the query fit the existing indexes? Does a new index name its write cost?
- [ ] **Per-row work on a list path:** a correlated subquery, a `$lookup`, an aggregation or an external call that runs once per returned row, or a "latest" subquery evaluated over every history instead of the current one. These shapes are findings without a timing: the row count of the collection is the number.

## <a id="ci"></a>CI and deploy workflows

Lens: domain · Applies when: a changed file is under `.github/` or `helm/`, or is named `configure.yaml`, `*.yml` or `*.yaml` under a scripts folder.

- [ ] **Every reference has a producer:** for each `${{ steps.<id>.outputs.<name> }}`, `needs.<job>.outputs.<name>`, `env.<NAME>` or `inputs.<name>`, find the step, job, env block or input that sets it at the head. A reference with no producer is empty at run time and fails silently (a promotion with an empty target, a deploy to nowhere). That is a `[critical]`.
- [ ] **Every path exists:** each script, action or file a step calls exists at the head, at the path the step uses after the checkout it runs under.
- [ ] **Removed environment, remaining references:** when the diff removes an environment, a job or a secret, grep the whole `.github/` and `helm/` tree for its name; each remaining reference is a finding.
- [ ] **No inline script** in a `run:` block (`AGENTS.md`, "CI/CD Workflows").



## <a id="tests"></a>Tests

Lens: domain · Applies when: always.

The rules live in `AGENTS.md`, "Testing Strategy" and "Test Architecture".

- [ ] **Level:** is each new test at the level that fits its job (unit for logic, integration for data access, acceptance for a user scenario)?
- [ ] **The trap is not mocked:** does a test mock the boundary where the bug can be?
- [ ] **The risk list is covered:** for each risky hunk, make one small mutation in your head (invert a condition, drop a filter or a flag, swap a write order). Does a test fail under it?
- [ ] **A removed test leaves no gap:** for each test that the diff deletes, find a mutation that it catches. Does a remaining test fail under the same mutation? If one does, the removed test was redundant: not a finding.
- [ ] **Each assert can fail:** can each assert of a new test fail on a wrong result? An assert that the fixture state makes always true (for example, "no rows" on a project that never had rows) proves nothing. A guard assert that checks the setup before the action is not a finding.
- [ ] **No futile test:** does a test only restate a declaration, or test the framework?
- [ ] **Isolation:** does each test isolate its database state and avoid depending on another test's execution order?
- [ ] **Home:** is a new test in the existing file and class for its subject? Does its name claim no more than it checks?

## <a id="rules"></a>Repo rules and scope

Lens: rules · Applies when: always.

- [ ] **Repo rules:** a clear violation of `AGENTS.md` or a scoped `CLAUDE.md`, with the rule quoted.
- [ ] **Scope:** the diff does what the spec, the PR body and the ticket (when you have it) say, and nothing more. A departure from the spec is in its `## Implementation` section.
- [ ] **Unrelated hunk:** a hunk that the title, the body and the ticket do not explain: another module, a key, a secret, a credential, a dependency pin, a config value, a generated file. Report it as `[major]` with the hunk and the line of the PR body that should have named it; a key or a secret is a `[critical]`. An agent-written PR brings such hunks from a stale branch or a leftover edit, and a reader skims them.
- [ ] **Imports:** at the top, in three groups. An inline import has a comment that names the cycle it breaks (`AGENTS.md`, "Imports").
- [ ] **Logging:** use the existing module logger and preserve the exception and its context.
- [ ] **Commits:** Conventional Commits with the Linear issue when one exists (`AGENTS.md`, "Authoring commits").
- [ ] **CI:** no inline script in a workflow `run:` block (`AGENTS.md`, "CI/CD Workflows").
- [ ] **Prose:** no stale name, docstring, comment or PR-body claim left from an earlier round, and no dead code.

## <a id="readability"></a>Readability for a human reviewer

Lens: domain · Applies when: always. Check only the added and changed lines.

- [ ] **A reader gets it from the code alone:** a hunk makes sense without the spec, the ticket or the chat. A name that needs the spec to make sense is a finding.
- [ ] **Complexity did not grow without a reason:** compare the changed control flow at the base and head; use the repository's configured complexity checker when available. A new or higher score needs a reason in the PR.
- [ ] **Flat control flow:** an early return before a nested `else`; no boolean parameter that switches the behavior of a function.
- [ ] **Comments:** a comment gives a fact the code cannot show (a trap, a reason, an accepted risk). No comment restates the code, and none holds a ticket number or a design-doc id.
- [ ] **Docstrings:** a public function with a complex input or output states both, with a small example.
- [ ] **No magic value:** a literal with a meaning is a named constant or a `Literal` type.

## <a id="design"></a>Design

Lens: design · Applies when: always. Check only the added and changed lines: a problem that existed before the change is not a finding.

- [ ] **One job** per function and module.
- [ ] **Narrow inputs:** a function takes only what it reads.
- [ ] **One home per fact:** a rule, check, mapping, helper or constant lives in one place. Search the repo before you accept a new helper.
- [ ] **Layering:** dependencies point one way. A lower layer does not import an upper one.
- [ ] **No branch on a kind:** a new kind adds a table entry, not an `if`.
- [ ] **No unused abstraction:** each PR holds only what it uses. No production default or parameter exists only for tests. An interface, a hook or a parameter needs a second caller today; YAGNI wins over SOLID.
- [ ] **Testable shape:** a function that needs more than 3 mocks for one test does too much, or reaches past its layer.
- [ ] **Errors:** no bare `except`, and no error that the code swallows. An error message names what failed and for which id.
- [ ] **Names:** one name per concept, and each name matches what the code does.
- [ ] **A shared type widened:** when a type, a serializer, a dataclass or a base class is reused for a second record family, every reader of the first family's fields now receives records that may lack them. Name the reader and the field.
- [ ] **A projection or a field list copied:** a hand-written list of fields next to a serializer or a model drifts the first time one of them changes; a new field then renders empty. One home for the list.

**The fix you suggest** is smaller than the problem. It adds no new abstraction, unless the finding is that one is missing.
