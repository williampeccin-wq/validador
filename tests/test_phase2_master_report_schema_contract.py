import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from validators.phase2.status_contracts import ALLOWED_STATUSES, compute_overall_status


def _write_phase1_doc(phase1_root: Path, case_id: str, doc_type: str, filename: str, data: Dict[str, Any]) -> Path:
    """
    Minimal Phase 1 fixture writer that matches the convention:
      storage/phase1/<case_id>/<doc_type>/<filename>.json
    Payload shape uses {"data": ...} which Phase 2 collectors should accept.
    """
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


def _computed_overall_from_payload_checks(payload_checks: List[Dict[str, Any]]) -> str:
    statuses = [c["status"] for c in payload_checks]
    return compute_overall_status(statuses)


@pytest.mark.parametrize(
    "case_name, phase1_docs",
    [
        # 1) Empty Phase 1: should not crash; should emit report with checks array; status should be MISSING by contract (empty => MISSING)
        ("empty_phase1", []),
        # 2) Proposta only: still should emit; checks present; overall computed deterministically
        (
            "proposta_only",
            [
                ("proposta_daycoval", "p1.json", {"nome_financiado": "JOAO", "salario": "R$ 2500,00", "outras_rendas": "0"}),
            ],
        ),
        # 3) Proposta + CNH: still should emit; checks present
        (
            "proposta_cnh",
            [
                ("proposta_daycoval", "p1.json", {"nome_financiado": "JOAO DA SILVA", "data_nascimento": "01/01/1990"}),
                ("cnh", "c1.json", {"nome": "JOAO SILVA", "data_nascimento": "01/01/1990"}),
            ],
        ),
    ],
)
def test_phase2_master_report_schema_contract(tmp_path: Path, case_name: str, phase1_docs: List[Tuple[str, str, Dict[str, Any]]]) -> None:
    """
    Master report schema contract (Phase 2):
      - Must write a JSON file at <phase2_root>/<case_id>/report.json
      - Root must include:
          - checks: list[dict] with at least id/status and status enum
          - overall_status: enum
          - status: enum
          - summary.overall_status: enum
      - Invariant: status == overall_status == summary.overall_status
      - Invariant: overall_status equals compute_overall_status([check.status...])
    """
    # Arrange: isolated storage roots
    phase1_root = tmp_path / "storage" / "phase1"
    phase2_root = tmp_path / "storage" / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    # Unique case_id per scenario (deterministic)
    case_id = f"case_{case_name}"

    # Write minimal Phase 1 docs
    for doc_type, filename, data in phase1_docs:
        _write_phase1_doc(phase1_root, case_id, doc_type, filename, data)

    # Act
    from validators.phase2.master_report import build_master_report  # local import to keep test fast/isolated

    report_obj = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    assert report_obj is not None

    payload = _load_report_json(phase2_root, case_id)

    # Assert: mandatory keys at root
    assert "checks" in payload, "report root must include 'checks'"
    assert "overall_status" in payload, "report root must include 'overall_status'"
    assert "status" in payload, "report root must include 'status'"
    assert "summary" in payload, "report root must include 'summary'"

    # Assert: checks shape + enums
    checks = _assert_checks_shape(payload["checks"])

    # Assert: status enums
    _assert_status_enum(payload["overall_status"], "overall_status")
    _assert_status_enum(payload["status"], "status")

    assert isinstance(payload["summary"], dict), "summary must be an object"
    assert "overall_status" in payload["summary"], "summary must include 'overall_status'"
    _assert_status_enum(payload["summary"]["overall_status"], "summary.overall_status")

    # Invariant: all three match
    assert payload["status"] == payload["overall_status"], "root.status must equal root.overall_status"
    assert payload["status"] == payload["summary"]["overall_status"], "root.status must equal summary.overall_status"

    # Invariant: equals computed from checks
    computed = _computed_overall_from_payload_checks(checks)
    assert payload["overall_status"] == computed, (
        "root.overall_status must be derived from checks by contract.\n"
        f"expected(computed)={computed} got={payload['overall_status']}"
    )


def test_phase2_master_report_checks_ids_are_unique(tmp_path: Path) -> None:
    """
    Contract: check IDs in a report must be unique (avoid downstream ambiguity).
    """
    phase1_root = tmp_path / "storage" / "phase1"
    phase2_root = tmp_path / "storage" / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = "case_unique_ids"

    from validators.phase2.master_report import build_master_report  # local import

    build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    payload = _load_report_json(phase2_root, case_id)

    checks = _assert_checks_shape(payload["checks"])
    ids = [c["id"] for c in checks]
    assert len(ids) == len(set(ids)), f"check ids must be unique; duplicates found: {ids}"
