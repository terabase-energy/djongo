# <a id="comment-style"></a>Comment style

The same as the built-in `code-review`. `pr-review` posts in this style in CI:
- A short description of the issue: the condition, and the concrete failure. When a test would catch it, suggest that test.
- Cite the rule it breaks, with a link: the `AGENTS.md` or `CLAUDE.md` section, or the checklist file.
- A committable `suggestion` block only for a small fix that is complete alone. For a larger fix (6 lines or more, a structural change, or more than one place), describe it without a block.
- Code links are permalinks with the full sha and at least one line of context on each side: `https://github.com/<repo>/blob/<full sha>/<path>#L4-L7`.
- One issue per comment. Never write a verdict ("approved", "LGTM").

## <a id="anchors"></a>Anchors

A finding on a deleted line uses `side: LEFT` and its line number at the base. A range uses `start_line` and `line`.
