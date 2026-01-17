import inspect
from typing import Any, Callable, Dict, List

import pytest

# Contract: closed enum for Phase 2 check statuses.
STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_MISSING = "MISSING"

ALLOWED_STATUSES = {STATUS_OK, STATUS_WARN, STATUS_FAIL, STATUS_MISSING}

# Contract: deterministic precedence (worst wins).
# FAIL > MISSING > WARN > OK
PRECEDENCE = {
    STATUS_OK: 0,
    STATUS_WARN: 1,
    STATUS_MISSING: 2,
    STATUS_FAIL: 3,
}


def _find_overall_status_fn() -> Callable[..., Any]:
    """
    Locate a function that computes aggregated overall status from checks.

    Priority:
      1) validators.phase2.status_contracts.compute_overall_status  (explicit contract module)
      2) validators.phase2.master_report.<candidate>               (legacy fallback)
    """
    # 1) Preferred: explicit contract module
    try:
        import validators.phase2.status_contracts as sc  # noqa: WPS433
        fn = getattr(sc, "compute_overall_status", None)
        if callable(fn):
            return fn
    except Exception:
        # If module is missing, we still try master_report (legacy path).
        pass

    # 2) Fallback: master_report candidates (legacy)
    import validators.phase2.master_report as mr  # noqa: WPS433

    candidates = [
        "compute_overall_status",
        "derive_overall_status",
        "aggregate_overall_status",
        "overall_status_from_checks",
        "status_from_checks",
        "aggregate_status",
        "compute_status",
        "_compute_overall_status",
        "_derive_overall_status",
        "_aggregate_overall_status",
        "_overall_status_from_checks",
        "_status_from_checks",
        "_aggregate_status",
    ]

    for name in candidates:
        fn = getattr(mr, name, None)
        if callable(fn):
            return fn

    available_mr = sorted([n for n in dir(mr) if "status" in n.lower() or "aggregate" in n.lower()])
    raise AssertionError(
        "Could not find an overall-status aggregation function.\n"
        "Expected:\n"
        "  - validators.phase2.status_contracts.compute_overall_status(checks)\n"
        "or a helper inside validators.phase2.master_report.\n"
        f"master_report names containing 'status'/'aggregate' currently present: {available_mr}"
    )


def _call_overall_status_fn(fn: Callable[..., Any], checks: List[Dict[str, Any]]) -> str:
    """
    Call the discovered function with best-effort argument binding.

    We support both:
      - fn(checks) where checks is list[dict]
      - fn(statuses) where statuses is list[str]
      - fn(checks=...) / fn(check_statuses=...) / fn(statuses=...) keyword variants
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    status_list = [c["status"] for c in checks]
    param_names = {p.name for p in params}

    preferred_kw = ["checks", "check_list", "check_items", "check_results"]
    status_kw = ["statuses", "check_statuses", "status_list", "values"]

    for kw in preferred_kw:
        if kw in param_names:
            return fn(**{kw: checks})

    for kw in status_kw:
        if kw in param_names:
            return fn(**{kw: status_list})

    if len(params) == 1:
        try:
            return fn(checks)
        except Exception:
            return fn(status_list)

    try:
        return fn(checks=checks)
    except Exception:
        pass
    try:
        return fn(statuses=status_list)
    except Exception:
        pass

    raise AssertionError(
        f"Unable to call {fn.__name__} with checks/statuses. Signature: {sig}. "
        "Expected a function that accepts checks or statuses and returns overall status."
    )


def _mk_checks(*statuses: str) -> List[Dict[str, Any]]:
    return [{"id": f"check.{i}", "status": st} for i, st in enumerate(statuses)]


def _expected_overall_status(checks: List[Dict[str, Any]]) -> str:
    """
    Contract: overall_status = worst status present in checks.
    Empty checks => MISSING.
    """
    if not checks:
        return STATUS_MISSING
    worst = max((c["status"] for c in checks), key=lambda s: PRECEDENCE[s])
    return worst


@pytest.mark.parametrize(
    "statuses",
    [
        # Empty: explicit contract decision
        (),
        # Pure cases
        (STATUS_OK,),
        (STATUS_WARN,),
        (STATUS_MISSING,),
        (STATUS_FAIL,),
        # Mixed precedence
        (STATUS_OK, STATUS_OK, STATUS_OK),
        (STATUS_OK, STATUS_WARN),
        (STATUS_WARN, STATUS_OK),
        (STATUS_OK, STATUS_MISSING),
        (STATUS_MISSING, STATUS_OK),
        (STATUS_WARN, STATUS_MISSING),
        (STATUS_MISSING, STATUS_WARN),
        (STATUS_WARN, STATUS_FAIL),
        (STATUS_FAIL, STATUS_WARN),
        (STATUS_MISSING, STATUS_FAIL),
        (STATUS_FAIL, STATUS_MISSING),
        # Larger mixes
        (STATUS_OK, STATUS_WARN, STATUS_OK),
        (STATUS_OK, STATUS_WARN, STATUS_MISSING),
        (STATUS_OK, STATUS_WARN, STATUS_FAIL),
        (STATUS_OK, STATUS_MISSING, STATUS_FAIL),
        (STATUS_WARN, STATUS_MISSING, STATUS_FAIL),
    ],
)
def test_phase2_master_report_overall_status_precedence_contract(statuses: tuple) -> None:
    fn = _find_overall_status_fn()

    for st in statuses:
        assert st in ALLOWED_STATUSES

    checks = _mk_checks(*statuses)
    got = _call_overall_status_fn(fn, checks)
    exp = _expected_overall_status(checks)

    assert got in ALLOWED_STATUSES, f"overall_status must be one of {sorted(ALLOWED_STATUSES)}, got={got}"
    assert got == exp, f"overall_status precedence contract violated: got={got}, expected={exp}, statuses={list(statuses)}"


def test_phase2_master_report_overall_status_never_better_than_any_check() -> None:
    fn = _find_overall_status_fn()

    combos = [
        _mk_checks(STATUS_OK, STATUS_OK),
        _mk_checks(STATUS_OK, STATUS_WARN),
        _mk_checks(STATUS_OK, STATUS_MISSING),
        _mk_checks(STATUS_OK, STATUS_FAIL),
        _mk_checks(STATUS_WARN, STATUS_MISSING),
        _mk_checks(STATUS_WARN, STATUS_FAIL),
        _mk_checks(STATUS_MISSING, STATUS_FAIL),
    ]

    for checks in combos:
        got = _call_overall_status_fn(fn, checks)
        assert got in ALLOWED_STATUSES

        got_rank = PRECEDENCE[got]
        for c in checks:
            st = c["status"]
            assert st in ALLOWED_STATUSES
            assert got_rank >= PRECEDENCE[st], (
                "overall_status cannot be better than a child check.\n"
                f"overall={got} (rank={got_rank}) vs check={st} (rank={PRECEDENCE[st]})"
            )
