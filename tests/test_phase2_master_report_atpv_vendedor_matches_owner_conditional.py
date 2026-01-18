# tests/test_phase2_master_report_atpv_vendedor_matches_owner_conditional.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.atpv import _is_valid_cnpj as _is_valid_cnpj  # type: ignore
from validators.atpv import _is_valid_cpf as _is_valid_cpf  # type: ignore
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.phase2.master_report import build_master_report


def _write_phase1_doc(case_root: Path, doc_type: str, payload: Dict[str, Any], name: str = "0001.json") -> Path:
    d = case_root / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"data": payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _mk_case_roots(tmp_path: Path) -> Dict[str, Path | str]:
    case_id = "case-atpv-vendedor-owner-001"
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
    """Evita que checks de renda (Phase2) dominem o overall_status dos testes de ATPV."""
    proposta_payload = {"cpf": "11144477735", "nome_financiado": "MARIA IVONE FIGLERSKI", "salario": "R$ 9000,00"}
    _write_phase1_doc(phase1_case, "proposta_daycoval", proposta_payload)
    holerite_payload = {"total_vencimentos": "R$ 10.000,00"}
    _write_phase1_doc(phase1_case, "holerite", holerite_payload)


def _find_valid_cnpj(base12_digits: str) -> str:
    """Gera um CNPJ 14 válido usando o validador do projeto (sem assumir algoritmo)."""
    assert len(base12_digits) == 12 and base12_digits.isdigit()
    for last2 in range(0, 100):
        candidate = base12_digits + f"{last2:02d}"
        if _is_valid_cnpj(candidate):
            return candidate
    raise AssertionError("Could not find a valid CNPJ for the given base12 prefix")


def _find_valid_cpf(base9_digits: str) -> str:
    """Gera um CPF 11 válido usando o validador do projeto (sem assumir algoritmo)."""
    assert len(base9_digits) == 9 and base9_digits.isdigit()
    for last2 in range(0, 100):
        candidate = base9_digits + f"{last2:02d}"
        if _is_valid_cpf(candidate):
            return candidate
    raise AssertionError("Could not find a valid CPF for the given base9 prefix")


def _find_valid_renavam(base10_digits: str) -> str:
    """Gera um RENAVAM 11 válido usando o validador do projeto (sem assumir algoritmo)."""
    assert len(base10_digits) == 10 and base10_digits.isdigit()
    for last in "0123456789":
        candidate = base10_digits + last
        if _is_valid_renavam_11(candidate):
            return candidate
    raise AssertionError("Could not find a valid RENAVAM for the given base10 prefix")


def test_vendedor_matches_owner_is_ok_when_docs_match(tmp_path: Path) -> None:
    """Quando doc do vendedor no ATPV e doc do proprietário no CRLV-e existem e são válidos, devem bater => OK."""
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    # Gate1 minimal
    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})
    _neutralize_income_to_ok(phase1_case)

    # CRLV-e presente com RENAVAM válido (para não gerar WARN/FAIL nos checks de renavam)
    vehicle_ren = _find_valid_renavam("1234567890")
    owner_doc = _find_valid_cnpj("112223330001")
    _write_phase1_doc(
        phase1_case,
        "crlv_e",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "renavam": vehicle_ren,
            "proprietario_doc": owner_doc,
        },
    )

    # ATPV com RENAVAM válido e igual ao CRLV-e; vendedor_doc == owner_doc
    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "renavam": vehicle_ren,
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",  # match proposta
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
            "vendedor_cpf_cnpj": owner_doc,
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]

    # Cross-check vendedor ↔ proprietário
    chk = _find_check(report, "vehicle.atpv.vendedor.matches_vehicle_owner")
    assert chk["status"] == "OK"

    # Renavam hardening deve estar OK neste cenário
    assert _find_check(report, "vehicle.atpv.renavam.required_if_supported")["status"] == "OK"
    assert _find_check(report, "vehicle.atpv.renavam.matches_vehicle_doc")["status"] == "OK"

    # Policy A não pode sumir
    assert _find_check(report, "vehicle.atpv.comprador.matches_proposta")["status"] == "OK"

    # overall_status deve ficar OK (nenhum WARN/FAIL esperado)
    assert report.get("overall_status") == "OK"
    assert (report.get("summary") or {}).get("overall_status") == "OK"


def test_vendedor_mismatch_is_warn_when_both_docs_valid(tmp_path: Path) -> None:
    """Se vendedor_doc e owner_doc são válidos mas diferentes, o check deve virar WARN (condicional por enquanto)."""
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})
    _neutralize_income_to_ok(phase1_case)

    vehicle_ren = _find_valid_renavam("1234567890")
    owner_doc = _find_valid_cnpj("112223330001")
    other_vendor_doc = _find_valid_cpf("123456789")
    assert owner_doc != other_vendor_doc

    _write_phase1_doc(
        phase1_case,
        "crlv_e",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "renavam": vehicle_ren,
            "proprietario_doc": owner_doc,
        },
    )

    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "renavam": vehicle_ren,
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
            "vendedor_cpf_cnpj": other_vendor_doc,
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]

    chk = _find_check(report, "vehicle.atpv.vendedor.matches_vehicle_owner")
    assert chk["status"] == "WARN"

    # Ainda assim, renavam hardening e Policy A devem ficar OK
    assert _find_check(report, "vehicle.atpv.renavam.required_if_supported")["status"] == "OK"
    assert _find_check(report, "vehicle.atpv.renavam.matches_vehicle_doc")["status"] == "OK"
    assert _find_check(report, "vehicle.atpv.comprador.matches_proposta")["status"] == "OK"

    # WARN deve degradar overall_status (por enquanto)
    assert report.get("overall_status") == "WARN"
    assert (report.get("summary") or {}).get("overall_status") == "WARN"
