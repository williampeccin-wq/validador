# tests/test_phase2_master_report_cnh_senatran_crosscheck.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from validators.phase2.master_report import build_master_report


def _write_phase1_doc(*, phase1_root: Path, case_id: str, doc_type: str, filename: str, data: Dict[str, Any]) -> Path:
    """
    Master_report lê o "latest *.json" e usa raw["data"].
    Então o mínimo compatível é:
      {"data": {...}}
    """
    d = phase1_root / case_id / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(json.dumps({"data": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _get_check_map(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in report.get("checks") or []:
        if isinstance(c, dict) and "id" in c:
            out[str(c["id"])] = c
    return out


def test_master_report_adds_cnh_senatran_checks_when_present_ok(tmp_path: Path) -> None:
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_with_cnh_senatran_ok"
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
        },
    )
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
    checks = _get_check_map(report)

    assert "identity.proposta_vs_cnh_senatran.nome" in checks
    assert "identity.proposta_vs_cnh_senatran.cpf" in checks
    assert "identity.cnh_senatran.validade" in checks
    assert "identity.cnh_senatran.categoria" in checks

    assert checks["identity.proposta_vs_cnh_senatran.nome"]["status"] == "OK"
    assert checks["identity.proposta_vs_cnh_senatran.cpf"]["status"] == "OK"
    assert checks["identity.cnh_senatran.validade"]["status"] == "OK"
    assert checks["identity.cnh_senatran.categoria"]["status"] == "OK"


def test_master_report_cnh_senatran_name_or_cpf_mismatch_warn(tmp_path: Path) -> None:
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    case_id = "case_with_cnh_senatran_warn"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="proposta_daycoval",
        filename="001.json",
        data={
            "cpf": "111.222.333-44",
            "nome_financiado": "MARIA DE SOUZA",
        },
    )
    _write_phase1_doc(
        phase1_root=phase1_root,
        case_id=case_id,
        doc_type="cnh_senatran",
        filename="001.json",
        data={
            "cpf": "99999999999",
            "nome": "MARIA DA SILVA",  # last token differs
            "validade": "2030-12-31",
            "categoria": "B",
        },
    )

    report = build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    checks = _get_check_map(report)

    assert checks["identity.proposta_vs_cnh_senatran.nome"]["status"] == "WARN"
    assert checks["identity.proposta_vs_cnh_senatran.cpf"]["status"] == "WARN"
    assert checks["identity.cnh_senatran.validade"]["status"] == "OK"
    assert checks["identity.cnh_senatran.categoria"]["status"] == "OK"
