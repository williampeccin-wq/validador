from __future__ import annotations

import pytest

from parsers.holerite import analyze_holerite


def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def test_holerite_sanity_contract_minimal() -> None:
    out = analyze_holerite("")

    assert isinstance(out, dict)
    for k in ("nome", "cpf", "empregador", "data_admissao", "total_vencimentos", "debug"):
        assert k in out

    dbg = out["debug"]
    assert isinstance(dbg, dict)
    assert "checks" in dbg and isinstance(dbg["checks"], dict)
    assert "warnings" in dbg and isinstance(dbg["warnings"], list)


def test_holerite_sanity_soft_cpf_dv_does_not_block() -> None:
    # CPF com DV inválido mas com 11 dígitos: deve manter extração e apenas sinalizar
    text = "NOME\nJOAO DA SILVA\nCPF 123.456.789-00\n"
    out = analyze_holerite(text)

    assert out.get("cpf") == "12345678900"  # extração não bloqueada
    dbg = out["debug"]
    assert "cpf" in dbg["checks"]
    c = dbg["checks"]["cpf"]
    assert c["normalized"] == _only_digits(out["cpf"])
    assert isinstance(c["dv_ok"], bool)
    assert c["dv_ok"] is False
    assert any("CPF" in w.upper() for w in dbg["warnings"])


def test_holerite_sanity_valid_cpf_marks_ok() -> None:
    # CPF válido conhecido para teste (exemplo didático)
    text = "NOME\nMARIA DE SOUZA\nCPF 057.750.729-01\n"
    out = analyze_holerite(text)

    assert out.get("cpf") == "05775072901"
    dbg = out["debug"]
    assert dbg["checks"]["cpf"]["dv_ok"] is True
    assert dbg["warnings"] == []  # não deve avisar
