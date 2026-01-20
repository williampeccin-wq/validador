# tests/test_proposta_daycoval_vlr_compra_and_core_fields.py
from __future__ import annotations

import glob
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from orchestrator.phase1 import collect_document, start_case


FIXTURES_DIR = Path("tests/fixtures")


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _norm_upper(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _money_to_float(v: Any) -> Optional[float]:
    """
    Normaliza valores monetários vindos como:
      - "32.580,00"
      - "R$ 32.580,00"
      - 32580
      - 32580.0
    Retorna float (ex.: 32580.00) ou None.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("R$", "").strip()
    s = s.replace(".", "").replace(" ", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _assert_has_keys(d: Dict[str, Any], keys: list[str]) -> None:
    missing = [k for k in keys if k not in d]
    assert not missing, f"Campos ausentes no JSON da proposta: {missing}. Keys atuais: {sorted(d.keys())}"


def _load_last_phase1_json(case_id: str, doc_type: str) -> Dict[str, Any]:
    paths = sorted(glob.glob(f"storage/phase1/{case_id}/{doc_type}/*.json"))
    assert paths, f"Nenhum JSON encontrado em storage/phase1/{case_id}/{doc_type}/"
    p = paths[-1]
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


@dataclass(frozen=True)
class ExpectedProposal:
    fixture_name: str
    proposta: str
    nome_financiado_contains: str
    cpf_digits: Optional[str]
    salario: Optional[float]
    outras_rendas: Optional[float]
    valor_parcela: Optional[float]
    valor_compra: Optional[float]


CASES: list[ExpectedProposal] = [
    ExpectedProposal(
        fixture_name="fernandowettererproposta.pdf",
        proposta="008361141",
        nome_financiado_contains="FERNANDO",
        cpf_digits="07185129958",
        salario=4000.00,
        outras_rendas=0.00,
        valor_parcela=1179.68,
        valor_compra=32580.00,
    ),
    ExpectedProposal(
        fixture_name="franciscodantaspropostas.pdf",
        proposta="008364023",
        nome_financiado_contains="FRANCISCO",
        cpf_digits="84847590325",
        salario=None,
        outras_rendas=None,
        valor_parcela=1548.46,
        valor_compra=43094.00,
    ),
]


@pytest.mark.parametrize("c", CASES, ids=lambda c: c.fixture_name)
def test_proposta_daycoval_extracts_core_fields_including_valor_compra(c: ExpectedProposal) -> None:
    pdf = FIXTURES_DIR / c.fixture_name
    assert pdf.exists(), f"Fixture não encontrada: {pdf}"

    case_id = start_case()
    collect_document(case_id, str(pdf), document_type="proposta_daycoval")

    doc = _load_last_phase1_json(case_id, "proposta_daycoval")
    data = doc.get("data") or {}
    assert isinstance(data, dict), f"doc['data'] inválido: {type(data)}"

    required_keys = [
        "proposta",
        "nome_financiado",
        "cpf",
        "salario",
        "outras_rendas",
        # obrigatórios de negócio na Proposta:
        "valor_parcela",
        "valor_compra",
    ]
    _assert_has_keys(data, required_keys)

    assert str(data.get("proposta") or "").strip() == c.proposta

    nome = _norm_upper(str(data.get("nome_financiado") or ""))
    assert c.nome_financiado_contains in nome, f"nome_financiado inesperado: {data.get('nome_financiado')}"

    if c.cpf_digits is not None:
        cpf = _only_digits(str(data.get("cpf") or ""))
        assert cpf.endswith(c.cpf_digits), f"cpf inesperado: {data.get('cpf')} (digits={cpf})"

    if c.salario is not None:
        assert _money_to_float(data.get("salario")) == pytest.approx(c.salario, abs=0.01)
    if c.outras_rendas is not None:
        assert _money_to_float(data.get("outras_rendas")) == pytest.approx(c.outras_rendas, abs=0.01)

    assert _money_to_float(data.get("valor_parcela")) == pytest.approx(c.valor_parcela, abs=0.01)
    assert _money_to_float(data.get("valor_compra")) == pytest.approx(c.valor_compra, abs=0.01)


def test_proposta_daycoval_valor_compra_key_is_present_even_when_blank() -> None:
    """
    Contrato de shape: a key existe, mesmo que o valor seja None/""
    (ex.: fixtures antigos que não possuem Vlr. Compra).
    """
    pdf = FIXTURES_DIR / "andersonsantos.pdf"
    assert pdf.exists(), f"Fixture não encontrada: {pdf}"

    case_id = start_case()
    collect_document(case_id, str(pdf), document_type="proposta_daycoval")

    doc = _load_last_phase1_json(case_id, "proposta_daycoval")
    data = doc.get("data") or {}
    assert isinstance(data, dict)

    assert "valor_compra" in data, f"Key valor_compra não existe. Keys atuais: {sorted(data.keys())}"
