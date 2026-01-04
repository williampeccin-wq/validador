# tests/test_documento_veiculo_antigo_golden.py
from __future__ import annotations

from pathlib import Path

from parsers.documento_veiculo_antigo import DocumentoVeiculoAntigoParser


FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDF_ANTIGO = FIXTURES_DIR / "exemplodocumentoantigo.pdf"


def _assert_required_fields(res: dict) -> None:
    assert res.get("placa"), "placa obrigatória"
    assert res.get("renavam"), "renavam obrigatório"
    assert res.get("chassi"), "chassi obrigatório"
    assert res.get("ano_modelo") is not None, "ano_modelo obrigatório"
    assert res.get("ano_fabricacao") is not None, "ano_fabricacao obrigatório"
    assert res.get("proprietario"), "proprietario obrigatório"


def test_documento_antigo_golden():
    assert PDF_ANTIGO.exists(), f"Fixture não encontrada: {PDF_ANTIGO}"
    parser = DocumentoVeiculoAntigoParser(min_text_len_threshold=800, ocr_dpi=300)
    out = parser.analyze_layout_ocr(str(PDF_ANTIGO), documento_hint="CRV")

    _assert_required_fields(out)

    assert out["placa"] == "AYH0307"
    assert out["renavam"] == "60919369893"
    assert out["chassi"] == "5GATA19102017EMDA"
    assert out["ano_fabricacao"] == 2007
    assert out["ano_modelo"] == 2007
    assert out["proprietario"] == "ELAINE THOMAS NUNES"
