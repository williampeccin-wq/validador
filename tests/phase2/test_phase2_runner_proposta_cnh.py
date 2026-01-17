from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _write_phase1_doc(phase1_root: Path, case_id: str, doc_type: str, filename: str, data: Dict[str, Any]) -> Path:
    """
    Write a minimal Phase 1 document JSON in the canonical layout:
      <phase1_root>/<case_id>/<doc_type>/<filename>.json
    """
    d = phase1_root / case_id / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    payload = {"data": data}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _load_report_json(phase2_root: Path, case_id: str) -> Dict[str, Any]:
    """
    Canonical Phase 2 runner output contract: report.json at:
      <phase2_root>/<case_id>/report.json
    """
    p = phase2_root / case_id / "report.json"
    assert p.exists(), f"Expected report.json at {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _assert_checks_shape(checks: Any) -> List[Dict[str, Any]]:
    assert isinstance(checks, list), f"checks must be list, got={type(checks)}"
    for i, c in enumerate(checks):
        assert isinstance(c, dict), f"checks[{i}] must be dict, got={type(c)}"
        assert isinstance(c.get("id"), str) and c["id"].strip(), f"checks[{i}].id must be non-empty str"
        assert isinstance(c.get("status"), str) and c["status"].strip(), f"checks[{i}].status must be non-empty str"
    return checks


def _assert_inputs_metadata_only(inputs: Any) -> None:
    """
    Inputs must be metadata-only (no data leakage).
    Accept both shapes:
      - canonical: {"docs": {"proposta_daycoval": {"present": True, "path": "..."}, ...}}
      - flat: {"proposta_daycoval": {"path": "..."}, ...}
    """
    assert isinstance(inputs, dict), f"inputs must be dict, got={type(inputs)}"

    # Canonical wrapper
    if "docs" in inputs and isinstance(inputs["docs"], dict):
        inputs = inputs["docs"]

    assert isinstance(inputs, dict), f"inputs/docs must be dict, got={type(inputs)}"

    disallowed = {
        "data",
        "payload",
        "content",
        "text",
        "raw_text",
        "native_text",
        "ocr_text",
        "fields",
        "parsed",
        "extracted",
        "document",
        "doc",
    }
    allowed_keys = {"path", "present"}

    for k, v in inputs.items():
        assert isinstance(k, str) and k.strip(), f"inputs keys must be non-empty str; got={k!r}"
        assert isinstance(v, dict), f"inputs[{k!r}] must be dict, got={type(v)}"

        for bad in disallowed:
            assert bad not in v, f"inputs[{k!r}] must not contain '{bad}' (data leakage)"

        extra = set(v.keys()) - allowed_keys
        assert not extra, (
            f"inputs[{k!r}] contains unexpected keys: {sorted(extra)}; "
            f"allowed={sorted(allowed_keys)}"
        )

        # If present=True, require a non-empty path string
        if v.get("present") is True:
            assert isinstance(v.get("path"), str) and v["path"].strip(), (
                f"inputs[{k!r}].path must be non-empty when present=True"
            )


