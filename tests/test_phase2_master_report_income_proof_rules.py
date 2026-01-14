# tests/test_phase2_master_report_income_proof_rules.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from validators.phase2.master_report import build_master_report


def _write_phase1_doc(phase1_root: Path, case_id: str, doc_type: str, data: Dict[str, Any]) -> Path:
    """
    Cria um JSON minimalista no padrão Phase 1:
      storage/phase1/<case_id>/<doc_type>/<uuid_like>.json
    Apenas o campo "data" é necessário para Phase 2.
    """
    d = phase1_root / case_id / doc_type
    d.mkdir(parents=True, exist_ok=True)

    # Nome simples e determinístico; como o loader pega o "mais recente" por mtime,
    # um único arquivo por doc_type já resolve o teste.
    p = d / "0001.json"
    payload = {"data": data, "debug": {"test": True}}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _base_case_with_proposta_and_cnh(phase1_root: Path, case_id: str) -> None:
    # Proposta com renda declarada
    _write_phase1_doc(
        phase1_root,
        case_id,
        "proposta_daycoval",
        {
            "cpf": "05775072901",
            "nome_financiado": "ANDERSON SANTOS DE BARROS",
            "data_nascimento": "12/07/1987",
            "uf": "SC",
            "cidade_nascimento": "FLORIANOPOLIS",
            "salario": "6700,00",
            "outras_rendas": "0,00",
        },
    )

    # CNH mínima compatível (para não gerar MISSING nos checks Proposta↔CNH)
    _write_phase1_doc(
        phase1_root,
        case_id,
        "cnh",
        {
            "cpf": "05775072901",
            "nome": "ANDERSON SANTOS DE BARROS",
            "data_nascimento": "12/07/1987",
            "uf_nascimento": "SC",
            "cidade_nascimento": "FLORIANOPOLIS",
            "validade": "21/07/2032",
        },
    )


def _find_check(report: Dict[str, Any], check_id: str) -> Dict[str, Any]:
    for c in report.get("checks", []):
        if c.get("id") == check_id:
            return c
    raise AssertionError(f"Check id not found: {check_id}")


def test_income_missing_only_when_no_proof_docs(tmp_path: Path) -> None:
    """
    Regra:
    - Proposta existe
    - Nenhum comprovante (holerite/extrato/folha)
    => income.declared_vs_proven.minimum deve ser MISSING
    => overall_status deve ser MISSING (já que todo o resto está OK)
    """
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_income_none"

    _base_case_with_proposta_and_cnh(phase1_root, case_id)

    report_obj = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    report = json.loads((phase2_root / case_id / "report.json").read_text(encoding="utf-8"))

    chk = _find_check(report, "income.declared_vs_proven.minimum")
    assert chk["status"] == "MISSING"
    assert report["summary"]["overall_status"] == "MISSING"


def test_income_warn_when_proof_doc_present_but_unapurable(tmp_path: Path) -> None:
    """
    Regra:
    - Proposta existe
    - Existe comprovante (extrato), mas SEM campo apurado no payload
    => deve sinalizar (WARN), mas NÃO tratar como MISSING
    => overall_status deve ser WARN
    """
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_income_extrato_unapurable"

    _base_case_with_proposta_and_cnh(phase1_root, case_id)

    # Extrato presente, mas sem qualquer um dos campos esperados pelo validador de renda:
    # renda_apurada / renda_recorrente / creditos_recorrentes_total / creditos_validos_total
    _write_phase1_doc(
        phase1_root,
        case_id,
        "extrato_bancario",
        {
            "banco": "ITAU",
            "mes_referencia": "2024-06",
            # intencionalmente sem campos de renda apurada
        },
    )

    _ = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    report = json.loads((phase2_root / case_id / "report.json").read_text(encoding="utf-8"))

    chk = _find_check(report, "income.declared_vs_proven.proof")
    assert chk["status"] == "WARN"
    assert report["summary"]["overall_status"] == "WARN"


def test_income_ok_when_holerite_proves_declared(tmp_path: Path) -> None:
    """
    Regra:
    - Proposta existe
    - Holerite existe e traz total_vencimentos compatível
    => income.declared_vs_proven.total deve ser OK
    => overall_status deve ser OK
    """
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_income_holerite_ok"

    _base_case_with_proposta_and_cnh(phase1_root, case_id)

    _write_phase1_doc(
        phase1_root,
        case_id,
        "holerite",
        {
            "total_vencimentos": "6700,00",
        },
    )

    _ = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    report = json.loads((phase2_root / case_id / "report.json").read_text(encoding="utf-8"))

    chk = _find_check(report, "income.declared_vs_proven.total")
    assert chk["status"] == "OK"
    assert report["summary"]["overall_status"] == "OK"
