from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Union

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_MISSING = "MISSING"
STATUS_FAIL = "FAIL"

ALLOWED_STATUSES = {STATUS_OK, STATUS_WARN, STATUS_MISSING, STATUS_FAIL}

# Contract: FAIL > MISSING > WARN > OK
_PRECEDENCE = {
    STATUS_OK: 0,
    STATUS_WARN: 1,
    STATUS_MISSING: 2,
    STATUS_FAIL: 3,
}


CheckLike = Dict[str, Any]
ChecksInput = Union[Sequence[CheckLike], Sequence[str]]


def compute_overall_status(checks: ChecksInput) -> str:
    """
    Phase 2 contract: compute aggregated status from checks.

    Rules (explicit contract):
      - Allowed statuses: OK, WARN, MISSING, FAIL
      - Precedence: FAIL > MISSING > WARN > OK
      - Empty list => MISSING (defensive default)
      - Input may be:
          a) list of dicts with key 'status' (e.g. {"id": "...", "status": "OK"})
          b) list of status strings

    This function is intentionally standalone and deterministic; it must NOT depend
    on runner side-effects or document parsing state.
    """
    if not checks:
        return STATUS_MISSING

    # Determine whether this is list[dict] or list[str]
    first = checks[0]  # type: ignore[index]
    if isinstance(first, dict):
        statuses = [str(c.get("status", "")).strip() for c in checks]  # type: ignore[arg-type]
    else:
        statuses = [str(s).strip() for s in checks]  # type: ignore[arg-type]

    # Validate statuses strictly (contract)
    for st in statuses:
        if st not in ALLOWED_STATUSES:
            raise ValueError(
                f"Invalid check status: {st!r}. Allowed: {sorted(ALLOWED_STATUSES)}"
            )

    worst = max(statuses, key=lambda s: _PRECEDENCE[s])
    return worst
