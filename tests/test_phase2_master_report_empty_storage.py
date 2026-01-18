# tests/test_phase2_master_report_empty_storage.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.phase2.master_report import build_master_report


def test_phase2_master_report_with_empty_phase1_storage(tmp_path: Path) -> None:
    """
    Contrato do master_report:
    - Mesmo com Phase 1 vazio (sem pasta do case, sem docs), o master_report deve:
      - ser gerado sem exceção
      - escrever phase2/<case_id>/report.json
      - conter "checks" como lista
      - conter um status agregado (normalmente "status"; tolera "overall_status")
    """

    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_empty_phase1_storage"

    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    _ = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))

    report_path = phase2_root / case_id / "report.json"
    assert report_path.exists(), f"report.json não foi criado em: {report_path}"

    report: Dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))

    assert report.get("case_id") == case_id

    # master_report usa "status" hoje; toleramos "overall_status" caso evolua/normalize.
    agg_status = report.get("status", report.get("overall_status"))
    assert agg_status is not None, "Report não contém status agregado ('status' ou 'overall_status')"

    assert agg_status in {"OK", "WARN", "MISSING", "ERROR"}, f"status agregado inesperado: {agg_status}"

    checks = report.get("checks", [])
    assert isinstance(checks, list)

    # opcional: garante que cada item tem id/status (contrato mínimo)
    for c in checks:
        assert isinstance(c, dict)
        assert "id" in c
        assert "status" in c
