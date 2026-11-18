# [IFR-561] Reuse process-owned Mongo clients across Django wrappers

## Context

[IFR-561](https://linear.app/terabase/issue/IFR-561/staging-documentdb-connection-churn-and-request-failures)
reports staging DocumentDB connection pressure and authentication failures. This
spec uses the supplied ticket snapshot; its historical cloud measurements have
not been refreshed as part of this work.

The library code matches the ticket's Djongo baseline, commit
`6b516395a4cbf91eff70ac465acb54cf7946a8d7`:

- [database.connect](../../../djongo/database.py) constructs a client on every
  call. Its database-name dictionary retains only the last client, without reuse.
- [DatabaseWrapper](../../../djongo/base.py) closes an existing client before
  reconnecting and closes the client's entire pool during wrapper cleanup.
- Its autocommit overrides force `False` even when Django configures `True`.
  Django cleanup therefore closes wrappers even with `CONN_MAX_AGE=None`.
- Sessions and transaction state live on the wrapper and its `DjongoClient`.
  [Transaction](../../../djongo/transaction.py) owns session/transaction context
  managers. [Relation writes](../../../djongo/models/fields.py) and
  [SQL operations](../../../djongo/sql2mongo/query.py) obtain their session from
  the wrapper's `DjongoClient`.
- [Test-database cloning](../../../djongo/creation.py) directly closes the raw
  client and must also respect the new ownership boundary.

A fresh offline reproduction on November 18, 2026 used Django 5.2.9, PyMongo
4.15.5, asgiref 3.11.1 and gevent 26.4.0 from the existing backend environment.
In a fresh interpreter, gevent patched before Django imports; three batches of
four request greenlets initialized their real Django wrappers and invoked
`close_old_connections()`. Only `MongoClient` construction was mocked, with
database handles pointing back to their owning mock client.

| Maximum connection age | Requests | Distinct wrappers | Clients constructed | Clients closed |
|---|---:|---:|---:|---:|
| `0` | 12 | 12 | 12 | 12 |
| `None` | 12 | 12 | 12 | 12 |

This proves the lifecycle defect locally. It does not measure real sockets or
establish the cause of every reconnect. Aggregation memory failures remain
separate from the connection-lifecycle change.

## Open questions

No unresolved library ownership decision blocks this spec. Before a backend
rollout, the Construct Infra owner must confirm the inputs of the
[connection budget](#connection-budget): current topology, maximum process
counts including deployment overlap, other Mongo consumers, the per-instance
limit and the monitoring-socket assumption. These determine application pool
limits, not whether Djongo should retain process-owned clients.

Run the read-only [capacity collector](../../../scripts/collect_docdb_capacity.py)
once per environment with that environment's active AWS configuration and its
DocumentDB cluster identifier. The [collector guide](../../../scripts/README.md)
describes its output and permissions. Reports include their account and region,
cluster topology, connection/limit history, and discoverable EKS/DMS consumer
configuration. Review collection gaps and cross-account consumers before treating
these inputs as a complete fleet budget.

Real MongoDB replica-set and DocumentDB validation require suitable test
environments. Availability must be recorded before claiming those checks passed.

## Acceptance criteria → tests

| Criterion | Test (level) |
|---|---|
| Repeated and concurrent requests reuse a client for an unchanged connection identity, including after an idle interval with no attached wrappers. | Run the reproduction for both age settings: 12 distinct wrappers, one client construction, zero client closes until explicit process shutdown. Exercise Django request-start/request-finish signals as well as explicit task-style closes. Unit/subprocess. |
| Closing or reconnecting one wrapper does not interrupt another borrower. | Overlap two wrappers and cursors; close one, then successfully use the other. Reconnect the first and verify client identity and fresh wrapper-local state. Unit, plus real database integration. |
| Aliases with the same connection identity share one client; different identities never do. | Aliases differing only in database name or read preference share one client. Vary hosts/URI, credentials, authentication source, TLS, `tz_aware`/`tzinfo` and pool options independently and assert separate clients. Equivalent reordered keyword dictionaries reuse; distinguish value types and meaningful sequences. A wrapper from `connection.copy()` (deep-copied settings) reuses the original client. An unsupported option value, such as an event-listener list, raises `ImproperlyConfigured` naming only the key. Unit. |
| Supported timezone settings retain the same client identity after settings are copied. | With real `datetime.timezone` and `bson.tz_util.FixedOffset` values, repeatedly call Django's `connection.copy()` and assert one registered client for the original and copies. Do not mock copying, timezone objects or key generation. Distinct offsets, names and supported timezone types have distinct keys. A custom timezone subclass, including an unhashable one, raises `ImproperlyConfigured` naming only `tzinfo` before constructing a client. Unit. |
| Each alias keeps its read preference on a shared client. | Configure `primary` and `secondaryPreferred` aliases on the same database: assert one client, and that each wrapper's database handle, cursor reads and cached-collection listing carry the alias's read preference, tags and staleness. A read preference embedded in a URI `host` yields a separate client. Unit, plus replica-set integration observing the selected server. |
| First acquisition is safe under threads and greenlets, never blocks a gevent hub, and constructor failure is retryable. | Synchronize concurrent acquisitions; assert exactly one published client per key, every caller receives it, and each losing candidate is closed. Make construction yield (patched to sleep cooperatively) while other greenlets acquire, with Djongo imported both before and after `monkey.patch_all()`; the run completes within a timeout. Inject one construction failure, then succeed without a cached failed entry. Run gevent cases in fresh subprocesses. Unit/subprocess. |
| Wrapper-owned state remains independent. | Two wrappers share the client but have separate database handles, schema settings, cached collections, cursors, sessions, rollback state and callbacks. Interleave operations and inspect the session supplied to each driver call. Unit and replica-set integration. |
| A wrapper runs at most one Mongo transaction; nested `atomic` blocks join it, and close ends only the owner's session. | Single level: commit persists, rollback discards. Nested: inner and outer commit persist atomically; an outer rollback discards inner writes; an inner exception caught inside the outer block makes later outer queries raise Django's `TransactionManagementError` and persists nothing; `atomic(savepoint=False)` inner failure behaves the same. Every write inside the outer block, including after an inner block exits, carries the outer session. After a rollback, the next transaction on the same wrapper commits (Celery prefork regression). Abnormal close, cleanup failure and repeated close end the session exactly once. Preserve the existing autocommit hook sequence. Check persisted results against a real replica set; mock-only tests do not prove transaction behavior. Unit and integration. |
| A forked child never performs I/O through an inherited client or waits on an inherited locked registry mutex. | Fork with and without a connected parent wrapper, including while another parent thread holds the registry lock. Exercise ORM cursor and raw wrapper-client access in the child; assert a new child client, no child close of the parent's client, and continued parent usability. Subprocess, with platform-specific skips stated. |
| Explicit shutdown/reset is idempotent and restricted to clients owned by the current process, and nothing runs at interpreter exit. | Close each registered current-process client once; repeated teardown is harmless. Importing Djongo registers no `atexit` handler. After closing wrappers and resetting, the next connection constructs a new client. Constructor and teardown exceptions cannot leave the registry locked. Unit. |
| Test-database cloning does not close another borrower's pool. | Mock dump/restore processes; assert clone cleanup detaches its wrapper, preserves the shared client and keeps source/clone database selection separate. Unit. |
| Real connection creation no longer scales with request count. | Against a local single-node replica set, run the 12-request greenlet harness without mocking `MongoClient`, for 1 and 3 batches, and read the server's `serverStatus().connections.totalCreated` from a separate observer client before and after. Baseline: the delta grows with requests. Set `serverMonitoringMode="poll"` so MongoDB monitors like DocumentDB (one socket per server, no round-trip-time socket). Change: the first batch creates at most one monitoring socket per server plus `maxPoolSize` (set small, e.g. 4); later batches create none, and the delta is identical for 1 and 3 batches. Subtract the observer's own connection. Integration. |
| Recovery and pool exhaustion retain native PyMongo behavior. | Interrupt a real connection and verify subsequent recovery without registry eviction; exhaust a small pool and verify finite configured checkout waiting without closing the shared client. Integration. |
| Supported Django/PyMongo consumers retain query results and routing. | Run existing SQL-translation regressions and focused real ORM/relation/raw-access tests with the consuming backend's versions. Run available compatibility environments and report legacy failures separately. Unit and integration. |
| Staging connection use stays within the agreed budget under bursts and maximum permitted deployment overlap. | After the downstream dependency/configuration changes, scale to the agreed maximum, fill the old workers' pools, then roll out while old pods retain their connections through preStop and draining and replacements receive a burst. Include terminating pods, worker recycling and overlapping Celery/result-backend clients. Record the simultaneous live workers/clients and per-instance connection peaks; verify both fit the reviewed budget and enforced overlap bounds. Also replay an idle period and a second burst, measuring checkout waits/timeouts, latency and authentication failures. Separate staging acceptance gate owned by Construct Infra. |

## Trade-offs

- Retain clients in a process-local registry instead of extending wrapper age.
  Django checks the autocommit mismatch before checking connection age, so
  `CONN_MAX_AGE=None` still closes the current wrapper and its Mongo client, as
  the reproduction above confirms. Even after a separate autocommit fix,
  retaining a wrapper would not make its client available to other request
  greenlets: they have separate wrappers. A process-owned registry lets those
  wrappers borrow the same pool while preserving Django's request cleanup.
- Key the registry on connection identity, not alias. Construct's `default`,
  `docdb_ro` and `events` aliases use the same hosts and credentials; they
  differ only in database name and read preference. PyMongo applies both per
  database handle (`client.get_database(name, read_preference=...)`), so one
  client per process can serve all three. Each client keeps one monitoring
  socket per instance (see the [connection budget](#connection-budget)), so a
  client per alias triples the fixed monitoring cost and consumes capacity that
  could otherwise serve application sockets. Sharing also couples pool capacity, which is the
  intent: one per-process budget is simpler to size than three. The key
  therefore excludes alias, database name and the read-preference options
  (`readPreference`, `readPreferenceTags`, `maxStalenessSeconds`), and includes
  every other effective client option, compared by value. Host, credentials,
  TLS, codec and pool options still separate clients. A read preference embedded in a URI `host` is
  not parsed out, so it stays part of the key and yields a separate client.
- The consequence is that the raw client carries no alias read preference.
  Today `wrapper.client_connection[name]` inherits the alias's routing; after
  this change it reads from the primary. Construct's `get_mongo_db("docdb_ro")`
  uses that pattern for portfolio and QC-CSV aggregations, which would silently
  move to the primary. The wrapper's database handle (`wrapper.connection`) is
  the supported way to obtain alias routing, and the downstream helper must
  switch to it in the same release. If that cannot ship together, fall back to
  including the read-preference options in the key: `default` and `events`
  still share a client and `docdb_ro` gets its own, at a lower pool budget.
- Share only `MongoClient` and its native PyMongo pools. Keep database handles,
  `DjongoClient`, collection caches, cursors and sessions outside the registry.
  The client provides reusable connections, whereas these Djongo objects carry
  the state of a particular wrapper or operation. For example, `_savepoint()`
  stores the active session on the wrapper's `DjongoClient`, and every query in
  [query.py](../../../djongo/sql2mongo/query.py) and relation write in
  [fields.py](../../../djongo/models/fields.py) passes
  `djongo_connection.session` to the driver. Sharing that object could make one
  request execute in another request's transaction, end its session, or consume
  its cursor results.
  [PyMongo sessions are not safe for concurrent use](https://pymongo.readthedocs.io/en/stable/api/pymongo/client_session.html).
  Keeping these objects local also preserves each wrapper's schema setting and
  collection-cache lifetime. This restriction concerns Djongo's stateful use of
  the handles; it does not claim that every PyMongo database handle is inherently
  unsafe to share.
- Preserve the current autocommit behavior. Redesigning transactions in the same
  change would alter which Django hooks start or complete transactions.
- Fix savepoint nesting instead of preserving it. Because autocommit is forced
  to `False`, every `atomic` block, outermost included, calls `_savepoint`. Each
  call starts a new session and transaction and overwrites the previous one, so
  today a nested block orphans the outer transaction: after the inner block
  exits, the outer block's writes run without a session, and the outer exit
  completes the inner transaction a second time. `rollbacked` is never cleared,
  so after one rollback a long-lived wrapper (a Celery prefork child) silently
  discards every later transaction. Today's per-request `client.close()` partly
  hides these leaks; a retained client would accumulate them. MongoDB has no
  savepoints, so the wrapper runs one transaction whose depth follows Django's
  `savepoint_ids`: only the outermost `_savepoint` starts it, inner savepoints
  join it, inner commits are no-ops, and the outermost commit completes it.
  An inner rollback cannot restore partial state, so it aborts the transaction
  and raises `django.db.utils.DatabaseError`; Django's `Atomic.__exit__` then
  sets `needs_rollback`, later queries in the outer block raise
  `TransactionManagementError`, and the outer exit rolls back. This turns
  silent partial commits into explicit failures. Code that catches an inner
  exception and continues the outer block, including `get_or_create` racing
  inside an outer `atomic`, now fails instead of committing partially.
- Let PyMongo recover topology and sockets. Do not introduce a second socket
  pool, a retry loop, a per-request ping or eviction on transient operation errors.
- Retain clients across intervals with zero wrappers. Reference-counted shutdown
  at the last wrapper close would recreate the original churn: when request A
  finishes and no other request is active, the pool would close; request B would
  then construct another client and repeat discovery and authentication. The
  same cycle would occur between tile bursts and Celery tasks. Keeping a strong
  registry reference allows the next request to reuse the client after that
  idle interval. The trade-off is retaining client resources while idle, which
  is why the pools need explicit limits and owning-process shutdown/reset must
  release them after callers have drained.

## Connection budget

Retaining clients removes churn but does not bound connections. Without pool
options, PyMongo allows `maxPoolSize=100` per client and an unbounded checkout
wait; each Gunicorn gevent worker accepts up to 1,000 concurrent requests.
Even the 80 API workers in the nonterminating rollout target could open
80 × 100 = 8,000 application sockets against a 1,000-connection instance.
Terminating old workers add more pools, and retained idle sockets raise the
baseline between bursts. The library change and downstream pool configuration
below must ship in the same release.

The per-instance budget, assuming a failover concentrates all traffic on one
instance:

```text
Σ over process roles r:
    live_processes_r × Σ over client identities c:
        (maxPoolSize_r,c + monitoring_sockets_per_instance_r,c)
+ other consumers + headroom ≤ DatabaseConnectionsLimit
```

Count **all simultaneously living client-owning processes**, including
terminating pods and old workers that are still draining. For the API:

```text
live_api_pods_bound = maxReplicas + maxSurge + terminating_api_pods_bound
live_api_processes_bound = live_api_pods_bound × GUNICORN_WORKERS
                          + recycling_worker_overlap
                          + client-owning master_processes
```

`maxSurge` bounds the nonterminating rollout target, not all living pods.
Staging's 30-second preStop and 200-second termination grace allow old pools
to remain open after replacements start. Eight old pods plus eight replacements
already mean 128 API workers: a pool of eight permits 1,024 application sockets
before monitors or other consumers. Therefore the previous API pool size of
eight is not an acceptable rollout budget.

The Construct Infra owner must establish and enforce the terminating-pod and
worker-recycling bounds, account for any master that initializes Mongo during
preload, and repeat the calculation for every Celery child, worker parent,
beat, migration/job and independent result-backend client. Repeated rollouts,
autoscaling and node drains can overlap; do not assume only one old generation
exists unless deployment controls enforce that. If a live-process bound is
unknown, the pool budget is not approved.

The following is a **worked example, not approved staging or production
defaults**. The replica/worker settings come from
`helm/backend/values.stg.yaml`; every allowance and the connection limit must
be confirmed separately in each environment using its collector report:

| Input | Example value / required condition |
|---|---|
| Nonterminating API pod target | 8 max replicas + 2 surge = 10 |
| Additional terminating API pod bound | 8; requires validation and enforced deployment overlap limits |
| API workers | (10 + 8) × 8 = 144 |
| Additional client-owning master/recycling processes | 0 in this example only; establish the real bound before use |
| Djongo clients per API worker | 1, shared by `default`, `docdb_ro` and `events` for matching connection identities |
| All connections outside those API Djongo clients | Reserved cap of 100, including their monitors and peak Celery/result-backend, other workload, external and cross-account use; requires measurement and bounding |
| Operating headroom | 150; an explicit example policy, not measured spare capacity |
| Per-instance connection limit | 1,000 in this example; confirm `DatabaseConnectionsLimit` in each account |

DocumentDB does not support PyMongo's streaming monitoring protocol, so each
client is assumed to hold one unauthenticated polling socket per instance,
without a separate round-trip-time socket. Confirm this with one staging
measurement before treating the figures below as final.

Under those assumptions, the maximum API pool size is:

```text
floor((1,000 - 100 other - 150 headroom - 144 API monitors) / 144 workers) = 4
144 × (4 application + 1 monitoring) + 100 other + 150 headroom = 970
```

This example supports a **candidate API `maxPoolSize=4` only if every stated
bound holds**, leaving 30 connections beyond the reserved headroom. A higher
live-process count, extra client identity, monitoring cost or other-consumer cap
requires recalculation or tighter overlap controls. Do not deploy the example
values as defaults simply because a collector run completed. The same calculation
and maximum-overlap test are required independently for production.

Downstream configuration, owned by Construct backend:

- Read `maxPoolSize`, `waitQueueTimeoutMS`, `maxIdleTimeMS` and
  `serverSelectionTimeoutMS` from environment variables in `_mongo_client`,
  and set them per workload in each `values.*.yaml`, using the approved
  environment-specific budget. The worked example's candidate API pool is four;
  Celery and result-backend pool sizes must fit the separately bounded
  other-consumer allowance. Candidate timeout values are
  `waitQueueTimeoutMS=2000`, `maxIdleTimeMS=300000`,
  `serverSelectionTimeoutMS=5000`. A short checkout timeout makes an exhausted
  pool fail the request instead of holding it until Gunicorn's timeout.
- Apply separately budgeted pool limits to the Celery result-backend URI,
  counting each process that instantiates that independent client, including
  API workers if applicable.
- Comment the budget beside `maxReplicas`, `maxSurge`, `GUNICORN_WORKERS` and
  termination/recycling settings, and enforce the reviewed overlap bounds.
- The staging replay fills old pools before replacement, sustains the maximum
  permitted old/new overlap and measures all live client owners, connection
  peaks, checkout timeouts and p99 latency. Failure of the overlap bound or the
  per-instance budget blocks rollout even if ordinary request tests pass.

Djongo keeps PyMongo's defaults and does not choose pool sizes. Its README
states that multi-process deployments must set these options.

## Data and migrations

None. No stored document shape, query routing, permission rule or database schema
changes. A consuming application must pin the resulting Djongo revision and
configure native pool options separately.

## Risks and rollback

The largest risks are cross-wrapper session leakage, using inherited clients
after fork, unsafe configuration identity, and retaining too many pools across
worker processes. Isolation, fork and configuration tests are release gates.

Raw clients returned through a wrapper are borrowed: callers must not close them.
They carry no alias read preference; callers needing alias routing must use the
wrapper's database handle. Shipping the library without the downstream
`get_mongo_db` change moves `docdb_ro` raw aggregations to the primary.
Shipping it without downstream pool options retains idle sockets with no
bound; shipping pool options without the library change has no effect, because
each client lives for one request.
Retaining a raw PyMongo handle across a process fork is unsupported; reacquire
through the wrapper after fork. A process shutdown/reset requires callers to
drain in-flight work first. No live-request pool reset is introduced.

Rejecting opaque `CLIENT` values is a breaking change for consumers that pass
event listeners, type registries, `ServerApi` or encryption options through
Django settings, or use timezone implementations outside the two explicitly
supported fixed-offset types below. The README documents the accepted types and the
`pymongo.monitoring.register()` alternative; Construct is unaffected.

Nested `atomic` semantics change: an exception from an inner block that the
outer block catches now forces the whole transaction to roll back, where today
it silently commits a partial result outside any transaction. Consumers must
audit such patterns before rollout. The same change fixes the silent loss of
transactional writes on long-lived wrappers, such as a Celery prefork child,
after the first rollback.

The library alone does not establish a safe fleet connection budget. Downstream
pool limits must include API workers, Celery children and its independent result
backend, management jobs, other clients, monitors, rollout overlap and headroom.
Checkout timeouts bound waiting time; HTTP concurrency still requires its own
limit. Do not choose arbitrary pool sizes in this library change.

Rollback consists of reverting the consuming application's Djongo pin and its
associated worker hooks/pool configuration together, then replacing workers.
Do not switch lifecycle implementations inside a running process. Stop rollout
on session leakage, changed routing, fork failures or renewed connection-limit
errors. Record aggregation-memory errors separately throughout the comparison.

## Review Tier

**Tier 2**: shared database ownership, fork safety and transaction/session cleanup
affect every ORM consumer and require full review plus real database validation.

## Changes

1. **Focused lifecycle tests.** Add
   `tests/mock_tests/test_connection_lifecycle.py` and subprocess helpers under
   `tests/mock_tests/` where needed. Capture the failing baseline first using
   real Django connection handling and early gevent patching. Extend existing
   connection tests in [test_sqlparsing.py](../../../tests/mock_tests/test_sqlparsing.py)
   where their setup already fits. Add a reproducible focused test environment
   in [tox.ini](../../../tox.ini) for Django 5.2.9, PyMongo 4.15.5 and gevent,
   without replacing the existing compatibility matrix.
   The registry is process-wide state, so add a shared fixture (an autouse
   `setUp`/`tearDown` mixin for `unittest`, applied to every test class that
   creates wrappers) that runs the documented sequence before and after each
   test: close the test's wrappers, then reset the registry. Lifecycle tests
   that count constructions assert from that clean state. Update
   `TestConnection.test_connection` in `test_sqlparsing.py` to use that
   fixture and a concrete settings dictionary instead of `MagicMock(dict)`: the
   registry validates option values and must not receive mock objects. Verify
   isolation by running the mock suite in default and reversed order
   (`unittest` with a reversed loader, or `pytest -p random_order` if
   available); both must pass.
2. **Process registry in [database.py](../../../djongo/database.py).** Replace the
   name-only dictionary with guarded lookup/construction by PID and effective
   client options, excluding the read-preference options. Preserve the
   existing `connect(db, **kwargs)` calling convention. Include
   `document_class=OrderedDict` and `connect=False` in the effective options.
   Keep schema enforcement wrapper-local. In `get_new_connection`, split the
   read-preference options out of the client keyword arguments and build the
   wrapper's handle with `client.get_database(name, read_preference=...)`,
   mapping mode names to PyMongo's public read-preference classes.
   Build the key by value: canonicalize dictionary order recursively, keep
   lists and tuples as ordered tuples, and preserve value types so `1`, `1.0`
   and `True` stay distinct. Accept only `str`, `bytes`, `int`, `float`,
   `bool`, `None`, classes (such as `document_class`), and dicts, lists and tuples
   of these. Timezone values are a separate explicit case: support **only exact
   instances** of `datetime.timezone` and `bson.tz_util.FixedOffset`, not arbitrary
   `datetime.tzinfo` subclasses. Build their canonical key from the exact type,
   the constant `utcoffset(None)` represented by its integer
   `(days, seconds, microseconds)` components, and `tzname(None)` (a string or
   `None`). Preserve the type and name even when two zones have the same offset.
   Validate those components before publishing a client. Do not hash or compare
   the timezone object itself: `FixedOffset` copies do not have value equality.
   Reject other timezone implementations, including custom subclasses and
   dateutil/pytz/ZoneInfo objects, with `ImproperlyConfigured` naming only the
   option key. Supporting a rule-based timezone later requires a separate stable
   identity policy; its offset at one instant does not identify its DST rules.
   Any other unsupported value also raises
   `ImproperlyConfigured` naming the option key, never its value. Identity is
   not a usable key: Django's `BaseDatabaseWrapper.copy()` deep-copies
   `settings_dict`, so an opaque object such as an event listener, `TypeRegistry`
   or `ServerApi` would get a new identity on each copy, construct a client the
   registry never releases, and bring the churn back. The canonical keys, rather
   than equality of the original objects, must remain equal after deep copy.
   Require the combined timezone-and-`connection.copy()` regression from the
   acceptance table for both supported timezone types. Command
   listeners belong in `pymongo.monitoring.register()`, which applies to every
   client. Construct's `CLIENT` contains only scalars. Do not use `repr`,
   JSON serialization or URI rewriting to guess equivalence. Never log keys,
   URIs, credentials or options. Publish only successful constructions.
   Never hold the registry lock while constructing or closing a client:
   construction can yield (for example DNS resolution of `mongodb+srv` hosts),
   and a real OS lock held by a yielded greenlet blocks the gevent hub when
   Djongo is imported before monkey-patching. Look up under the lock; on a miss,
   construct outside it; re-check and publish under the lock; if another caller
   published first, return that client and close the losing candidate outside
   the lock. With `connect=False` the candidate has opened no sockets or
   monitors.
3. **Explicit lifecycle operations.** Provide a documented current-process
   shutdown/reset entry point, idempotent after draining callers. Clear registry
   state even if individual closes fail, attempt all owned clients and surface
   cleanup errors. The documented sequence is to drain callers, close Django
   connections (`connections.close_all()`), then reset. No production path
   resets a live process: fork is handled by PID checks and worker shutdown
   ends all use, so stale-wrapper reattachment is not needed. A wrapper used
   against a reset client fails with PyMongo's own error. Do not register
   interpreter-exit (`atexit`) cleanup: closing a client sends `endSessions`
   over the network, which under gevent during interpreter shutdown can hang
   and delay pod termination past the grace period. Process exit already closes
   the sockets, and the server expires abandoned sessions itself. Worker
   frameworks call the entry point from their shutdown hooks (Gunicorn
   `worker_exit`, Celery `worker_process_shutdown`), where the event loop is
   still running.
4. **Fork protection and wrapper borrowing in
   [base.py](../../../djongo/base.py).** Reinitialize registry synchronization
   and drop inherited entries in an after-fork callback where supported, without
   closing inherited clients or acquiring inherited locks. Validate the owning
   PID on acquisition and before wrapper I/O. Centralize
   borrowed-client access so both cursor creation and direct
   `wrapper.client_connection` access detect stale attachments. A copied wrapper
   discards inherited local handles/session references without operating on
   them, then borrows a child-owned client. Never call PyMongo private reset APIs.
5. **Wrapper cleanup and transaction ownership.** Remove raw-client closes from
   wrapper connection/reconnection. `_close()` detaches wrapper resources and
   aborts/ends only its own active session, resetting custom transaction and
   rollback references in a `finally` path. Retain Django's
   `closed_in_transaction`/`needs_rollback` behavior. Implement the
   single-transaction nesting from the trade-offs: `_savepoint` starts a
   `Transaction` only when none is active; `_savepoint_commit` completes it only
   when `savepoint_ids` is empty; `_savepoint_rollback` aborts it, and raises
   `django.db.utils.DatabaseError` when called for an inner savepoint. Keep
   `djongo_connection.session` on the active session until the transaction
   completes, and do not replace `djongo_connection` mid-transaction. Replace
   the `rollbacked` flag with transaction state cleared when the transaction
   ends. Make [transaction.py](../../../djongo/transaction.py) end its session
   exactly once and tolerate commit/abort on an already-ended transaction,
   including exceptions while completing it. Delete the
   `self.client_connection[name].__setattr__('session', ...)` lines in
   `_savepoint` and `_savepoint_commit`: `client[name]` returns a new `Database`
   object on every access and nothing reads the attribute. Audit relation/query
   call sites; no session or mutable database handle enters the registry. Do
   not change autocommit semantics to implement pooling.
6. **Clone cleanup and lifecycle documentation.** Change the direct client close
   in [creation.py](../../../djongo/creation.py) to wrapper cleanup. Document
   borrowed-client ownership, alias routing through the wrapper's database
   handle, fork reacquisition, explicit teardown and the required native pool
   options with the budget formula in [README.md](../../../README.md). Keep construction and
   explicit shutdown diagnostics limited to alias, PID and lifecycle reason.
7. **Integration verification and downstream handoff.** Add focused replica-set
   tests alongside [Djongo tests](../../../tests/djongo_tests/) for isolation,
   transaction outcomes, native driver recovery, and the real-socket
   `totalCreated` comparison. The socket test runs once against the baseline
   commit to record the before figure, then against the change. It needs a
   local `mongod` started as a single-node replica set (transactions require
   one); skip with an explicit reason when the binary is absent. Record results before
   publishing the library fix. Construct backend work ships in one release
   with the new pin: `get_mongo_db` on the wrapper's database handle, the
   pool options and per-workload values from the
   [connection budget](#connection-budget), Gunicorn/Celery teardown hooks,
   removal of the `reset_djongo_savepoint_state_after_rollback` fixture in
   `terabase/conftest.py` (it patches the replaced savepoint methods and sets
   the dead `session` attribute), an audit of code catching exceptions from
   nested `atomic` blocks, and the staging replay. This PR does not modify or
   deploy that repository.

Out of scope: aggregation optimization, authentication/permission caching,
instance resizing, changing read preferences, transaction changes beyond
single-transaction nesting, and live database operations.

## Verification

- Re-run the offline 12-request subprocess reproduction against the library
  change for both `CONN_MAX_AGE` values and request/task cleanup paths. Assert the
  acceptance counts and zero client closes before explicit teardown.
- Run the new focused tox environment and existing mocked SQL-translation
  tests, in default and reversed order. The environment must declare all
  required test dependencies and use this checkout, without depending on the
  backend's virtual environment path.
- Run the real-socket `totalCreated` test against the baseline commit and the
  change, and record both deltas. This is the only evidence below staging that
  real connection creation fell.
- Run thread/greenlet first-use races (with Djongo imported before and after
  gevent patching), constructor failure, reset/shutdown,
  configuration identity, overlapping wrappers, clone cleanup and fork probes.
  Use timeouts so synchronization regressions fail instead of hanging.
- Copy real Django wrappers containing each supported fixed-offset timezone;
  verify the same registered client is reused across repeated copies and that
  unsupported timezone types fail before constructing one.
- Run replica-set transaction, ORM/relation, checkout-timeout and recovery
  checks. State explicitly which require unavailable services, binaries or
  compatible runtimes; mock results cannot substitute for socket/transaction
  evidence.
- Check changed file whitespace, documentation links and the complete branch
  diff. Self-review every changed lifecycle call site.
- The downstream staging gate refreshes topology and fleet sizing, pins the
  tested revision, rolls out hooks and pool settings, then measures burst,
  idle/reuse and maximum permitted old/new deployment overlap with populated
  pools. Record terminating pods, draining/recycling workers and independent
  clients as well as ready replicas; verify both the live-process bounds and
  per-instance connection budget. Repeat independently for production. Local validation does not claim
  that deployment or live remediation occurred.