def _find_phase2_runner_fn() -> Callable[..., Any]:
    """
    Locate a callable in orchestrator.phase2_runner that runs Phase 2 and writes report.json.

    Preference order:
      1) run_phase2 (canonical runner introduced to satisfy master_report contracts)
      2) execute_phase2 / run_case variants (if present)
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

    available = sorted(
        [n for n in dir(pr) if "run" in n.lower() or "phase2" in n.lower() or "execute" in n.lower()]
    )
    raise AssertionError(
        "Could not find a Phase 2 runner callable in orchestrator.phase2_runner.\n"
        "Expected a function like run_phase2(case_id=..., ...) that writes report.json.\n"
        f"Candidates tried: {candidates}\n"
        f"Names containing 'run'/'phase2'/'execute' present: {available}"
    )


def _call_runner(
    fn: Callable[..., Any],
    case_id: str,
    phase1_root: str,
    phase2_root: str,
    tmp_path: Path,
) -> Any:
    """
    Call runner in a flexible way across possible API shapes.

    Supported patterns (in order):
      - fn(case_id=..., storage_root=Path("..."), write_report=True)
      - fn(case_id=..., storage_root="...", write_report=True)
      - fn(case_id=..., phase1_root="...", phase2_root="...", write_report=True)
      - fn(case_id, phase1_root=..., phase2_root=...)
      - positional fallbacks

    Also supports runners that assume CWD-relative "storage/phase1" + "storage/phase2":
      - if needed, chdir into tmp_path (which contains storage/) for the call, then restore.
    """
    storage_root = Path(phase1_root).parent  # .../storage
    assert storage_root.name == "storage", f"expected phase1_root under storage/, got {phase1_root}"

    sig = None
    try:
        sig = inspect.signature(fn)
    except Exception:
        sig = None

    def _try_call(**kwargs: Any) -> Optional[Any]:
        try:
            return fn(**kwargs)
        except TypeError:
            return None

    cwd_before = Path.cwd()
    try:
        # First, try modern canonical signature with storage_root + case_id kw-only
        out = _try_call(case_id=case_id, storage_root=storage_root, write_report=True)
        if out is not None:
            return out

        out = _try_call(case_id=case_id, storage_root=str(storage_root), write_report=True)
        if out is not None:
            return out

        # Some variants might accept phase1_root/phase2_root directly
        out = _try_call(case_id=case_id, phase1_root=phase1_root, phase2_root=phase2_root, write_report=True)
        if out is not None:
            return out

        # If runner is positional, try typical patterns
        try:
            return fn(case_id, phase1_root=phase1_root, phase2_root=phase2_root)
        except TypeError:
            pass

        # As a last resort, switch CWD to tmp_path and call with no roots
        os.chdir(tmp_path)
        out = _try_call(case_id=case_id, write_report=True)
        if out is not None:
            return out

        # Positional fallbacks in CWD mode
        for args in [
            (case_id,),
            (case_id, str(storage_root)),
            (case_id, phase1_root, phase2_root),
        ]:
            try:
                return fn(*args)
            except TypeError:
                continue

        raise AssertionError(
            "Found a runner function but could not call it with supported signatures.\n"
            "Tried keyword patterns with (case_id, storage_root, write_report), (case_id, phase1_root, phase2_root),\n"
            "and CWD-relative call. Also tried positional variants.\n"
            f"Function: {fn}\n"
            f"Signature (best-effort): {sig}"
        )
    finally:
        os.chdir(cwd_before)


def _compute_overall_status_from_checks(checks: List[Dict[str, Any]]) -> str:
    """
    Use the canonical status aggregation contract if available; otherwise apply the agreed precedence:
      FAIL > MISSING > WARN > OK
    """
    statuses = [str(c.get("status", "")).strip() for c in checks if str(c.get("status", "")).strip()]
    try:
        from validators.phase2.status_contracts import compute_overall_status  # canonical

        return compute_overall_status(statuses)
    except Exception:
        precedence = {"FAIL": 0, "MISSING": 1, "WARN": 2, "OK": 3}
        worst = "OK"
        for s in statuses:
            if s not in precedence:
                continue
            if precedence[s] < precedence[worst]:
                worst = s
        return worst


def test_phase2_runner_writes_report_and_does_not_block(tmp_path: Path) -> None:
    # IMPORTANT: build a layout that supports BOTH styles:
    # - explicit roots passed to runner
    # - runner assuming CWD-relative "storage/phase1" + "storage/phase2"
    storage_root = tmp_path / "storage"
    phase1_root = storage_root / "phase1"
    phase2_root = storage_root / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = "case_runner_proposta_cnh"

    # Minimal Gate 1 docs for proposta_vs_cnh scenario
    _write_phase1_doc(
        phase1_root,
        case_id,
        "proposta_daycoval",
        "p1.json",
        {
            "nome_financiado": "JOAO DA SILVA",
            "data_nascimento": "01/01/1990",
            "uf": "SC",
            "cidade_nascimento": "FLORIANOPOLIS",
        },
    )
    _write_phase1_doc(
        phase1_root,
        case_id,
        "cnh",
        "c1.json",
        {
            "nome": "JOAO SILVA",
            "data_nascimento": "01/01/1990",
            "uf_nascimento": "SC",
            "cidade_nascimento": "FLORIANOPOLIS",
        },
    )

    fn = _find_phase2_runner_fn()

    # Must not raise
    _call_runner(
        fn,
        case_id,
        phase1_root=str(phase1_root),
        phase2_root=str(phase2_root),
        tmp_path=tmp_path,
    )

    payload = _load_report_json(phase2_root, case_id)

    # Root schema must be present
    assert "checks" in payload, "report root must include 'checks'"
    assert "inputs" in payload, "report root must include 'inputs'"
    assert "summary" in payload, "report root must include 'summary'"
    assert "overall_status" in payload, "report root must include 'overall_status'"
    assert "status" in payload, "report root must include 'status'"

    checks = _assert_checks_shape(payload["checks"])
    assert len(checks) > 0, "report must include at least one check"

    _assert_inputs_metadata_only(payload["inputs"])

    # overall_status must be derived from checks via the canonical aggregation contract
    expected_overall = _compute_overall_status_from_checks(checks)
    assert payload["overall_status"] == expected_overall, (
        "overall_status must equal compute_overall_status(check.statuses)\n"
        f"expected={expected_overall} got={payload['overall_status']}"
    )

    # status should not contradict overall_status (allow exact equality; if you later evolve semantics,
    # update this contract explicitly)
    assert payload["status"] == payload["overall_status"], (
        "status must match overall_status (single authoritative aggregate for now)\n"
        f"status={payload['status']} overall_status={payload['overall_status']}"
    )
