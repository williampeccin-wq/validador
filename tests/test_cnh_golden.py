import json
from pathlib import Path

import pytest

# Import do seu contrato público
from parsers.cnh import analyze_cnh


HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "golden"


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.golden
def test_cnh_golden_from_saved_ocr_text():
    """
    Teste de regressão (golden):
    - Entrada: texto OCR salvo
    - Saída: campos estruturados do contrato
    """
    raw_text = _load_text(FIXTURES / "cnh_ocr.txt")
    expected = _load_json(GOLDEN / "cnh_expected.json")

    fields, dbg = analyze_cnh(raw_text=raw_text, filename="CNH DIGITAL.pdf", use_gemini=False)

    # 1) Garantir presença de chaves do contrato
    for k in expected.keys():
        assert k in fields, f"Campo ausente no retorno: {k}"

    # 2) Comparação exata do payload contratual
    # (Se um dia você decidir mudar o contrato, você atualiza o expected conscientemente.)
    assert fields == expected

    # 3) Debug existe (não congelamos conteúdo; só garantimos que é dict)
    assert isinstance(dbg, dict)
