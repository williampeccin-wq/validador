# tests/test_proposta_daycoval_required_valores_compra_e_parcela.py

from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from orchestrator.phase1 import collect_document, start_case


FIXTURES = Path("tests/fixtures")


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _norm_br_money_str(s: Optional[str]) -> Optional[str]:
    """
    Normaliza string BR de dinheiro para formato canônico "12345,67"
    (sem R$, sem espaços, sem milhares com ponto).
    """
    if s is None:
        return None
    s2 = str(s).strip().replace("R$", "").strip()
    if not s2:
        return None
    # tira pontos de milhar: "32.580,00" -> "32580,00"
    s2 = s2.replace(".", "")
    # mantém vírgula decimal
    m = re.search(r"\d+,\d{2}", s2)
    return m.group(0) if m else None


def _load_last_phase1_json(case_id: str, doc_type: str) -> Dict[str, Any]:
    paths = sorted(glob.glob(f"storage/phase1/{case_id}/{doc_type}/*.json"))
    assert paths, f"Nenhum JSON encontrado em storage/phase1/{case_id}/{doc_type}/"
    p = paths[-1]
    return json.loads(Path(p).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fixture, expected_proposta, expected_cpf, expected_valor_compra, expected_valor_parcela",
    [
        ("fernandowettererproposta.pdf", "008361141", "07185129958", "32580,00", "1179,68"),
        ("franciscodantaspropostas.pdf", "008364023", "84847590325", "43094,00", "1548,46"),
    ],
)
def test_proposta_daycoval_extrai_valor_compra_e_valor_parcela_obrigatorios(
    fixture: str,
    expected_proposta: str,
    expected_cpf: str,
    expected_valor_compra: str,
    expected_valor_parcela: str,
) -> None:
    pdf = FIXTURES / fixture
    assert pdf.exists(), f"Fixture não encontrada: {pdf}"

    case_id = start_case()
    collect_document(case_id, str(pdf), document_type="proposta_daycoval")

    doc = _load_last_phase1_json(case_id, "proposta_daycoval")
    data = doc.get("data") or {}
    assert isinstance(data, dict)

    # sanity: proposta e cpf
    assert str(data.get("proposta") or "").strip() == expected_proposta
    assert _only_digits(str(data.get("cpf") or "")) == expected_cpf

    # obrigatórios: valor_compra (FIPE) e valor_parcela (financiamento)
    vc = _norm_br_money_str(data.get("valor_compra"))
    vp = _norm_br_money_str(data.get("valor_parcela"))

    assert vc == expected_valor_compra, f"valor_compra inválido: raw={data.get('valor_compra')} norm={vc}"
    assert vp == expected_valor_parcela, f"valor_parcela inválido: raw={data.get('valor_parcela')} norm={vp}"
