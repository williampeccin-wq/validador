# tests/test_phase2_master_report_cnh_senatran_affects_overall.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.phase2.master_report import build_master_report


def _write_phase1_doc(*, phase1_root: Path, case_id: str, doc_type: str, filename: str, data: Dict[str, Any]) -> Path:
    d = phase1_root / case_id / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(json.dumps({"data": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def test_cnh_senatran_checks_affect_overall_ok_when_all_ok(tmp_path: Path) -> None:
    """
    Contract (A):
      - CNH_SENATRAN checks are not merely informational
      - when present, they MUST influence overall_status
    This test builds a case where:
      - Gate1 is complete (proposta_daycoval + cnh)
      - Income proof exists and is extractable (holerite)
      - CNH_SENATRAN matches
    => overall_status should be OK
    """
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_overall_ok_with_senatran"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    # Proposta: declared income present so income.total can be evaluated.
    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="proposta_daycoval",
        filename="001.json",
        data={
            "cpf": "123.456.789-00",
            "nome_financiado": "JOAO DA SILVA",
            "data_nascimento": "2000-01-01",
            "salario": "5000,00",
            "outras_rendas": "0,00",
        },
    )

    # CNH (Gate1): keep identity.proposta_vs_cnh OK
    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="cnh",
        filename="001.json",
        data={
            "nome": "JOAO DA SILVA",
            "data_nascimento": "2000-01-01",
        },
    )

    # Holerite: ensures income proof is present + extractable => avoids MISSING in income checks
    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="holerite",
        filename="001.json",
        data={
            "total_vencimentos": "5200,00",
        },
    )

    # CNH SENATRAN: matches
    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="cnh_senatran",
        filename="001.json",
        data={
            "cpf": "12345678900",
            "nome": "João da Silva",
            "validade": "31/12/2030",
            "categoria": "B",
        },
    )

    report = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    assert report.get("overall_status") == "OK"


def test_cnh_senatran_mismatch_degrades_overall_to_warn(tmp_path: Path) -> None:
    """
    Same baseline as the OK case, but CNH_SENATRAN mismatches CPF/name.
    => overall_status MUST become WARN (because worst status wins).
    """
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_overall_warn_with_senatran_mismatch"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="proposta_daycoval",
        filename="001.json",
        data={
            "cpf": "123.456.789-00",
            "nome_financiado": "JOAO DA SILVA",
            "data_nascimento": "2000-01-01",
            "salario": "5000,00",
            "outras_rendas": "0,00",
        },
    )

    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="cnh",
        filename="001.json",
        data={
            "nome": "JOAO DA SILVA",
            "data_nascimento": "2000-01-01",
        },
    )

    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="holerite",
        filename="001.json",
        data={
            "total_vencimentos": "5200,00",
        },
    )

    # CNH SENATRAN: mismatch (forces WARN in at least one check)
    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="cnh_senatran",
        filename="001.json",
        data={
            "cpf": "99999999999",
            "nome": "JOAO DA SOUZA",  # last token differs vs SILVA
            "validade": "31/12/2030",
            "categoria": "B",
        },
    )

    report = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    assert report.get("overall_status") == "WARN"
