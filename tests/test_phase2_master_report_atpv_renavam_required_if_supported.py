# tests/test_phase2_master_report_atpv_renavam_required_if_supported.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.phase2.master_report import build_master_report


def _write_phase1_doc(case_root: Path, doc_type: str, payload: Dict[str, Any], name: str = "0001.json") -> Path:
    d = case_root / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"data": payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _mk_case_roots(tmp_path: Path) -> Dict[str, Path | str]:
    case_id = "case-atpv-renavam-hard-001"
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    phase1_case_root = phase1_root / case_id
    phase2_case_root = phase2_root / case_id
    phase1_case_root.mkdir(parents=True, exist_ok=True)
    phase2_case_root.mkdir(parents=True, exist_ok=True)
    return {"case_id": case_id, "phase1_root": phase1_root, "phase2_root": phase2_root, "phase1_case_root": phase1_case_root}


def _find_check(report: dict, check_id: str) -> dict:
    checks = report.get("checks") or []
    for c in checks:
        if c.get("id") == check_id:
            return c
    raise AssertionError(f"Check not found: {check_id}")


def _neutralize_income_to_ok(phase1_case: Path) -> None:
    proposta_payload = {"cpf": "11144477735", "nome_financiado": "MARIA IVONE FIGLERSKI", "salario": "R$ 9000,00"}
    _write_phase1_doc(phase1_case, "proposta_daycoval", proposta_payload)

    holerite_payload = {"total_vencimentos": "R$ 10.000,00"}
    _write_phase1_doc(phase1_case, "holerite", holerite_payload)


def _find_valid_renavam(base10_digits: str) -> str:
    """
    Gera um RENAVAM 11 válido sem assumir o algoritmo (usa o validador oficial do projeto).
    base10_digits deve ter 10 dígitos.
    """
    assert len(base10_digits) == 10 and base10_digits.isdigit()
    for last in "0123456789":
        candidate = base10_digits + last
        if _is_valid_renavam_11(candidate):
            return candidate
    raise AssertionError("Could not find a valid RENAVAM for the given base10 prefix")


def test_required_if_supported_emits_fail_and_degrades_overall(tmp_path: Path) -> None:
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    # Gate1 required docs (minimal)
    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})
    _neutralize_income_to_ok(phase1_case)

    # Doc correlato presente (suporta exigir RENAVAM)
    vehicle_ren = _find_valid_renavam("1234567890")
    _write_phase1_doc(phase1_case, "crlv_e", {"placa": "ASY6E68", "chassi": "9BD118181B1126184", "renavam": vehicle_ren})

    # ATPV sem RENAVAM => FAIL
    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",  # match proposta -> Policy A OK
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
            "renavam": None,
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]

    chk = _find_check(report, "vehicle.atpv.renavam.required_if_supported")
    assert chk["status"] == "FAIL"
    assert report.get("overall_status") == "FAIL"
    assert (report.get("summary") or {}).get("overall_status") == "FAIL"

    # Policy A continua existindo (não pode sumir)
    assert _find_check(report, "vehicle.atpv.comprador.matches_proposta")["status"] == "OK"


def test_renavam_crosscheck_mismatch_fails_when_both_valid(tmp_path: Path) -> None:
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})
    _neutralize_income_to_ok(phase1_case)

    vehicle_ren = _find_valid_renavam("1234567890")
    atpv_ren = _find_valid_renavam("9876543210")
    assert vehicle_ren != atpv_ren

    _write_phase1_doc(phase1_case, "crlv_e", {"placa": "ASY6E68", "chassi": "9BD118181B1126184", "renavam": vehicle_ren})

    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "renavam": atpv_ren,
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]

    chk = _find_check(report, "vehicle.atpv.renavam.matches_vehicle_doc")
    assert chk["status"] == "FAIL"
    assert report.get("overall_status") == "FAIL"
    assert (report.get("summary") or {}).get("overall_status") == "FAIL"
