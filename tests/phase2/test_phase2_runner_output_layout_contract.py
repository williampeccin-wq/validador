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
    """
    Writes a Phase 1 JSON doc in the canonical layout:
      <phase1_root>/<case_id>/<doc_type>/<filename>

    Payload shape matches existing Phase2 runner tests: {"data": {...}}
    """
    p = phase1_root / case_id / doc_type
    p.mkdir(parents=True, exist_ok=True)
    out = p / filename
    out.write_text(json.dumps({"data": data}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _find_phase2_runner_fn() -> Callable[..., Any]:
    """
    Locate a callable in orchestrator.phase2_runner that runs Phase 2 and writes report.json.
    We allow multiple names to avoid coupling this test to one internal API.
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
        "Tried keyword args, storage_root, keyword-only, CWD-dependent call, and positional variants.\n"
        f"Function: {fn}"
    )


def _assert_output_layout(phase2_root: Path, case_id: str) -> None:
    """
    Output layout contract:

      Required:
        - <phase2_root>/<case_id>/report.json

      Optional:
        - <phase2_root>/<case_id>/reports/*.json

      Forbidden:
        - any other *.json under <phase2_root>/<case_id>, outside report.json and reports/*.json
    """
    case_dir = phase2_root / case_id
    assert case_dir.exists(), f"Expected case dir to exist: {case_dir}"

    required = case_dir / "report.json"
    assert required.exists(), f"Expected canonical report.json at {required}"

    all_json = sorted(case_dir.rglob("*.json"))

    allowed: set[Path] = {required}

    reports_dir = case_dir / "reports"
    if reports_dir.exists():
        for p in sorted(reports_dir.glob("*.json")):
            allowed.add(p)

    forbidden = [p for p in all_json if p not in allowed]
    assert not forbidden, (
        "Output layout violation: found unexpected JSON files under phase2/<case_id>.\n"
        "Allowed:\n"
        f"  - {required.relative_to(case_dir)}\n"
        "  - reports/*.json (optional)\n"
        "Forbidden found:\n"
        + "\n".join([f"  - {p.relative_to(case_dir)}" for p in forbidden])
    )


@pytest.mark.parametrize(
    "scenario, phase1_docs",
    [
        (
            "gate1_minimal",
            [
                ("proposta_daycoval", "p1.json", {"nome_financiado": "JOAO DA SILVA", "data_nascimento": "01/01/1990"}),
                ("cnh", "c1.json", {"nome": "JOAO SILVA", "data_nascimento": "01/01/1990"}),
            ],
        ),
        (
            "income_only",
            [
                ("holerite", "h1.json", {"salario_liquido": 5000}),
            ],
        ),
        (
            "empty_phase1",
            [],
        ),
    ],
)
def test_phase2_runner_output_layout_contract(tmp_path: Path, scenario: str, phase1_docs: list) -> None:
    """
    This is a pure output-layout contract.
    It does NOT validate business semantics beyond the existence of report.json and layout constraints.

    Must remain stable even as we add new checks or legacy reports.
    """
    storage_root = tmp_path / "storage"
    phase1_root = storage_root / "phase1"
    phase2_root = storage_root / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = f"case_layout_{scenario}"

    for doc_type, filename, data in phase1_docs:
        _write_phase1_doc(phase1_root, case_id, doc_type, filename, data)

    fn = _find_phase2_runner_fn()

    # Must not raise
    _call_runner(fn, case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root), tmp_path=tmp_path)

    # Must satisfy layout contract
    _assert_output_layout(phase2_root, case_id)
