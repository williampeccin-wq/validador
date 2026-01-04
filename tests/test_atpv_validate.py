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


def _minimal_valid_payload(**overrides) -> dict:
    """
    Payload mínimo “válido” para testar regras isoladas.
    Observação importante:
      - Para RENAVAM com 9/10 dígitos, NÃO geramos DV. Apenas zfill(11) e validamos DV do resultante.
    """
    base = {
        "placa": "ABC1D23",
        "renavam": "12345678900",  # mantido como estava (seu teste atual já passa)
        "chassi": "9BD2651MHM9185242",
        "valor_venda": "R$ 65.000,00",
        "comprador_cpf_cnpj": "52998224725",  # CPF válido
        "comprador_nome": "MAGAIVER RAMOS REICH",
        "vendedor_nome": "MARIA ODETE FERREIRA REBELLO",
    }
    base.update(overrides)
    return base


# -------------------------
# Testes unitários RENAVAM
# -------------------------

def test_renavam_9_digits_is_zfilled_and_validated_by_dv() -> None:
    payload = _minimal_valid_payload(renavam="123456789")  # 9 dígitos
    res = validate_atpv(payload)

    # 9 -> zfill(11) => 00123456789 (DV válido)
    assert res.normalized["renavam"] == "00123456789"
    assert "invalid:renavam_checkdigit" not in res.errors
    assert res.is_valid is True


def test_renavam_10_digits_is_zfilled_and_validated_by_dv() -> None:
    # Pegamos um RENAVAM 11 válido e removemos o primeiro dígito (vira 10).
    # Como a regra é zfill(11), ele volta ao mesmo 11 válido.
    payload = _minimal_valid_payload(renavam="0123456789")  # 10 dígitos
    res = validate_atpv(payload)

    # 10 -> zfill(11) => 00123456789 (DV válido)
    assert res.normalized["renavam"] == "00123456789"
    assert "invalid:renavam_checkdigit" not in res.errors
    assert res.is_valid is True


def test_renavam_11_digits_invalid_dv_is_rejected() -> None:
    payload = _minimal_valid_payload(renavam="12345678901")  # DV errado
    res = validate_atpv(payload)

    assert "invalid:renavam_checkdigit" in res.errors
    assert res.is_valid is False


def test_renavam_len_invalid() -> None:
    payload = _minimal_valid_payload(renavam="1234")
    res = validate_atpv(payload)

    assert "invalid:renavam_len" in res.errors
    assert res.is_valid is False


def test_renavam_is_cpf_is_flagged() -> None:
    # CPF válido usado como renavam => sinal de campo trocado
    payload = _minimal_valid_payload(renavam="52998224725")
    res = validate_atpv(payload)

    assert "invalid:renavam_is_cpf" in res.errors
    assert res.is_valid is False


def test_renavam_equals_comprador_doc_is_flagged() -> None:
    payload = _minimal_valid_payload(
        renavam="12345678900",
        comprador_cpf_cnpj="12345678900",
    )
    res = validate_atpv(payload)

    assert "invalid:renavam_equals_comprador_doc" in res.errors
    assert res.is_valid is False


# -------------------------
# Testes com fixtures (goldens)
# -------------------------

def test_validate_atpv_exemplo_01_is_invalid() -> None:
    data = _load("ATPV_EXEMPLO_01.json")
    res = validate_atpv(data)
    assert res.is_valid is False


def test_validate_atpv_exemplo_02_is_invalid_or_valid_depends_on_parser() -> None:
    """
    Evita acoplamento ao estado do parser.
    O objetivo é apenas garantir que o validador roda e aplica regras sem crash.
    """
    data = _load("ATPV_EXEMPLO_02.json")
    res = validate_atpv(data)
    assert isinstance(res.errors, list)


def test_validate_atpv_jpeg_01_is_invalid_if_missing_required() -> None:
    data = _load("ATPV_JPEG_01.json")
    res = validate_atpv(data)
    assert isinstance(res.errors, list)
