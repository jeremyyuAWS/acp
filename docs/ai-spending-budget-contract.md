# Metered provider spending reservation contract

This is an opt-in ledger, not yet wired to provider dispatch, run creation, or the UI.
It bounds admitted **metered provider exposure** only when the caller supplies and
enforces a valid upper bound for every potentially billable attempt. It does not cap
shared infrastructure, provisioned GPU time, hosting, storage, or other Azure costs.
No real provider prices are included. Test amounts are synthetic.

## Ownership and integration

This task owns `api/ai_spending_budget.py`, `tests/test_ai_spending_budget.py`, and
this document. Provider dispatch/waterfall and frontend integration belong to other tasks.
The deadline is September 9, 2026 at 10 a.m. Pacific.

Construct `BudgetLedger(store._db)` using the existing SQLite or Postgres adapter.
Do not instantiate a global Store as a fallback. The module uses only the adapter's
`cursor`, `execute`, `fetchone`, and `fetchall` methods, and inspects its transaction
context to reject calls inside an ambient Store transaction. The dispatch claim must
commit before a network call. Database failures propagate and grant no permission.

`SCHEMA` defines two additive tables: `ai_spending_budgets` (owner/run composite
primary key, immutable cap/currency) and `ai_spending_attempts` (owner/run/attempt
composite key, maximum charge, pricing reference, state, final charge).
`init_schema()` is an explicit local/bootstrap seam. Production integration must
incorporate these statements into the versioned migration machinery in `store.py`
and update its schema version/checksum with that file's owner. Do not run DDL per
request or claim production readiness before that migration is reviewed.

## API

All IDs are nonblank strings of at most 512 characters. Monetary amounts are Python
integers from 0 through 2^63−1, in millionths of the budget currency (USD by default).
Floats and booleans are rejected. Convert provider decimal prices conservatively,
rounding upper bounds and final charges upward to these units. Never round down.

* `create_budget(owner_id, run_id, cap_units, currency="USD") -> dict`: idempotent
  only for the same immutable configuration. Zero cap is valid. Currency is a
  three-letter uppercase code and must match the caller's pricing currency.
* `reserve(owner_id, run_id, attempt_id, max_cost_units, pricing_ref) -> dict`:
  persists the maximum billable exposure before dispatch. Missing bounds/pricing
  raise `UnknownPricing`. Insufficient balance raises `BudgetExceeded`. Replay
  returns the existing record, including terminal state; changed bound/reference
  raises `AttemptConflict`. A reservation is not permission to send.
* `claim_dispatch(owner_id, run_id, attempt_id) -> bool`: returns True exactly once
  after commit. Only this result permits one network attempt. False on replay or a
  terminal state is never permission. Missing attempts and blocked budgets raise
  `BudgetError`. A callback adapter can translate False into an exception.
* `settle(owner_id, run_id, attempt_id, actual_cost_units) -> dict`: authoritative
  final billing only, after dispatch. Exact replay is idempotent. If actual cost
  exceeds the reserved bound, records `breached` and permanently blocks admission
  and new claims for that budget, even if its total cap has remaining room. Returns
  that state instead of raising and losing the evidence to transaction rollback.
  This is evidence that the provider-bound contract failed, not a successful cap.
* `release(owner_id, run_id, attempt_id, confirmed_not_charged=False) -> dict`:
  releases an unsent reservation. After dispatch, requires authoritative evidence
  of no charge via `confirmed_not_charged=True`; timeout/HTTP failure is insufficient.
* `mark_uncertain(owner_id, run_id, attempt_id) -> dict`: retains the full bound and
  blocks further reservations and claims for this owner/run until authoritative
  settlement or confirmed no-charge release. Holds never expire automatically.
* `snapshot(owner_id, run_id) -> dict`: cap/currency, `spent_units`, `held_units`,
  `available_units`, `blocked`, and `cost_scope="metered_provider"`. Available
  balance alone is not permission when blocked.

Run scope means the cap is for the specific owner/run pair, not an aggregate owner
account limit across runs. The integration must authenticate the owner and bind a
canonical persisted run ID; this module is not an authorization layer. Do not mint
a replacement run ID to replenish an exhausted cap for the same operation.

## Provider and retry obligations

The pricing reference identifies a server-controlled, versioned pricing snapshot.
The bound must include input, maximum output/reasoning, images, minimum fees, tools,
and any other billable dimensions applicable to that provider. Set provider limits
that enforce those maxima. Unknown dimensions, missing prices, an unbounded request,
or an expired price contract must refuse dispatch; zero is valid only when explicitly
verified free. This ledger cannot validate an arbitrary caller-supplied number.

Disable SDK hidden retries or reserve for every separately billable dispatch. Each
waterfall fallback and retry needs a fresh stable attempt ID; never reuse an ID to
send again. A known charged failure settles that charge before a fresh reservation.
An uncertain failure retains its reservation and blocks the fallback. Cached output
can reuse a terminal result outside this module; it cannot repeat provider dispatch.

A crash after claim but before send leaves a durable `dispatched` hold. A crash
after send has the same conservative treatment. Recovery must reconcile it or mark
it uncertain; it cannot redispatch or release merely because the process died.
Distributed exactly-once network delivery is not claimed. If commit acknowledgment
is lost, do not send; a replay cannot manufacture another successful claim.

## Atomicity and tests

Every decision opens one adapter cursor transaction and first updates the budget
row to itself. SQLite acquires its write lock before any read; Postgres acquires a
row lock held through commit. All ledger mutations for the same owner/run use this
lock. Reads of attempts and balance therefore occur after competing commits. No
process-local lock, post-hoc counter, or read-then-write settings API enforces the cap.
The conservation rule is `spent + held <= cap` while the supplied bounds hold.
Python integer sums avoid SQL integer overflow; a provider overrun is recorded honestly.

The tests use real existing adapters, persistence across new connections, concurrent
independent adapters, duplicate claims, invalid transitions, uncertain charges,
overruns, and a simulated transaction failure. Providers are never called.
SQLite tests run by default. To also run against a disposable local Postgres database,
set `ACP_BUDGET_TEST_PG_URL` to a localhost URL with database name `acp_budget_test`.
That opt-in fixture truncates only the two ledger tables in that dedicated database.
It must never point to production. Concurrent callers use separate connections.

Verified September 8, 2026: **30 passed** (15 cases each on SQLite and PostgreSQL
16 in a disposable local container), including a dispatch/release race and an actual
charge exceeding the entire run cap. PostgreSQL concurrency was exercised against
the real `_PgAdapter`, not a SQL mock. Transaction failure is deliberately simulated;
no live provider billing, crash-injected database process, or production database was used.

Remaining integration: versioned schema migration, authenticated run budget creation,
verified provider price/bound calculation, token/charge limits and disabled hidden
retries, dispatch callbacks, reconciliation workflow, and UI reporting that separates
metered model charges from infrastructure costs. Current tests are not end-to-end
evidence of a production cap.
