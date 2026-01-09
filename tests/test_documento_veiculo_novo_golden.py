# tests/test_documento_veiculo_novo_golden.py
from __future__ import annotations

from pathlib import Path

from parsers.documento_veiculo_novo import DocumentoVeiculoNovoParser


FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDF_NOVO = FIXTURES_DIR / "exemplodocumentoNovo.pdf"


def _assert_required_fields(res: dict) -> None:
    assert res.get("placa"), "placa obrigatória"
    assert res.get("renavam"), "renavam obrigatório"
    assert res.get("chassi"), "chassi obrigatório"
    assert res.get("ano_modelo") is not None, "ano_modelo obrigatório"
    assert res.get("ano_fabricacao") is not None, "ano_fabricacao obrigatório"
    assert res.get("proprietario"), "proprietario obrigatório"


def test_documento_novo_golden():
    assert PDF_NOVO.exists(), f"Fixture não encontrada: {PDF_NOVO}"
    parser = DocumentoVeiculoNovoParser(min_text_len_threshold=800, ocr_dpi=300)
    out = parser.analyze_layout_ocr(str(PDF_NOVO), documento_hint="CRLV")

    _assert_required_fields(out)

    assert out["placa"] == "MHA7923"
    assert out["renavam"] == "00133070786"
    assert out["chassi"] == "9BFZF55P898396756"
    assert out["ano_fabricacao"] == 2009
    assert out["ano_modelo"] == 2009
    assert out["proprietario"] == "WILLIAN BAUMANN"
