# tests/test_documento_veiculo_router.py
from __future__ import annotations

from pathlib import Path

from parsers.documento_veiculo import DocumentoVeiculoParser


FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDF_ANTIGO = FIXTURES_DIR / "exemplodocumentoantigo.pdf"
PDF_NOVO = FIXTURES_DIR / "exemplodocumentoNovo.pdf"


def test_router_runs_both():
    parser = DocumentoVeiculoParser(min_text_len_threshold=800, ocr_dpi=300)

    res1 = parser.analyze(str(PDF_NOVO))
    assert res1.placa == "MHA7923"
    assert res1.proprietario == "WILLIAN BAUMANN"

    res2 = parser.analyze(str(PDF_ANTIGO))
    assert res2.placa == "AYH0307"
    assert res2.proprietario == "ELAINE THOMAS NUNES"
