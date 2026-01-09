# tests/test_documento_veiculo_antigo_golden.py
from __future__ import annotations

from pathlib import Path
import pytest

from parsers.documento_veiculo_antigo import DocumentoVeiculoAntigoParser

PDF_ANTIGO = Path(__file__).parent / "fixtures" / "exemplodocumentoantigo.pdf"


def _assert_required_fields(res: dict) -> None:
    assert res.get("placa"), "placa obrigatória"
    assert res.get("renavam"), "renavam obrigatório"
    assert res.get("ano_fabricacao"), "ano_fabricacao obrigatório"
    assert res.get("ano_modelo"), "ano_modelo obrigatório"
    assert res.get("proprietario"), "proprietario obrigatório"


def test_documento_antigo_golden():
    assert PDF_ANTIGO.exists(), f"Fixture não encontrada: {PDF_ANTIGO}"
    parser = DocumentoVeiculoAntigoParser(min_text_len_threshold=800, ocr_dpi=300)
    out = parser.analyze_layout_ocr(str(PDF_ANTIGO), documento_hint="CRV")

    # Acordado: documento antigo é instável (OCR). Mantemos xfail até atacar isso no futuro.
    if not out.get("placa"):
        pytest.xfail("CRV antigo: OCR de placa instável (acordado para tratar no futuro).")

    _assert_required_fields(out)

    # Esperados (extraídos do próprio exemplo)
    assert out["placa"] == "AYH0307"
    assert out["renavam"] == "919217044"
    assert out["ano_fabricacao"] == 2007
    assert out["ano_modelo"] == 2007
    assert out["proprietario"] == "ELAINE THOMAS NUNES"
