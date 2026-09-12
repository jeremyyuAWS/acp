"""Bind managed AI spending to durable, owner-scoped remediation executions."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType

from ai_spending_budget import BudgetLedger, BudgetError, AttemptConflict, _units


RUN_POLICY_SCHEMA = """CREATE TABLE IF NOT EXISTS ai_spending_run_policies (
    owner_id TEXT NOT NULL, run_id TEXT NOT NULL, scan_id TEXT NOT NULL,
    policy_json TEXT NOT NULL, PRIMARY KEY(owner_id,run_id),
    FOREIGN KEY(owner_id,run_id) REFERENCES ai_spending_budgets(owner_id,run_id))"""


# Where a run's AI may process content. `local` is the self-hosted Ollama floor only —
# providers.zone_for_url reports zone `local` for it and providers.py:442 records its
# cost as a real measured 0 — so a local-only run has nothing to meter. `any` permits the
# configured cloud waterfall. ABSENT is neither: it is the pre-field meaning of an already
# stored snapshot, which must keep normalizing to exactly the dict it did before, byte for
# byte, or persist_run_policy's immutability comparison rejects its own accepted run.
#
# `local` is now READ in the dispatch path, and the split matters. `RunContext.enabled`
# still gates the CLOUD waterfall and still requires cap_units > 0, so a zero-cap run can
# buy nothing from a vendor no matter what its zone says — that gate is untouched. What
# `local` adds is `RunContext.local_drafting`, which ai.suggest_fix reads to reach the
# keyless Ollama floor instead of deferring. Two separate permissions, deliberately: making
# `enabled` true for a zero-cap local run would have opened every cloud seam that reads it
# (managed_text_generate, managed_generate_attempts, managed_text_ready,
# ai.run_verified_remediation) to a run with no budget to answer for it.
AI_ZONES = ("local", "any")


def _zone(value):
    if type(value) is not str or value not in AI_ZONES:
        raise BudgetError("ai_zone must be either 'local' or 'any'")
    return value


def normalize_document_input_mode(snapshot, *, positive_budget):
    value = snapshot['document_wide_input_mode']
    if type(value) is not str or value not in {'extracted', 'native_pdf'}:
        raise BudgetError("document_wide_input_mode must be 'extracted' or 'native_pdf'")
    if (snapshot.get('document_wide_ai') is not True or snapshot.get('ai') != 1
            or snapshot.get('ai_zone') != 'any' or not positive_budget):
        raise BudgetError('Document input selection requires document-wide Cloud AI and a positive spending limit')
    return value



NATIVE_PDF_QUALITY_PROFILE = 'native-pdf-quality.v1'


def normalize_document_model_profile(snapshot, *, positive_budget):
    """A frozen opt-in; absence never widens an existing run's provider permission."""
    value = snapshot['document_wide_model_profile']
    if type(value) is not str or value != NATIVE_PDF_QUALITY_PROFILE:
        raise BudgetError('Unsupported document-wide model profile')
    if (snapshot.get('document_wide_ai') is not True or snapshot.get('ai') != 1
            or snapshot.get('document_wide_input_mode') != 'native_pdf'
            or snapshot.get('ai_zone') != 'any' or not positive_budget):
        raise BudgetError('The PDF quality profile requires full-PDF Cloud AI and a positive spending limit')
    return value

