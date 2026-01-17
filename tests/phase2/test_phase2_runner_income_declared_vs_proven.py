from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest


def _write_phase1_doc(
    phase1_root: Path,
    case_id: str,
    doc_type: str,
    filename: str,
    data: Dict[str, Any],
) -> Path:
    p = phase1_root / case_id / doc_type
    p.mkdir(parents=True, exist_ok=True)
    out = p / filename
    out.write_text(json.dumps({"data": data}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _load_report_json(phase2_root: Path, case_id: str) -> Dict[str, Any]:
    p = phase2_root / case_id / "report.json"
    assert p.exists(), f"Expected report.json at {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _find_phase2_runner_fn() -> Callable[..., Any]:
    """
    Locate a callable in orchestrator.phase2_runner that runs Phase 2 and writes report.json.
    We allow multiple names to avoid coupling tests to one internal API.
    """
    import orchestrator.phase2_runner as pr  # local import for runtime consistency

    candidates = [
        "run_phase2",
        "run_phase2_for_case",
        "run_case",
        "run",
        "execute_phase2",
        "execute",
        "main",
        "_run_phase2",
        "_run_case",
    ]

    for name in candidates:
        fn = getattr(pr, name, None)
        if callable(fn):
            return fn

    available = sorted([n for n in dir(pr) if "run" in n.lower() or "phase2" in n.lower() or "execute" in n.lower()])
    raise AssertionError(
        "Could not find a Phase 2 runner callable in orchestrator.phase2_runner.\n"
        "Expected a function like run_phase2(case_id, phase1_root=..., phase2_root=...) that writes report.json.\n"
        f"Candidates tried: {candidates}\n"
        f"Names containing 'run'/'phase2'/'execute' present: {available}"
    )


def _call_runner(fn: Callable[..., Any], case_id: str, phase1_root: str, phase2_root: str, tmp_path: Path) -> Any:
    """
    Call runner in a flexible way:
      - Prefer signature with keyword args
      - Fall back to positional patterns if needed
      - If runner assumes CWD-relative storage/, we chdir to tmp_path where we created storage/
    """
    # Preferred keyword form
    try:
        return fn(case_id, phase1_root=phase1_root, phase2_root=phase2_root)
    except TypeError:
        pass

    # Alternate kw names
    try:
        return fn(case_id, storage_phase1=phase1_root, storage_phase2=phase2_root)
    except TypeError:
        pass

    # Some runners accept a root storage dir and derive phase1/phase2 internally
    try:
        return fn(case_id, storage_root=str(Path(phase1_root).parent))
    except TypeError:
        pass

    # Keyword-only runner: try calling with case_id kw
    try:
        return fn(case_id=case_id, phase1_root=phase1_root, phase2_root=phase2_root)
    except TypeError:
        pass

    # CWD-dependent fallback
    import os

    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        try:
            return fn(case_id)
        except TypeError:
            pass
        try:
            return fn(case_id=case_id)
        except TypeError:
            pass
    finally:
        os.chdir(cwd)

    # Positional fallback variants
    for args in [
        (case_id, phase1_root, phase2_root),
        (case_id, phase1_root),
        (case_id,),
    ]:
        try:
            return fn(*args)
        except TypeError:
            continue

    raise AssertionError(
        "Found a runner function but could not call it with supported signatures.\n"
        "Tried: (case_id, phase1_root=..., phase2_root=...), (case_id, storage_phase1=..., storage_phase2=...),\n"
        "(case_id, storage_root=...), keyword-only (case_id=...), CWD-dependent call, and positional variants.\n"
        f"Function: {fn}"
    )


def _assert_master_report_contract(payload: Dict[str, Any]) -> None:
    # Root keys (minimum expected by schema contract)
    for k in ["checks", "inputs", "summary"]:
        assert k in payload, f"Missing root key: {k}"
    assert "status" in payload or "overall_status" in payload, "Missing root status field(s)"

    # checks shape
    assert isinstance(payload["checks"], list)
    for c in payload["checks"]:
        assert isinstance(c, dict)
        assert "id" in c
        assert "status" in c

    # inputs metadata-only (no 'data' blobs)
    assert isinstance(payload["inputs"], dict)
    for doc_type, meta in payload["inputs"].items():
        assert isinstance(doc_type, str)
        assert isinstance(meta, dict)
        assert "data" not in meta, f"inputs[{doc_type}] must be metadata-only (found 'data')"

    # overall_status contract: must be one of allowed
    allowed = {"OK", "WARN", "FAIL", "MISSING"}
    if "overall_status" in payload:
        assert payload["overall_status"] in allowed
    if "status" in payload:
        assert payload["status"] in allowed


@pytest.mark.parametrize(
    "scenario, phase1_docs",
    [
        (
            "holerite_only",
            [
                ("holerite", "h1.json", {"salario_liquido": 5000}),
            ],
        ),
        (
            "extrato_only",
            [
                ("extrato_bancario", "e1.json", {"total_entradas": 5800, "total_saidas": 4294}),
            ],
        ),
        (
            "holerite_and_extrato",
            [
                ("holerite", "h1.json", {"salario_liquido": 5000}),
                ("extrato_bancario", "e1.json", {"total_entradas": 5800, "total_saidas": 4294}),
            ],
        ),
        (
            "no_income_docs",
            [],
        ),
    ],
)
def test_phase2_runner_income_writes_report_and_does_not_block(tmp_path: Path, scenario: str, phase1_docs: list) -> None:
    """
    Contract (runner canônico):
      - Runner must not block/raise
      - Must write: <phase2_root>/<case_id>/report.json
      - Report must satisfy master_report contracts (schema/status/inputs/overall_status)

    We intentionally do NOT require optional docs: absence must be represented as MISSING/WARN/OK per contracts.
    """
    storage_root = tmp_path / "storage"
    phase1_root = storage_root / "phase1"
    phase2_root = storage_root / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = f"case_runner_income_{scenario}"

    for doc_type, filename, data in phase1_docs:
        _write_phase1_doc(phase1_root, case_id, doc_type, filename, data)

    fn = _find_phase2_runner_fn()

    # Must not raise
    _call_runner(fn, case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root), tmp_path=tmp_path)

    payload = _load_report_json(phase2_root, case_id)
    _assert_master_report_contract(payload)
