# tests/test_atpv_validate.py
from __future__ import annotations

import json
from pathlib import Path

from validators.atpv import validate_atpv


ROOT = Path(__file__).resolve().parents[1]
ATPV_DIR = ROOT / "tests" / "goldens" / "atpv"


def _load(name: str) -> dict:
    p = ATPV_DIR / name
    assert p.exists(), f"Fixture não encontrada: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_validate_atpv_exemplo_01_missing_required() -> None:
    data = _load("ATPV_EXEMPLO_01.json")
    res = validate_atpv(data)

    assert res.is_valid is False
    for k in ("placa", "renavam", "chassi", "comprador_cpf_cnpj", "data_venda", "valor_venda"):
        assert f"missing_required:{k}" in res.errors


def test_validate_atpv_exemplo_02_renavam_conflicts_and_missing_required() -> None:
    data = _load("ATPV_EXEMPLO_02.json")
    res = validate_atpv(data)

    assert res.is_valid is False

    # Conflito real: mesmo número foi usado como renavam e como doc do comprador
    assert "invalid:renavam_equals_comprador_doc" in res.errors

    # E ainda faltam outros obrigatórios
    for k in ("chassi", "data_venda", "valor_venda"):
        assert f"missing_required:{k}" in res.errors


def test_validate_atpv_jpeg_01_missing_valor_venda() -> None:
    data = _load("ATPV_JPEG_01.json")
    res = validate_atpv(data)

    assert res.is_valid is False
    assert "missing_required:valor_venda" in res.errors
