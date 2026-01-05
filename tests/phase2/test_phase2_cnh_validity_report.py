# tests/phase2/test_phase2_cnh_validity_report.py
from __future__ import annotations

from datetime import date

from validators.phase2.cnh_validity_validator import build_cnh_validity_report


def test_phase2_cnh_validity_report_valid():
    cnh_data = {"validade": "21/07/2030"}
    rep = build_cnh_validity_report(case_id="CASE-1", cnh_data=cnh_data, today=date(2026, 1, 5))

    assert rep["validator"] == "cnh_validity"
    assert rep["case_id"] == "CASE-1"
    assert rep["summary"]["total_checks"] == 1
    assert rep["summary"]["valid"] == 1
    assert rep["summary"]["expired"] == 0

    item = rep["sections"]["checks"][0]
    assert item["field"] == "validade"
    assert item["status"] == "valid"
    assert isinstance(item["explain"], str) and len(item["explain"]) > 0
    assert item["cnh"]["normalized"] == "2030-07-21"
    assert item["derived"]["days_to_expire"] is not None
    assert item["derived"]["days_to_expire"] >= 0


def test_phase2_cnh_validity_report_expired():
    cnh_data = {"validade": "2022-07-25"}
    rep = build_cnh_validity_report(case_id="CASE-2", cnh_data=cnh_data, today=date(2026, 1, 5))

    assert rep["summary"]["expired"] == 1
    item = rep["sections"]["checks"][0]
    assert item["status"] == "expired"
    assert item["cnh"]["normalized"] == "2022-07-25"
    assert item["derived"]["days_to_expire"] is not None
    assert item["derived"]["days_to_expire"] < 0


def test_phase2_cnh_validity_report_missing():
    cnh_data = {"validade": None}
    rep = build_cnh_validity_report(case_id="CASE-3", cnh_data=cnh_data, today=date(2026, 1, 5))

    assert rep["summary"]["missing"] == 1
    item = rep["sections"]["checks"][0]
    assert item["status"] == "missing"
    assert item["cnh"]["normalized"] is None
    assert isinstance(item["explain"], str) and len(item["explain"]) > 0
