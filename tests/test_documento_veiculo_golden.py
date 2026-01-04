# tests/test_documento_veiculo_golden.py
from __future__ import annotations

from pathlib import Path

from parsers.documento_veiculo import DocumentoVeiculoParser


FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDF_ANTIGO = FIXTURES_DIR / "exemplodocumentoantigo.pdf"
PDF_NOVO = FIXTURES_DIR / "exemplodocumentoNovo.pdf"


def _assert_required_fields(res: dict) -> None:
    # Campos obrigatórios
    assert res.get("placa"), "placa obrigatória"
    assert res.get("renavam"), "renavam obrigatório"
    assert res.get("chassi"), "chassi obrigatório"
    assert res.get("ano_modelo") is not None, "ano_modelo obrigatório"
    assert res.get("ano_fabricacao") is not None, "ano_fabricacao obrigatório"
    assert res.get("proprietario"), "proprietario obrigatório"


def test_documento_antigo_golden():
    assert PDF_ANTIGO.exists(), f"Fixture não encontrada: {PDF_ANTIGO}"
    parser = DocumentoVeiculoParser(min_text_len_threshold=800, ocr_dpi=300)
    res = parser.analyze(str(PDF_ANTIGO))

    out = {
        "documento": res.documento,
        "placa": res.placa,
        "renavam": res.renavam,
        "chassi": res.chassi,
        "ano_fabricacao": res.ano_fabricacao,
        "ano_modelo": res.ano_modelo,
        "proprietario": res.proprietario,
        "fonte_mode": res.fonte.mode,
    }

    _assert_required_fields(out)

    # Esperados (extraídos do próprio exemplo)
    assert out["placa"] == "AYH0307"
    assert out["renavam"] == "919217044"
    assert out["chassi"] == "935FCKFV87B529285"
    assert out["ano_fabricacao"] == 2007
    assert out["ano_modelo"] == 2007
    assert out["proprietario"] == "ELAINE THOMAS NUNES"

    # Documento antigo tende a cair em OCR (ok se for native caso seu PDF tenha texto)
    assert out["fonte_mode"] in ("ocr", "native")


def test_documento_novo_golden():
    assert PDF_NOVO.exists(), f"Fixture não encontrada: {PDF_NOVO}"
    parser = DocumentoVeiculoParser(min_text_len_threshold=800, ocr_dpi=300)
    res = parser.analyze(str(PDF_NOVO))

    out = {
        "documento": res.documento,
        "placa": res.placa,
        "renavam": res.renavam,
        "chassi": res.chassi,
        "ano_fabricacao": res.ano_fabricacao,
        "ano_modelo": res.ano_modelo,
        "proprietario": res.proprietario,
        "fonte_mode": res.fonte.mode,
    }

    _assert_required_fields(out)

    # Esperados (extraídos do próprio exemplo)
    assert out["placa"] == "MHA7923"
    assert out["renavam"] == "00133070786"
    assert out["chassi"] == "9BFZF55P898396756"
    assert out["ano_fabricacao"] == 2009
    assert out["ano_modelo"] == 2009
    assert out["proprietario"] == "WILLIAN BAUMANN"

    # CRLV-e normalmente tem texto nativo (mas ok se virar OCR)
    assert out["documento"] == "CRLV"
    assert out["fonte_mode"] in ("native", "ocr")