def normalize_run_policy(snapshot):
    """None means legacy/unmanaged; an explicit zero is managed and denies AI."""
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict):
        raise BudgetError("invalid remediation policy snapshot")
    if "ai_budget_usd" not in snapshot:
        if "document_wide_model_profile" in snapshot:
            raise BudgetError("The PDF quality profile requires a managed run spending limit")
        if "document_wide_input_mode" in snapshot:
            raise BudgetError("Document input selection requires a managed run spending limit")
        if snapshot.get("document_wide_ai"):
            raise BudgetError("Document-wide AI requires a managed run spending limit")
        if snapshot.get("auto_approve_ai"):
            raise BudgetError("Standing approval requires a managed run spending limit")
        if "generation_chain" in snapshot:
            raise BudgetError("An explicit generation chain requires a run spending limit")
        if "ai_zone" in snapshot:
            raise BudgetError("An explicit processing zone requires a run spending limit")
        return None
    amount = snapshot["ai_budget_usd"]
    if not isinstance(amount, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,12})\.[0-9]{2}", amount):
        raise BudgetError("ai_budget_usd must be a canonical two-place nonnegative USD string")
    whole, fraction = amount.split(".")
    cap = _units(int(whole) * 1_000_000 + int(fraction) * 10_000)
    ai = snapshot.get("ai")
    if type(ai) is not int or not 0 <= ai <= 3:
        raise BudgetError("AI policy level must be between zero and three")
    result = {"ai": ai, "ai_budget_usd": amount, "cap_units": cap, "currency": "USD"}
    if 'ai_zone' in snapshot:
        result['ai_zone'] = _zone(snapshot['ai_zone'])
    if 'document_wide_ai' in snapshot:
        value = snapshot['document_wide_ai']
        if type(value) is not bool or (value and ai != 1):
            raise BudgetError('Document-wide AI requires a boolean and AI enabled')
        if value and snapshot.get('ai_zone') == 'local':
            raise BudgetError('Document-wide AI is currently available only with Cloud AI. Local Ollama remains available for individual suggestions.')
        result['document_wide_ai'] = value
    if 'document_wide_input_mode' in snapshot:
        result['document_wide_input_mode'] = normalize_document_input_mode(snapshot, positive_budget=cap > 0)
    if 'document_wide_model_profile' in snapshot:
        result['document_wide_model_profile'] = normalize_document_model_profile(snapshot, positive_budget=cap > 0)
    if 'auto_approve_ai' in snapshot:
        from ai_standing_approval import normalize
        result['auto_approve_ai'] = normalize(snapshot['auto_approve_ai'])
        if result['auto_approve_ai'] and ai != 1:
            raise BudgetError('Standing approval requires AI enabled')
    if 'generation_chain' in snapshot:
        from ai_generation_chain import normalize_chain
        result['generation_chain'] = normalize_chain(snapshot['generation_chain'])
    if 'ai_review' in snapshot:
        from ai_review_policy import normalize_review_policy
        result['ai_review'] = normalize_review_policy(snapshot['ai_review'])
        # Existing accepted jobs predate family/evaluation selections. Do not add
        # keys to their canonical persisted policy and break immutable replays.
        for key in ('permitted_families', 'evaluation_versions', 'review_model'):
            if key not in snapshot['ai_review']:
                result['ai_review'].pop(key, None)
    if 'threshold_policy' in snapshot:
        if ai != 1 or cap <= 0:
            raise BudgetError('An approved threshold policy requires AI enabled and a positive run budget')
        from ai_threshold_execution import normalize_sealed_policy
        result['threshold_policy'] = normalize_sealed_policy(snapshot['threshold_policy'])
        selection = result.get('ai_review', {})
        sealed = result['threshold_policy']
        if (selection.get('mode') != 'threshold' or selection.get('enabled') is not True
                or selection.get('minimum_reliability') != sealed['minimum_reliability']
                or set(selection.get('permitted_families', [])) != set(sealed['families'])
                or selection.get('evaluation_versions') != {family:binding['evaluation_version'] for family,binding in sealed['families'].items()}):
            raise BudgetError('Selected AI policy does not match its approved threshold snapshot')
    return result


def persist_run_policy(db, cur, owner_id, scan_id, run_id, policy):
    """Internal transaction seam: caller already owns canonical DB execution identity."""
    if policy is None:
        db.execute(cur, "SELECT run_id FROM ai_spending_run_policies WHERE owner_id=%s AND run_id=%s",
                   (owner_id, run_id))
        if db.fetchone(cur):
            raise AttemptConflict("an accepted managed run cannot become legacy")
        return
    if not all(isinstance(v, str) and v.strip() for v in (owner_id, scan_id, run_id)):
        raise BudgetError("managed AI requires a canonical owner, scan and run")
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    # INSERT locks a conflicting budget before reading it on either DB. Policy and
    # budget commit together with the jobs; no lazy settings snapshot can replenish it.
    db.execute(cur, """INSERT INTO ai_spending_budgets(owner_id,run_id,cap_units,currency)
        VALUES(%s,%s,%s,%s) ON CONFLICT(owner_id,run_id) DO NOTHING""",
        (owner_id, run_id, policy["cap_units"], policy["currency"]))
    db.execute(cur, """SELECT cap_units,currency FROM ai_spending_budgets
        WHERE owner_id=%s AND run_id=%s""", (owner_id, run_id))
    budget = db.fetchone(cur)
    if (budget["cap_units"], budget["currency"]) != (policy["cap_units"], policy["currency"]):
        raise AttemptConflict("the accepted run budget is immutable")
    db.execute(cur, """INSERT INTO ai_spending_run_policies(owner_id,run_id,scan_id,policy_json)
        VALUES(%s,%s,%s,%s) ON CONFLICT(owner_id,run_id) DO NOTHING""",
        (owner_id, run_id, scan_id, encoded))
    db.execute(cur, """SELECT scan_id,policy_json FROM ai_spending_run_policies
        WHERE owner_id=%s AND run_id=%s""", (owner_id, run_id))
    row = db.fetchone(cur)
    if row != {"scan_id": scan_id, "policy_json": encoded}:
        raise AttemptConflict("the accepted run AI policy is immutable")


def persist_payload_policy(db, cur, owner_id, scan_id, run_id, payloads):
    """Called inside enqueue's commit boundary, before any jobs are exposed."""
    policies = [normalize_run_policy(p.get("remediation_impact_policy")) for p in payloads]
    if not policies:
        return
    if any(policy != policies[0] for policy in policies):
        raise BudgetError("all files in an AI run must use the same spending policy")
    persist_run_policy(db, cur, owner_id, scan_id, run_id, policies[0])


