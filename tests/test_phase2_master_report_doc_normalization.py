# tests/test_phase2_master_report_doc_normalization.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.atpv import _is_valid_cnpj as _is_valid_cnpj  # type: ignore
from validators.atpv import _is_valid_cpf as _is_valid_cpf  # type: ignore
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.atpv import _normalize_renavam_to_11 as _normalize_renavam_to_11  # type: ignore
from validators.phase2.master_report import build_master_report


def _write_phase1_doc(case_root: Path, doc_type: str, payload: Dict[str, Any], name: str = "0001.json") -> Path:
    d = case_root / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"data": payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _mk_case_roots(tmp_path: Path) -> Dict[str, Path | str]:
    case_id = "case-phase2-doc-normalization-001"
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


def _find_valid_cnpj(base12_digits: str) -> str:
    assert len(base12_digits) == 12 and base12_digits.isdigit()
    for last2 in range(0, 100):
        candidate = base12_digits + f"{last2:02d}"
        if _is_valid_cnpj(candidate):
            return candidate
    raise AssertionError("Could not find a valid CNPJ for the given base12 prefix")


def _find_valid_cpf(base9_digits: str) -> str:
    assert len(base9_digits) == 9 and base9_digits.isdigit()
    for last2 in range(0, 100):
        candidate = base9_digits + f"{last2:02d}"
        if _is_valid_cpf(candidate):
            return candidate
    raise AssertionError("Could not find a valid CPF for the given base9 prefix")


def _find_valid_renavam(base11_or_less: str = "12345678900") -> str:
    # best-effort: se já vier 11, tenta; senão, normaliza e tenta completar
    d = "".join([c for c in str(base11_or_less) if c.isdigit()])
    if len(d) >= 11:
        cand = d[:11]
        if _is_valid_renavam_11(cand):
            return cand

    base10 = (d + "0" * 10)[:10]
    for last in "0123456789":
        candidate = base10 + last
        if _is_valid_renavam_11(candidate):
            return candidate
    raise AssertionError("Could not find a valid RENAVAM")


def _format_cnpj(cnpj14: str) -> str:
    assert len(cnpj14) == 14 and cnpj14.isdigit()
    return f"{cnpj14[:2]}.{cnpj14[2:5]}.{cnpj14[5:8]}/{cnpj14[8:12]}-{cnpj14[12:]}"


def _format_cpf(cpf11: str) -> str:
    assert len(cpf11) == 11 and cpf11.isdigit()
    return f"{cpf11[:3]}.{cpf11[3:6]}.{cpf11[6:9]}-{cpf11[9:]}"


def test_vendedor_owner_doc_matches_with_masked_cnpj(tmp_path: Path) -> None:
    """CNPJ com máscara (ATPV) deve comparar OK com dígitos (CRLV-e)."""
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    # Gate1 minimal
    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})
    _neutralize_income_to_ok(phase1_case)

    ren11 = _find_valid_renavam("12345678900")
    owner_doc_digits = _find_valid_cnpj("112223330001")
    vendor_doc_masked = _format_cnpj(owner_doc_digits)

    # CRLV-e com doc do proprietário em dígitos
    _write_phase1_doc(
        phase1_case,
        "crlv_e",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "renavam": ren11,
            "proprietario_doc": owner_doc_digits,
        },
    )

    # ATPV com vendedor doc mascarado
    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "renavam": _normalize_renavam_to_11(ren11),
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
            "vendedor_cpf_cnpj": vendor_doc_masked,
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]
    chk = _find_check(report, "vehicle.atpv.vendedor.matches_vehicle_owner")
    assert chk["status"] == "OK"


def test_comprador_matches_proposta_with_masked_cpf(tmp_path: Path) -> None:
    """CPF com máscara (ATPV) deve comparar OK com dígitos (Proposta)."""
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    buyer_cpf_digits = _find_valid_cpf("111444777")
    buyer_cpf_masked = _format_cpf(buyer_cpf_digits)

    # Gate1 minimal + proposta com dígitos
    _write_phase1_doc(phase1_case, "cnh", {"cpf": buyer_cpf_digits, "nome": "MARIA IVONE FIGLERSKI"})
    _write_phase1_doc(
        phase1_case,
        "proposta_daycoval",
        {"cpf": buyer_cpf_digits, "nome_financiado": "MARIA IVONE FIGLERSKI", "salario": "R$ 9000,00"},
    )
    _write_phase1_doc(phase1_case, "holerite", {"total_vencimentos": "R$ 10.000,00"})

    # Doc correlato para não gerar WARN desnecessário em renavam.required_if_supported
    ren11 = _find_valid_renavam("12345678900")
    _write_phase1_doc(
        phase1_case,
        "crlv_e",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "renavam": ren11,
            "proprietario_doc": _find_valid_cnpj("112223330001"),
        },
    )

    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "renavam": _normalize_renavam_to_11(ren11),
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": buyer_cpf_masked,  # <- máscara aqui
            "comprador_nome": "MARIA IVONE FIGLERSKI",
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]
    chk = _find_check(report, "vehicle.atpv.comprador.matches_proposta")
    assert chk["status"] == "OK"
