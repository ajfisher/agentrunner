from __future__ import annotations

REPAIRABLE_CLASSIFICATION = 'repairable'
TERMINAL_CLASSIFICATION = 'terminal'

REPAIRABLE_KIND_NON_FAST_FORWARD = 'non_fast_forward'
REPAIRABLE_KIND_TARGET_BRANCH_MISSING = 'target_branch_missing'

MVP_REPAIRABLE_BLOCKER_KINDS = frozenset({
    REPAIRABLE_KIND_NON_FAST_FORWARD,
    REPAIRABLE_KIND_TARGET_BRANCH_MISSING,
})
VALID_CLASSIFICATIONS = frozenset({REPAIRABLE_CLASSIFICATION, TERMINAL_CLASSIFICATION})


def merge_blocker_is_mvp_repairable(blocker: object) -> bool:
    if not isinstance(blocker, dict):
        return False
    return (
        blocker.get('classification') == REPAIRABLE_CLASSIFICATION
        and blocker.get('kind') in MVP_REPAIRABLE_BLOCKER_KINDS
    )


def merger_result_uses_mvp_repairable_passback(result: object, *, target_role: str | None = None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get('status') != 'blocked' or result.get('merged') is not False:
        return False
    blocker = result.get('mergeBlocker')
    if not merge_blocker_is_mvp_repairable(blocker):
        return False
    if target_role is None:
        return True
    passback = blocker.get('passback') if isinstance(blocker, dict) else None
    return isinstance(passback, dict) and passback.get('targetRole') == target_role
