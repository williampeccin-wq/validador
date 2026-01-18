# tests/test_phase2_master_report_atpv_policy_a.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.phase2.master_report import build_master_report


def _write_phase1_doc(case_root: Path, doc_type: str, payload: Dict[str, Any], name: str = "0001.json") -> Path:
    d = case_root / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"data": payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _mk_case_roots(tmp_path: Path) -> Dict[str, Path | str]:
    case_id = "case-atpv-001"
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
    """
    Ensures income checks do NOT produce MISSING/WARN so we can isolate ATPV policy behavior.
    """
    # Declared income present
    proposta_payload = {"cpf": "11144477735", "nome_financiado": "MARIA IVONE FIGLERSKI", "salario": "R$ 9000,00"}
    _write_phase1_doc(phase1_case, "proposta_daycoval", proposta_payload)

    # Proof doc present with extractable value
    holerite_payload = {"total_vencimentos": "R$ 10.000,00"}
    _write_phase1_doc(phase1_case, "holerite", holerite_payload)


def test_atpv_mismatch_degrades_overall_status_policy_a(tmp_path: Path) -> None:
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    # Gate1 required docs (minimal)
    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})

    # Neutralize income checks (avoid MISSING overriding WARN)
    _neutralize_income_to_ok(phase1_case)

    # ATPV present but buyer doc mismatches proposta => WARN => overall_status WARN (Policy A)
    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "22233344455",  # mismatch
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
            "renavam": None,  # condicional
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]

    chk = _find_check(report, "vehicle.atpv.comprador.matches_proposta")
    assert chk["status"] == "WARN"

    assert report.get("overall_status") == "WARN"
    assert (report.get("summary") or {}).get("overall_status") == "WARN"

    # Followups exist and are OK (do not degrade)
    assert _find_check(report, "followup.atpv.renavam")["status"] == "OK"
    assert _find_check(report, "followup.atpv.vendedor")["status"] == "OK"


def test_atpv_match_keeps_check_ok(tmp_path: Path) -> None:
    r = _mk_case_roots(tmp_path)
    case_id = str(r["case_id"])
    phase1_case = r["phase1_case_root"]  # type: ignore[assignment]

    _write_phase1_doc(phase1_case, "cnh", {"cpf": "11144477735", "nome": "MARIA IVONE FIGLERSKI"})
    _neutralize_income_to_ok(phase1_case)

    _write_phase1_doc(
        phase1_case,
        "atpv",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",  # match
            "comprador_nome": "MARIA IVONE FIGLERSKI",
            "vendedor_nome": "CENTRAL VEICULOS LTDA",
            "renavam": None,  # condicional
        },
    )

    report = build_master_report(case_id, phase1_root=r["phase1_root"], phase2_root=r["phase2_root"])  # type: ignore[arg-type]

    chk = _find_check(report, "vehicle.atpv.comprador.matches_proposta")
    assert chk["status"] == "OK"

    assert _find_check(report, "vehicle.atpv.vendedor.informativo")["status"] == "OK"
    assert _find_check(report, "followup.atpv.renavam")["status"] == "OK"
    assert _find_check(report, "followup.atpv.vendedor")["status"] == "OK"
