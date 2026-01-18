# tests/test_phase2_master_report_real_pdfs_detran.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from parsers.detran_sc import analyze_detran_sc
from validators.phase2.master_report import build_master_report


RUN_REAL = os.environ.get("RUN_REAL_PDF_INTEGRATION") == "1"


def _write_phase1_doc(tmp_path: Path, case_id: str, doc_type: str, data: Dict[str, Any]) -> Path:
    d = tmp_path / "phase1" / case_id / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / "0001.json"
    payload = {"data": data}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _get_check(report: Dict[str, Any], check_id: str) -> Dict[str, Any]:
    for c in report.get("checks", []):
        if c.get("id") == check_id:
            return c
    raise AssertionError(f"missing check id: {check_id}")


def _fixture_or_skip(rel_path: str) -> Path:
    p = Path(rel_path)
    if not p.exists():
        pytest.skip(f"Missing fixture: {rel_path} (version it under tests/fixtures/)")
    return p


@pytest.mark.skipif(not RUN_REAL, reason="Set RUN_REAL_PDF_INTEGRATION=1 to run real PDF integration tests")
def test_real_pdf_detran_sc_despachante_owner_match_by_doc(tmp_path: Path):
    """
    Real PDF (despachante / consulta fechada):
      - DETRAN deve expor doc forte (CPF/CNPJ) ou ao menos permitir match determinístico.
      - Teste determinístico: se o PDF expuser proprietario_doc, copiamos isso para o ATPV.
      - Objetivo: provar Phase2 DETRAN em PDF real sem depender de dados pessoais fixos no repo.
    """
    case_id = "real-detran-despachante"

    pdf = _fixture_or_skip("tests/fixtures/DETRAN_SC_DESPACHANTE_01.pdf")
    detran = analyze_detran_sc(str(pdf), consulta="despachante")

    # Gate1 mínimo
    _write_phase1_doc(
        tmp_path,
        case_id,
        "proposta_daycoval",
        {
            "nome_financiado": "JOAO DA SILVA",
            "data_nascimento": "1990-01-01",
            "vlr_compra": "999.999,99",
        },
    )
    _write_phase1_doc(
        tmp_path,
        case_id,
        "cnh",
        {
            "nome": "JOAO DA SILVA",
            "data_nascimento": "1990-01-01",
        },
    )

    # DETRAN real
    _write_phase1_doc(tmp_path, case_id, "detran_sc", detran)

    proprietario_doc = detran.get("proprietario_doc")
    proprietario_nome = detran.get("proprietario_nome")

    atpv = {
        "vendedor_nome": proprietario_nome or "JOAO DA SILVA",
        "vendedor_cpf_cnpj": proprietario_doc,
    }
    _write_phase1_doc(tmp_path, case_id, "atpv", atpv)

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")

    _ = _get_check(report, "vehicle.detran.present")

    c_owner = _get_check(report, "vehicle.detran.owner.matches_atpv_vendedor")

    if proprietario_doc:
        assert c_owner["status"] == "OK"
        assert c_owner["evidence"].get("match_mode") == "doc"
    else:
        # Se não expôs doc, o validator pode cair para WARN/MISSING dependendo de nome/iniciais.
        assert c_owner["status"] in ("OK", "WARN", "MISSING")

    _ = _get_check(report, "vehicle.detran.restricao_administrativa.absent")
    _ = _get_check(report, "vehicle.detran.alienacao_fiduciaria.inactive_or_absent")
    _ = _get_check(report, "vehicle.detran.ipva.no_overdue")
    _ = _get_check(report, "vehicle.detran.debitos.total_vs_valor_compra")


@pytest.mark.skipif(not RUN_REAL, reason="Set RUN_REAL_PDF_INTEGRATION=1 to run real PDF integration tests")
def test_real_pdf_detran_sc_aberta_owner_match_is_not_fail(tmp_path: Path):
    """
    Real PDF (consulta aberta / ofuscada):
      - DETRAN não expõe doc; comparação é fraca.
      - Contrato de segurança: NUNCA FAIL por falta de dados fortes.
      - Aceitamos WARN (iniciais) OU MISSING (insuficiente), mas jamais FAIL.
    """
    case_id = "real-detran-aberta"

    pdf = _fixture_or_skip("tests/fixtures/DETRAN_SC_ABERTA_01.pdf")
    detran = analyze_detran_sc(str(pdf), consulta="aberta")

    # Gate1 mínimo
    _write_phase1_doc(
        tmp_path,
        case_id,
        "proposta_daycoval",
        {
            "nome_financiado": "JOAO DA SILVA",
            "data_nascimento": "1990-01-01",
            "vlr_compra": "999.999,99",
        },
    )
    _write_phase1_doc(
        tmp_path,
        case_id,
        "cnh",
        {
            "nome": "JOAO DA SILVA",
            "data_nascimento": "1990-01-01",
        },
    )

    # DETRAN real
    _write_phase1_doc(tmp_path, case_id, "detran_sc", detran)

    # ATPV mínimo (nome genérico; objetivo é o contrato "não falhar por falta de força")
    _write_phase1_doc(
        tmp_path,
        case_id,
        "atpv",
        {
            "vendedor_nome": "JOAO DA SILVA",
            "vendedor_cpf_cnpj": None,
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")

    _ = _get_check(report, "vehicle.detran.present")

    c_owner = _get_check(report, "vehicle.detran.owner.matches_atpv_vendedor")

    # Consulta aberta: nunca FAIL (sem doc forte)
    assert c_owner["status"] in ("WARN", "MISSING", "OK")

    # Se o validator conseguir usar iniciais, deve indicar match_mode=initials.
    if c_owner["status"] == "WARN":
        assert c_owner["evidence"].get("match_mode") == "initials"

    _ = _get_check(report, "vehicle.detran.restricao_administrativa.absent")
    _ = _get_check(report, "vehicle.detran.alienacao_fiduciaria.inactive_or_absent")
    _ = _get_check(report, "vehicle.detran.ipva.no_overdue")
    _ = _get_check(report, "vehicle.detran.debitos.total_vs_valor_compra")
