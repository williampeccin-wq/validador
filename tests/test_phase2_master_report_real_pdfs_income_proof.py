from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orchestrator.phase1 import collect_document, start_case
from validators.phase2.master_report import build_master_report


RUN_REAL = os.getenv("RUN_REAL_PDF_INTEGRATION", "0") == "1"


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _find_check(report: dict, check_id: str) -> dict:
    for c in report.get("checks", []) or []:
        if c.get("id") == check_id:
            return c
    raise AssertionError(f"Check id not found: {check_id}. Available: {[c.get('id') for c in (report.get('checks') or [])]}")


@pytest.mark.skipif(not RUN_REAL, reason="Set RUN_REAL_PDF_INTEGRATION=1 to run real PDF integration test.")
def test_real_pdfs_income_not_missing_when_any_proof_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Integração REAL:
      - Phase 1: PDFs reais via collect_document
      - Phase 2: master_report
    Regra validada:
      - Se existir pelo menos um comprovante (holerite/contracheque/folha e/ou extrato),
        o report NÃO pode marcar renda como MISSING por ausência total de comprovantes.
    """

    storage_root = tmp_path / "storage"
    phase1_root = storage_root / "phase1"
    phase2_root = storage_root / "phase2"

    # Habilita parsing de docs opcionais no Phase 1 (extrato/holerite/etc).
    monkeypatch.setenv("PHASE1_PARSE_OPTIONAL_DOCS", "1")

    # OCR: só habilite se o seu ambiente tiver Tesseract/Poppler OK e você quiser forçar OCR.
    # monkeypatch.setenv("PHASE1_ENABLE_OCR", "1")

    proposta_pdf = _fixture_path("andersonsantos.pdf")
    cnh_pdf = _fixture_path("CNH DIGITAL.pdf")

    # Um extrato "real" que você já tinha
    extrato_pdf = _fixture_path("extrato_itau_2024_06.pdf")

    # Seu holerite/contracheque novo (nome exatamente como está em tests/fixtures/)
    holerite_pdf = _fixture_path("contracheque_11_2025 (2).pdf")

    case_id = start_case(storage_root=storage_root)

    collect_document(case_id, str(proposta_pdf), document_type="proposta_daycoval", storage_root=storage_root)
    collect_document(case_id, str(cnh_pdf), document_type="cnh", storage_root=storage_root)

    # Comprovantes (pode ser um, outro, ou ambos)
    collect_document(case_id, str(extrato_pdf), document_type="extrato_bancario", storage_root=storage_root)
    collect_document(case_id, str(holerite_pdf), document_type="holerite", storage_root=storage_root)

    _ = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    report = _read_json(phase2_root / case_id / "report.json")

    # Sanity: inputs registram paths do Phase 1
    inputs = report.get("inputs", {}) or {}
    assert "proposta_daycoval" in inputs
    assert "cnh" in inputs

    # Como coletamos ambos comprovantes, pelo menos um deve constar nos inputs
    assert ("holerite" in inputs) or ("extrato_bancario" in inputs)

    income_check = _find_check(report, "income.declared_vs_proven.proposta_provas")

    # Regra-chave: não pode ser MISSING se há qualquer comprovante presente
    assert income_check.get("status") in {"OK", "WARN", "FAIL"}

    # Debug útil se quebrar
    if income_check.get("status") not in {"OK", "WARN", "FAIL"}:
        raise AssertionError(f"income_check: {json.dumps(income_check, ensure_ascii=False, indent=2)}")
