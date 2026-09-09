"""Run-snapshotted review preferences; generic text never authorizes a writer."""
from ai_threshold_execution import normalize_selection, capability_summary

DEFAULT = normalize_selection(None)


def normalize_review_policy(value):
    return normalize_selection(value)


def approval_gate(policy, *, review, estimate, validation, proposal_sha256,
                  source_revision, supported=False, administrator_floor=None):
    """Legacy generic drafting seam, retained as strictly draft-for-review.

    Scalar estimates and raw-text review hashes cannot establish structured proposal
    eligibility. Registered exact-version adapters use evaluate_run_policy and the
    controlled dispatch in ai_threshold_execution instead.
    """
    selected = normalize_review_policy(policy)
    reason = ('review_all_selected' if selected['mode'] != 'threshold' else
              'automatic_application_not_supported_for_this_change')
    return {'approval_required':True,'approval_kind':None,'reason':reason,
            'status':'awaiting_human_review',
            'checks':[{'gate':'registered_controlled_writer','passed':False}],
            'minimum_reliability':selected['minimum_reliability']}


def capabilities(store=None, owner=None):
    return capability_summary(store, owner)
