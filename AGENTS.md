# AGENTS.md

This file provides shared guidance to Claude Code and Codex when working in this repository.

## Development Environment

Djongo is a Django database backend that translates SQL queries into MongoDB queries.
Dependency requirements are declared in [setup.py](setup.py) and [requirements.txt](requirements.txt).
Use this repository's existing test tooling in [tox.ini](tox.ini); do not assume the tooling of a consuming application is available here.

### Testing Strategy

Always run relevant tests after changing code, using the existing test runners and a compatible Python, Django and PyMongo environment.

**Core principle:** Unit tests verify logic, integration tests verify data access. Acceptance tests verify real-life scenarios.

- **Unit tests:** mock external boundaries to verify branching and orchestration logic quickly.
- **Integration tests:** use a real database when query semantics, data access or connection behavior are the subject of the test.
- **Acceptance tests:** validate user-facing scenarios against acceptance criteria when applicable.
- **Skip tests** for trivial declarations or code with no branching logic.

### Test Architecture

- [tests/mock_tests/](tests/mock_tests/) contains mocked SQL translation tests.
- [tests/djongo_tests/](tests/djongo_tests/) contains the Django test project and Djongo-specific tests.
- [tests/django_tests/](tests/django_tests/) contains Django compatibility tests and their runner.
- [tox.ini](tox.ini) defines the existing test environments and commands. Verify referenced paths exist before using a command; some environments refer to legacy paths.

Extend the existing test for a subject before adding a new file. Do not mock the boundary whose behavior the test must verify.

### Imports

Always place imports at the top of the file. Group them in this order, with a blank line between each group:

1. **Python standard library** — `import os`, `from datetime import datetime`, etc.
2. **Third-party libraries** — `django`, `pymongo`, `bson`, `sqlparse`, etc.
3. **Project modules** — internal `djongo` modules

Inline imports (inside functions or methods) are only acceptable when:
- The import is platform-specific and guarded by a `try/except` (e.g. `import ctypes` for Linux-only calls)
- It is required to break a circular import — add a comment explaining the circular dependency

### Authoring commits

We use Conventional Commits. No need to provide a scope. When the change has a Linear issue, mention its identifier in the description. For instance:

```
fix: [ISSUE-1234] correct query translation
```

You can add more details to the body. Keep details short, explain the intent, not the content.

### CI/CD Workflows

Never inline a script of any language in a workflow YAML's `run:` or `script:` block — put it in `.github/scripts/` and have the step call that file.
