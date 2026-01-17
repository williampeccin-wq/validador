import inspect
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from validators.phase2.status_contracts import ALLOWED_STATUSES, compute_overall_status


def _write_phase1_doc(
    phase1_root: Path, case_id: str, doc_type: str, filename: str, data: Dict[str, Any]
) -> Path:
    out_dir = phase1_root / case_id / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / filename
    payload = {"data": data}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _load_report_json(phase2_root: Path, case_id: str) -> Dict[str, Any]:
    p = phase2_root / case_id / "report.json"
    assert p.exists(), f"Expected report.json at {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _assert_status_enum(value: Any, where: str) -> None:
    assert isinstance(value, str), f"{where} must be str, got={type(value)}"
    assert value in ALLOWED_STATUSES, f"{where} must be in {sorted(ALLOWED_STATUSES)}, got={value}"


def _assert_checks_shape(checks: Any) -> List[Dict[str, Any]]:
    assert isinstance(checks, list), f"checks must be a list, got={type(checks)}"
    out: List[Dict[str, Any]] = []
    for i, c in enumerate(checks):
        assert isinstance(c, dict), f"checks[{i}] must be dict, got={type(c)}"
        assert "id" in c, f"checks[{i}] missing 'id'"
        assert "status" in c, f"checks[{i}] missing 'status'"
        assert isinstance(c["id"], str) and c["id"].strip(), f"checks[{i}].id must be non-empty str"
        _assert_status_enum(c["status"], f"checks[{i}].status")
        out.append(c)
    return out


def _assert_inputs_metadata_only(inputs: Any) -> None:
    assert isinstance(inputs, dict), f"inputs must be dict, got={type(inputs)}"
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

    for k, v in inputs.items():
        assert isinstance(k, str) and k.strip(), f"inputs keys must be non-empty str; got={k!r}"
        assert isinstance(v, dict), f"inputs[{k!r}] must be dict, got={type(v)}"

        for bad in disallowed:
            assert bad not in v, f"inputs[{k!r}] must not contain '{bad}' (data leakage)"

        extra = set(v.keys()) - {"path"}
        assert not extra, f"inputs[{k!r}] contains unexpected keys: {sorted(extra)}; allowed=['path']"

        if "path" in v:
            assert isinstance(v["path"], str), f"inputs[{k!r}].path must be str, got={type(v['path'])}"


def _find_phase2_runner_fn() -> Callable[..., Any]:
    import orchestrator.phase2_runner as pr  # local import for runtime consistency

    explicit = getattr(pr, "run_phase2_proposta_cnh", None)
    if callable(explicit):
        return explicit

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

    dynamic = [n for n in dir(pr) if n.startswith("run_phase2_")]
    for name in sorted(dynamic):
        fn = getattr(pr, name, None)
        if callable(fn):
            return fn

    available = sorted([n for n in dir(pr) if "run" in n.lower() or "phase2" in n.lower() or "execute" in n.lower()])
    raise AssertionError(
        "Could not find a Phase 2 runner callable in orchestrator.phase2_runner.\n"
        "Expected a function like run_phase2_proposta_cnh(case_id, ...) or run_phase2(case_id, ...).\n"
        f"Names containing 'run'/'phase2'/'execute' present: {available}"
    )


@contextmanager
def _chdir(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _call_runner(fn: Callable[..., Any], case_id: str, phase1_root: str, phase2_root: str, tmp_path: Path) -> Any:
    """
    Robust runner invocation strategy:

    1) Try signature-based kwargs mapping (best-effort).
    2) Fallback: assume runner uses CWD-relative storage paths (storage/phase1 and storage/phase2).
       In that case, chdir(tmp_path) and call fn(case_id).
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    # Map commonly used parameter names -> values
    value_map: Dict[str, Any] = {
        "case_id": case_id,
        "cid": case_id,
        "id": case_id,
        "phase1_root": phase1_root,
        "phase2_root": phase2_root,
        "phase1_dir": phase1_root,
        "phase2_dir": phase2_root,
        "phase1_path": phase1_root,
        "phase2_path": phase2_root,
        "storage_phase1": phase1_root,
        "storage_phase2": phase2_root,
        "storage_phase1_root": phase1_root,
        "storage_phase2_root": phase2_root,
        "storage_root": str(Path(phase1_root).parent),  # .../storage
        "storage_dir": str(Path(phase1_root).parent),
        "base_dir": str(Path(phase1_root).parent),
        "root_dir": str(Path(phase1_root).parent),
    }

    # Attempt kwargs call if function has any matching named parameters
    kwargs: Dict[str, Any] = {}
    for p in params:
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.name in value_map:
            kwargs[p.name] = value_map[p.name]

    # Case: function likely takes (case_id, ...) but name isn't "case_id"
    # If first parameter exists and we didn't map it, use positional case_id.
    def _try_call_with_kwargs() -> Any:
        if not kwargs:
            raise TypeError("no-matching-kwargs")
        return fn(**kwargs)

    def _try_call_with_positional_plus_kwargs() -> Any:
        if not params:
            return fn()
        # If the first parameter is not mapped and isn't optional, pass case_id positionally.
        first = params[0]
        if first.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            if first.name not in kwargs:
                return fn(case_id, **kwargs)
        return fn(**kwargs)

    for attempt in (_try_call_with_kwargs, _try_call_with_positional_plus_kwargs):
        try:
            return attempt()
        except TypeError:
            pass

    # Fallback: CWD-relative storage pattern (common in your repo)
    # Ensure layout exists under tmp_path/storage/{phase1,phase2}
    with _chdir(tmp_path):
        # Try common call styles
        try:
            return fn(case_id)
        except TypeError:
            pass
        try:
            return fn(case_id=case_id)
        except TypeError:
            pass

    raise AssertionError(
        "Found a runner function but could not call it with supported strategies.\n"
        "Tried signature-based kwargs mapping and CWD-relative fallback (chdir(tmp_path) then fn(case_id)).\n"
        f"Function: {fn}\n"
        f"Signature: {sig}\n"
        f"Derived kwargs candidates: {sorted(kwargs.keys())}\n"
    )


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

    _assert_status_enum(payload["overall_status"], "overall_status")
    _assert_status_enum(payload["status"], "status")
    assert isinstance(payload["summary"], dict), "summary must be an object"
    assert "overall_status" in payload["summary"], "summary must include 'overall_status'"
    _assert_status_enum(payload["summary"]["overall_status"], "summary.overall_status")

    assert payload["status"] == payload["overall_status"], "root.status must equal root.overall_status"
    assert payload["status"] == payload["summary"]["overall_status"], "root.status must equal summary.overall_status"

    computed = compute_overall_status([c["status"] for c in checks])
    assert payload["overall_status"] == computed, (
        "root.overall_status must be derived from checks by contract.\n"
        f"expected(computed)={computed} got={payload['overall_status']}"
    )

    ids = [c["id"] for c in checks]
    assert len(ids) == len(set(ids)), f"check ids must be unique; duplicates found: {ids}"
