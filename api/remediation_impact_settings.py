"""Owner-scoped two-slider defaults and immutable execution snapshots.

The existing settings table is sufficient; compare-and-swap protects edits across tabs
and replicas. No provider secrets or global AI settings are changed here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import re
from decimal import Decimal
from datetime import datetime, timezone

DEFAULT_POLICY = {"rule_based": 2, "ai": 1, "revision": 0}


class ImpactPolicyConflict(ValueError):
    def __init__(self, current):
        super().__init__("The saved policy changed. Refresh before saving again.")
        self.current = current


def normalize_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("A remediation policy is required.")
    if 'cloud_input_strategy' in policy:
        if policy['cloud_input_strategy'] != 'automatic' or policy.get('ai_zone') != 'any' or policy.get('ai') != 1:
            raise ValueError('Automatic cloud input requires enabled Cloud AI.')
        if any(key in policy for key in ('document_wide_input_mode', 'document_wide_model_profile')):
            raise ValueError('Automatic cloud input cannot include a manual document selection.')
        from ai_model_profiles import RECOMMENDED_RUN_BUDGET_USD
        policy = {**policy, 'ai_budget_usd': policy.get('ai_budget_usd', RECOMMENDED_RUN_BUDGET_USD),
                  'document_wide_ai': True}
    result = {}
    for key, maximum in (("rule_based", 2), ("ai", 3)):
        value = policy.get(key)
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"{key} must be an integer between 0 and {maximum}.")
        result[key] = value
    if 'cloud_input_strategy' in policy:
        result['cloud_input_strategy'] = 'automatic'
    if "ai_budget_usd" in policy:
        amount = policy["ai_budget_usd"]
        if not isinstance(amount, str) or not re.fullmatch(r"\d{1,7}(?:\.\d{1,2})?", amount):
            raise ValueError("AI spending limit must be a USD amount with at most two decimal places.")
        if Decimal(amount) > Decimal("1000000"):
            raise ValueError("AI spending limit must not exceed 1,000,000 USD.")
        result["ai_budget_usd"] = format(Decimal(amount), ".2f")
    if "ai_zone" in policy:
        from ai_run_policy import _zone
        result['ai_zone'] = _zone(policy['ai_zone'])
        if 'ai_budget_usd' not in result:
            raise ValueError('An explicit processing zone requires a run spending limit.')
    if result.get('ai_zone') == 'local':
        from ai_review_policy import normalize_review_policy
        local_review = normalize_review_policy(policy.get('ai_review'))
        if policy.get('generation_chain') or local_review['enabled']:
            raise ValueError('Local-only Ollama does not permit cloud review or fallback chains.')
    if "document_wide_ai" in policy:
        value = policy['document_wide_ai']
        if type(value) is not bool:
            raise ValueError('document_wide_ai must be a boolean.')
        if value and (result['ai'] != 1 or 'ai_budget_usd' not in result):
            raise ValueError('Document-wide AI requires AI enabled and an explicit run spending limit.')
        if value and result.get('ai_zone') == 'local':
            raise ValueError('Document-wide AI is currently available only with Cloud AI. Local Ollama remains available for individual suggestions.')
        result['document_wide_ai'] = value
    if "document_wide_input_mode" in policy or "document_wide_model_profile" in policy:
        from ai_run_policy import normalize_document_input_mode, normalize_document_model_profile
        from ai_spending_budget import BudgetError
        try:
            for key, normalizer in (("document_wide_input_mode", normalize_document_input_mode),
                                    ("document_wide_model_profile", normalize_document_model_profile)):
                if key in policy:
                    result[key] = normalizer({**policy, **result},
                        positive_budget=Decimal(result.get('ai_budget_usd', '0')) > 0)
        except BudgetError as exc:
            # API policy validation uses ValueError for a 422 response; budget
            # execution keeps BudgetError so invalid queued runs still fail closed.
            raise ValueError(str(exc)) from exc
    if "auto_approve_ai" in policy:
        from ai_standing_approval import normalize
        result['auto_approve_ai'] = normalize(policy['auto_approve_ai'])
        if result['auto_approve_ai'] and (result['ai'] != 1 or 'ai_budget_usd' not in result):
            raise ValueError('Automatic approval requires AI enabled and an explicit run spending limit.')
        # The accepted run is advance user approval. AI review can remain enabled,
        # but is not an additional mandatory approval gate for this explicit choice.
    if "generation_chain" in policy:
        from ai_generation_chain import normalize_chain
        result['generation_chain'] = normalize_chain(policy['generation_chain'])
        if 'ai_budget_usd' not in result:
            raise ValueError('An explicit generation chain requires a run spending limit.')
    if "ai_review" in policy:
        from ai_review_policy import normalize_review_policy
        result["ai_review"] = normalize_review_policy(policy["ai_review"])
        if result['ai_review']['enabled'] and 'ai_budget_usd' not in result:
            raise ValueError('AI review requires an explicit run spending limit.')
    return result


def require_executable(policy):
    result = normalize_policy(policy)
    if result["ai"] > 1:
        raise ValueError("Automatic AI application is not supported by this execution service. "
                         "Choose Off or Draft for review.")
    return result


def _key(owner):
    return "remediation_impact_policy:" + hashlib.sha256(owner.encode()).hexdigest()


def read_impact_policy(store, owner):
    raw = store.get_setting(_key(owner))
    if raw is None:
        return dict(DEFAULT_POLICY)
    saved = json.loads(raw)
    return {**normalize_policy(saved), "revision": int(saved["revision"])}


def save_impact_policy(store, owner, actor, policy, expected_revision):
    selected = require_executable(policy)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("A non-negative expected_revision is required.")
    key = _key(owner)
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT value FROM app_settings WHERE key=%s", (key,))
        row = store._db.fetchone(cur)
        current = json.loads(row["value"]) if row else dict(DEFAULT_POLICY)
        if current["revision"] != expected_revision:
            # An exact retry after a lost response has already achieved its requested state.
            if normalize_policy(current) == selected:
                return {"policy": current, "duplicate": True}
            raise ImpactPolicyConflict(current)
        if row and normalize_policy(current) == selected:
            return {"policy": current, "duplicate": True}
        saved = {**selected, "revision": expected_revision + 1}
        encoded = json.dumps(saved, sort_keys=True)
        if row:
            store._db.execute(cur, "UPDATE app_settings SET value=%s WHERE key=%s AND value=%s",
                              (encoded, key, row["value"]))
        else:
            store._db.execute(cur, "INSERT INTO app_settings(key,value) VALUES(%s,%s) "
                              "ON CONFLICT(key) DO NOTHING", (key, encoded))
        if cur.rowcount != 1:
            store._db.execute(cur, "SELECT value FROM app_settings WHERE key=%s", (key,))
            latest = store._db.fetchone(cur)
            raise ImpactPolicyConflict(json.loads(latest["value"]) if latest else dict(DEFAULT_POLICY))
        store._db.execute(cur, "INSERT INTO decision_log"
                          "(id,ts,actor,action,scan_id,file,rule_id,detail) "
                          "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                          (uuid.uuid4().hex[:12], datetime.now(timezone.utc).isoformat(), actor,
                           "remediation.impact_policy.saved", None, None, None, encoded))
    return {"policy": saved, "duplicate": False}


def snapshot_impact_policy(store, owner, policy=None):
    saved = read_impact_policy(store, owner)
    selected = require_executable(saved if policy is None else policy)
    if selected.get('auto_approve_ai'):
        from ai_standing_approval import require_access
        require_access(store, owner)
    snapshot = {**selected, "revision": saved["revision"]}
    from ai_threshold_execution import seal_policy
    # Rules-only delivery must not depend on an unused AI preference's calibration.
    sealed = seal_policy(store, owner, selected.get('ai_review', {})) if selected['ai'] > 0 else None
    if sealed is not None:
        if selected['ai'] != 1 or Decimal(selected.get('ai_budget_usd', '0')) <= 0:
            raise ValueError('Automatic AI review requires AI enabled and an explicit positive run spending limit.')
        snapshot['threshold_policy'] = sealed
    canonical = json.dumps({"owner": owner, **snapshot}, sort_keys=True)
    return {**snapshot, "snapshot_id": "rip-" + hashlib.sha256(canonical.encode()).hexdigest()[:24]}
