# tests/phase2/test_phase2_runner_income_declared_vs_proven.py
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.phase1 import start_case, collect_document
from orchestrator.phase2_runner import run_phase2_income_declared_vs_proven


def test_phase2_runner_income_writes_report_and_does_not_block(tmp_path: Path):
    """
    Runner deve:
    - ler proposta persistida na phase1
    - gerar relatório mesmo sem holerite/folha/extrato
    - escrever report em phase2
    """
    # usa storage isolado para o teste
    storage_root = tmp_path / "storage"

    case_id = start_case(storage_root=str(storage_root / "phase1"))
    collect_document(
        case_id,
        "tests/fixtures/andersonsantos.pdf",
        document_type="proposta_daycoval",
        storage_root=str(storage_root / "phase1"),
    )

    res = run_phase2_income_declared_vs_proven(case_id=case_id, storage_root=storage_root, write_report=True)

    assert res.case_id == case_id
    assert res.proposta_json_path is not None
    assert res.report_path is not None
    assert res.report_path.exists()

    payload = json.loads(res.report_path.read_text(encoding="utf-8"))
    assert payload["validator"] == "income_declared_vs_proven"
    assert payload["case_id"] == case_id

    # sem docs comprovantes, deve acusar proven_missing
    assert payload["summary"]["declared_present"] is True
    assert payload["summary"]["proven_present"] is False
    assert payload["summary"]["status"] == "proven_missing"
