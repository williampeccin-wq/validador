# tests/test_phase2_master_report_atpv_renavam_required_if_supported.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from validators.phase2.master_report import build_master_report


def _write_phase1_doc(case_root: Path, doc_type: str, payload: Dict[str, Any]) -> None:
    d = case_root / doc_type
    d.mkdir(parents=True, exist_ok=True)
    p = d / "0001.json"
    p.write_text(json.dumps({"data": payload}, ensure_ascii=False, indent=2), encoding="utf-8")


def _mk_case(tmp_path: Path) -> Dict[str, Any]:
    case_id = "case-atpv-renavam-hard-001"
    phase1_root = tmp_path / "phase1"
    phase2_root = tmp_path / "phase2"
    phase1_case = phase1_root / case_id
    phase1_case.mkdir(parents=True)
    phase2_root.mkdir(parents=True)
    return {
        "case_id": case_id,
        "phase1_root": phase1_root,
        "phase2_root": phase2_root,
        "phase1_case": phase1_case,
    }


def _find(report: dict, cid: str) -> dict:
    for c in report.get("checks", []):
        if c["id"] == cid:
            return c
    raise AssertionError(f"Check not found: {cid}")


def test_required_if_supported_is_fail(tmp_path: Path) -> None:
    r = _mk_case(tmp_path)
    _write_phase1_doc(r["phase1_case"], "crlv_e", {"renavam": "12345678900"})
    _write_phase1_doc(
        r["phase1_case"],
        "atpv",
        {
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",
            "comprador_nome": "MARIA IVONE FIGLERSKI",
        },
    )

    report = build_master_report(
        r["case_id"], phase1_root=r["phase1_root"], phase2_root=r["phase2_root"]
    )

    chk = _find(report, "vehicle.atpv.renavam.required_if_supported")
    assert chk["status"] == "FAIL"
    assert report["overall_status"] == "FAIL"


def test_renavam_crosscheck_mismatch_fails(tmp_path: Path) -> None:
    r = _mk_case(tmp_path)
    _write_phase1_doc(r["phase1_case"], "crlv_e", {"renavam": "12345678900"})
    _write_phase1_doc(
        r["phase1_case"],
        "atpv",
        {
            "renavam": "98765432100",
            "placa": "ASY6E68",
            "chassi": "9BD118181B1126184",
            "valor_venda": "R$ 10.000,00",
            "comprador_cpf_cnpj": "11144477735",
            "comprador_nome": "MARIA IVONE FIGLERSKI",
        },
    )

    report = build_master_report(
        r["case_id"], phase1_root=r["phase1_root"], phase2_root=r["phase2_root"]
    )

    chk = _find(report, "vehicle.atpv.renavam.matches_vehicle_doc")
    assert chk["status"] == "FAIL"
    assert report["overall_status"] == "FAIL"