@dataclass(frozen=True)
class RunContext:
    ledger: BudgetLedger
    owner_id: str
    scan_id: str
    run_id: str
    policy: MappingProxyType
    deferred: list[dict] = field(default_factory=list)
    file: str = ""

    @property
    def enabled(self):
        """Cloud spending needs AI, a positive cap, and a zone permitting cloud."""
        return self.policy["ai"] > 0 and self.policy["cap_units"] > 0 and self.policy.get("ai_zone") != "local"

    @property
    def local_drafting(self):
        """May this run draft on the keyless local floor.

        True only for an explicitly local-zone run. There is nothing to meter — providers.py
        records the Ollama call's cost as a real measured 0 — so the cap that guards cloud
        spending has nothing to guard here, and requiring one demanded a spending limit the
        run could never spend. Deliberately NOT true for a zone-absent run: absent is the
        pre-field meaning of an already-stored snapshot, and reading it as consent to a
        different dispatch path would change what an accepted run agreed to."""
        return self.policy["ai"] > 0 and self.policy.get("ai_zone") == "local"


_CURRENT = ContextVar("managed_ai_run", default=None)


def current_run_context(*, required=True):
    context = _CURRENT.get()
    if context is None and required:
        raise BudgetError("no managed AI run context")
    return context


def optional_current_run_context():
    return current_run_context(required=False)


def read_run_budget(store, owner_id, scan_id, run_id):
    """Owner/scan-scoped status for API callers; None means no managed budget."""
    db = store._db
    with db.cursor() as cur:
        db.execute(cur, """SELECT p.policy_json FROM ai_spending_run_policies p
            JOIN scan_runs s ON s.id=p.scan_id AND s.owner_email=p.owner_id
            JOIN stage_executions e ON e.execution_id=p.run_id AND e.scan_id=p.scan_id
                AND e.owner_email=p.owner_id
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s""",
            (owner_id, scan_id, run_id))
        row = db.fetchone(cur)
    if row is None:
        return None
    return {**BudgetLedger(db).snapshot(owner_id, run_id), "policy": json.loads(row["policy_json"])}


@contextmanager
def run_context(store, payload, job):
    """Authenticate persisted job identity, then install a task-local managed context.

    Legacy jobs without an explicit cap yield None. Supplied policy/owner never
    overrides durable job data. The wrapper belongs around the entire handler so
    legacy proposers cannot silently bypass strict dispatch while it is managed.
    """
    if not job.get("id"):
        if normalize_run_policy(payload.get("remediation_impact_policy")) is not None:
            raise BudgetError("managed AI requires a durable job ID")
        token = _CURRENT.set(None)
        try:
            yield None
        finally:
            _CURRENT.reset(token)
        return
    db = store._db
    ledger = BudgetLedger(db)
    ledger._standalone()
    with db.cursor() as cur:
        db.execute(cur, """SELECT j.payload,j.scan_id,j.batch_id,j.type,
            s.owner_email,e.owner_email AS execution_owner,e.stage
            FROM jobs j JOIN scan_runs s ON s.id=j.scan_id
            JOIN stage_executions e ON e.execution_id=j.batch_id AND e.scan_id=j.scan_id
            WHERE j.id=%s""", (job.get("id"),))
        row = db.fetchone(cur)
        if row is None:
            # A legacy job can predate stage_executions. Never grant managed
            # permission without the authenticated join, even if payload asks for it.
            if normalize_run_policy(payload.get("remediation_impact_policy")) is not None:
                raise BudgetError("managed AI job has no canonical execution")
            context = None
        else:
            durable = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            policy = normalize_run_policy(durable.get("remediation_impact_policy"))
            if policy is None:
                persist_run_policy(db, cur, row["owner_email"], row["scan_id"], row["batch_id"], None)
                if normalize_run_policy(payload.get("remediation_impact_policy")) is not None:
                    raise BudgetError("caller cannot add a budget to an accepted legacy job")
                context = None
            else:
                if (row["owner_email"] != row["execution_owner"]
                        or row["owner_email"] != durable.get("owner")
                        or row["scan_id"] != payload.get("scan_id")
                        or row["batch_id"] != durable.get("stage_execution_id")
                        or row["stage"] != "remediate" or row["type"] != "remediate_file"
                        or payload.get("file") != durable.get("file")
                        or payload.get("owner") != row["owner_email"]
                        or normalize_run_policy(payload.get("remediation_impact_policy")) != policy):
                    raise BudgetError("managed AI job identity or policy does not match durable execution")
                # Supports managed jobs queued before the schema rollout. The
                # source is their durable snapshot, never the current user default.
                persist_run_policy(db, cur, row["owner_email"], row["scan_id"], row["batch_id"], policy)
                context = RunContext(ledger, row["owner_email"], row["scan_id"], row["batch_id"],
                                     MappingProxyType(policy), file=durable.get("file", ""))
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
