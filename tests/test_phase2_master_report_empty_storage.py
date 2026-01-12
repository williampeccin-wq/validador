from __future__ import annotations

import json
from pathlib import Path

from orchestrator.phase2_runner import run_phase2_master_report


def test_phase2_master_report_with_empty_phase1_storage(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    (storage_root / "phase1").mkdir(parents=True, exist_ok=True)

    case_id = "case_empty_001"
    res = run_phase2_master_report(case_id=case_id, storage_root=storage_root)

    assert res.case_id == case_id
    assert res.report_path.exists()

    payload = json.loads(res.report_path.read_text(encoding="utf-8"))
    assert payload["case_id"] == case_id
    assert payload["summary"]["overall_status"] == "MISSING"

    checks = {c["id"]: c for c in payload.get("checks", [])}
    assert "proposta_vs_cnh.minimum" in checks
    assert "income.declared_vs_proven.minimum" in checks
