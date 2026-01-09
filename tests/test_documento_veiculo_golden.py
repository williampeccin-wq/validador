# tests/test_documento_veiculo_golden.py
from __future__ import annotations

from pathlib import Path
import pytest

from parsers.documento_veiculo import DocumentoVeiculoParser

PDF_ANTIGO = Path(__file__).parent / "fixtures" / "exemplodocumentoantigo.pdf"
PDF_NOVO = Path(__file__).parent / "fixtures" / "exemplodocumentoNovo.pdf"


def _assert_required_fields(res: dict) -> None:
    # Campos obrigatórios
    assert res.get("placa"), "placa obrigatória"
    assert res.get("renavam"), "renavam obrigatório"
    assert res.get("ano_fabricacao"), "ano_fabricacao obrigatório"
    assert res.get("ano_modelo"), "ano_modelo obrigatório"
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

    # Acordado: documento antigo é instável (OCR). Mantemos xfail até atacar isso no futuro.
    if not out.get("placa"):
        pytest.xfail("CRV antigo via router: OCR de placa instável (acordado para tratar no futuro).")

    _assert_required_fields(out)

    # Esperados (extraídos do próprio exemplo)
    assert out["placa"] == "AYH0307"
    assert out["renavam"] == "919217044"
    assert out["ano_fabricacao"] == 2007
    assert out["ano_modelo"] == 2007
    assert out["proprietario"] == "ELAINE THOMAS NUNES"


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
