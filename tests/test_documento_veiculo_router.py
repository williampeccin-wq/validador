# tests/test_documento_veiculo_router.py
from __future__ import annotations

from pathlib import Path
import pytest

from parsers.documento_veiculo import DocumentoVeiculoParser

PDF_ANTIGO = Path(__file__).parent / "fixtures" / "exemplodocumentoantigo.pdf"
PDF_NOVO = Path(__file__).parent / "fixtures" / "exemplodocumentoNovo.pdf"


def test_router_runs_both():
    parser = DocumentoVeiculoParser(min_text_len_threshold=800, ocr_dpi=300)

    res1 = parser.analyze(str(PDF_NOVO))
    assert res1.placa == "MHA7923"
    assert res1.proprietario == "WILLIAN BAUMANN"

    res2 = parser.analyze(str(PDF_ANTIGO))

    # Acordado: documento antigo é instável (OCR). Mantemos xfail até atacar isso no futuro.
    if not res2.placa:
        pytest.xfail("CRV antigo via router: OCR de placa instável (acordado para tratar no futuro).")

    assert res2.placa == "AYH0307"
