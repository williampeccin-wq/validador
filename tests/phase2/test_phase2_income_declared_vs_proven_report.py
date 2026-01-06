# tests/phase2/test_phase2_income_declared_vs_proven_report.py
from __future__ import annotations

from datetime import date

from validators.phase2.income_declared_vs_proven_validator import (
    build_income_declared_vs_proven_report,
)


def test_income_report_compatible_with_holerite_and_extrato_apurado():
    proposta = {"salario": "3.700,00", "outras_rendas": "3.000,00"}
    holerite = {"total_vencimentos": "3.800,00"}
    extrato = {"renda_apurada": "3.000,00"}  # campo já apurado no payload

    rep = build_income_declared_vs_proven_report(
        case_id="CASE-1",
        proposta_data=proposta,
        holerite_data=holerite,
        extrato_data=extrato,
        today=date(2026, 1, 5),
    )

    assert rep["validator"] == "income_declared_vs_proven"
    assert rep["case_id"] == "CASE-1"
    assert rep["summary"]["total_declared"] == 6700.0
    assert rep["summary"]["total_proven"] == 6800.0
    assert rep["summary"]["status"] == "compatible"
    assert rep["summary"]["coverage_ratio"] is not None
    assert rep["summary"]["coverage_ratio"] > 1.0

    declared = rep["sections"]["declared"]["items"]
    assert declared[0]["label"] == "renda_principal"
    assert declared[1]["label"] == "outras_rendas"

    proven = rep["sections"]["proven"]["sources"]
    assert len(proven) >= 2
    assert any(s["document"] == "holerite" and s["normalized"] == 3800.0 for s in proven)
    assert any(s["document"] == "extrato_bancario" and s["normalized"] == 3000.0 for s in proven)


def test_income_report_proven_missing_when_no_docs():
    proposta = {"salario": "3.700,00", "outras_rendas": "3.000,00"}

    rep = build_income_declared_vs_proven_report(
        case_id="CASE-2",
        proposta_data=proposta,
        holerite_data=None,
        folha_data=None,
        extrato_data=None,
    )

    assert rep["summary"]["total_declared"] == 6700.0
    assert rep["summary"]["total_proven"] is None
    assert rep["summary"]["status"] == "proven_missing"


def test_income_report_declared_missing_when_no_renda_in_proposta():
    proposta = {"salario": None, "outras_rendas": None}
    holerite = {"total_vencimentos": "3.800,00"}

    rep = build_income_declared_vs_proven_report(
        case_id="CASE-3",
        proposta_data=proposta,
        holerite_data=holerite,
    )

    assert rep["summary"]["total_declared"] is None
    assert rep["summary"]["total_proven"] == 3800.0
    assert rep["summary"]["status"] == "declared_missing"
