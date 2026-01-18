# tests/test_phase2_master_report_detran_rules.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from validators.phase2.master_report import build_master_report


def _write_phase1_doc(tmp_path: Path, case_id: str, doc_type: str, data: Dict[str, Any]) -> Path:
    d = tmp_path / "phase1" / case_id / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / "0001.json"
    payload = {"data": data}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _presence_min_gate1(tmp_path: Path, case_id: str) -> None:
    # Gate1: proposta_daycoval + cnh
    _write_phase1_doc(
        tmp_path,
        case_id,
        "proposta_daycoval",
        {
            "nome_financiado": "JOAO DA SILVA",
            "data_nascimento": "1990-01-01",
            # Vlr. Compra (no layout real pode variar; aqui fixamos chave estável)
            "vlr_compra": "10.000,00",
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


def _get_check(report: Dict[str, Any], check_id: str) -> Dict[str, Any]:
    for c in report.get("checks", []):
        if c.get("id") == check_id:
            return c
    raise AssertionError(f"missing check id: {check_id}")


def _ids(report: Dict[str, Any]) -> List[str]:
    return [c.get("id") for c in report.get("checks", [])]


def test_phase2_detran_emits_checks_when_detran_present(tmp_path: Path):
    case_id = "case-detran-emit"
    _presence_min_gate1(tmp_path, case_id)

    # DETRAN presente, mas com dados neutros (sem restrição, sem alienação, sem ipva)
    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "J*** S***",
            "proprietario_nome_ofuscado": True,
            "proprietario_iniciais": "JS",
            "proprietario_iniciais_tokens": ["J", "S"],
            "proprietario_doc": None,
            "proprietario_doc_ofuscado": False,
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": False,
            "debitos_total_cents": 0,
            "multas_total_cents": 0,
            "evidence": {},
        },
    )

    # ATPV presente (nome do vendedor permite match por iniciais)
    _write_phase1_doc(
        tmp_path,
        case_id,
        "atpv",
        {
            "vendedor_nome": "JOAO SILVA",
            "vendedor_cpf_cnpj": None,
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")

    # Presence
    assert "vehicle.detran.present" in _ids(report)

    # Checks DETRAN esperados
    assert "vehicle.detran.owner.matches_atpv_vendedor" in _ids(report)
    assert "vehicle.detran.restricao_administrativa.absent" in _ids(report)
    assert "vehicle.detran.alienacao_fiduciaria.inactive_or_absent" in _ids(report)
    assert "vehicle.detran.ipva.no_overdue" in _ids(report)
    assert "vehicle.detran.debitos.total_vs_valor_compra" in _ids(report)

    # Match por iniciais => WARN (evidência fraca)
    c_owner = _get_check(report, "vehicle.detran.owner.matches_atpv_vendedor")
    assert c_owner["status"] == "WARN"
    assert c_owner["evidence"].get("match_mode") == "initials"


def test_phase2_detran_owner_doc_match_is_ok(tmp_path: Path):
    case_id = "case-detran-doc-ok"
    _presence_min_gate1(tmp_path, case_id)

    # DETRAN com doc forte
    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "JOAO DA SILVA",
            "proprietario_nome_ofuscado": False,
            "proprietario_iniciais": None,
            "proprietario_iniciais_tokens": [],
            "proprietario_doc": "123.456.789-09",
            "proprietario_doc_ofuscado": False,
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": False,
            "debitos_total_cents": 0,
            "multas_total_cents": 0,
            "evidence": {},
        },
    )

    # ATPV com doc forte igual
    _write_phase1_doc(
        tmp_path,
        case_id,
        "atpv",
        {
            "vendedor_nome": "JOAO DA SILVA",
            "vendedor_cpf_cnpj": "12345678909",
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c_owner = _get_check(report, "vehicle.detran.owner.matches_atpv_vendedor")
    assert c_owner["status"] == "OK"
    assert c_owner["evidence"].get("match_mode") == "doc"


def test_phase2_detran_owner_doc_mismatch_is_fail(tmp_path: Path):
    case_id = "case-detran-doc-fail"
    _presence_min_gate1(tmp_path, case_id)

    # DETRAN doc forte
    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "JOAO DA SILVA",
            "proprietario_nome_ofuscado": False,
            "proprietario_iniciais": None,
            "proprietario_iniciais_tokens": [],
            "proprietario_doc": "111.111.111-11",
            "proprietario_doc_ofuscado": False,
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": False,
            "debitos_total_cents": 0,
            "multas_total_cents": 0,
            "evidence": {},
        },
    )

    # ATPV doc forte diferente
    _write_phase1_doc(
        tmp_path,
        case_id,
        "atpv",
        {
            "vendedor_nome": "JOAO DA SILVA",
            "vendedor_cpf_cnpj": "222.222.222-22",
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c_owner = _get_check(report, "vehicle.detran.owner.matches_atpv_vendedor")
    assert c_owner["status"] == "FAIL"
    assert c_owner["evidence"].get("match_mode") == "doc"


def test_phase2_detran_restricao_admin_fail(tmp_path: Path):
    case_id = "case-detran-restr-fail"
    _presence_min_gate1(tmp_path, case_id)

    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "J*** S***",
            "proprietario_nome_ofuscado": True,
            "proprietario_iniciais": "JS",
            "proprietario_iniciais_tokens": ["J", "S"],
            "restricao_administrativa_ativa": True,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": False,
            "debitos_total_cents": 0,
            "multas_total_cents": 0,
            "evidence": {"restricao_admin": "MENCIONA RESTRIÇÃO/BLOQUEIO"},
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c = _get_check(report, "vehicle.detran.restricao_administrativa.absent")
    assert c["status"] == "FAIL"


def test_phase2_detran_alienacao_ativa_fail(tmp_path: Path):
    case_id = "case-detran-alien-fail"
    _presence_min_gate1(tmp_path, case_id)

    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "J*** S***",
            "proprietario_nome_ofuscado": True,
            "proprietario_iniciais": "JS",
            "proprietario_iniciais_tokens": ["J", "S"],
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ativa",
            "ipva_em_atraso": False,
            "debitos_total_cents": 0,
            "multas_total_cents": 0,
            "evidence": {"alienacao": "ALIENA/GRAVAME MENCIONADO"},
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c = _get_check(report, "vehicle.detran.alienacao_fiduciaria.inactive_or_absent")
    assert c["status"] == "FAIL"


def test_phase2_detran_ipva_atraso_fail(tmp_path: Path):
    case_id = "case-detran-ipva-fail"
    _presence_min_gate1(tmp_path, case_id)

    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "J*** S***",
            "proprietario_nome_ofuscado": True,
            "proprietario_iniciais": "JS",
            "proprietario_iniciais_tokens": ["J", "S"],
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": True,
            "debitos_total_cents": 0,
            "multas_total_cents": 0,
            "evidence": {"ipva": "IPVA + (ATRASO/ABERTO/NOTIFICADO) + VALOR"},
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c = _get_check(report, "vehicle.detran.ipva.no_overdue")
    assert c["status"] == "FAIL"


def test_phase2_detran_debitos_exceed_valor_compra_fails(tmp_path: Path):
    case_id = "case-detran-debitos-fail"
    _presence_min_gate1(tmp_path, case_id)

    # Proposta: Vlr. Compra = 10.000,00 => 1_000_000 cents
    # DETRAN: debitos + multas = 12.000,00 => FAIL
    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "J*** S***",
            "proprietario_nome_ofuscado": True,
            "proprietario_iniciais": "JS",
            "proprietario_iniciais_tokens": ["J", "S"],
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": False,
            "debitos_total_cents": 1_000_000,  # 10.000,00
            "multas_total_cents": 200_000,     # 2.000,00
            "evidence": {},
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c = _get_check(report, "vehicle.detran.debitos.total_vs_valor_compra")
    assert c["status"] == "FAIL"


def test_phase2_detran_debitos_within_valor_compra_ok(tmp_path: Path):
    case_id = "case-detran-debitos-ok"
    _presence_min_gate1(tmp_path, case_id)

    # DETRAN: total 9.999,99 <= 10.000,00 => OK
    _write_phase1_doc(
        tmp_path,
        case_id,
        "detran_sc",
        {
            "proprietario_nome": "J*** S***",
            "proprietario_nome_ofuscado": True,
            "proprietario_iniciais": "JS",
            "proprietario_iniciais_tokens": ["J", "S"],
            "restricao_administrativa_ativa": False,
            "alienacao_fiduciaria_status": "ausente",
            "ipva_em_atraso": False,
            "debitos_total_cents": 900_000,  # 9.000,00
            "multas_total_cents": 99_999,    # 999,99
            "evidence": {},
        },
    )

    report = build_master_report(case_id, phase1_root=tmp_path / "phase1", phase2_root=tmp_path / "phase2")
    c = _get_check(report, "vehicle.detran.debitos.total_vs_valor_compra")
    assert c["status"] == "OK"
