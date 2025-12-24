import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = ROOT / "tests" / "golden"


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_proposta_daycoval_golden_from_saved_native_text():
    """
    Golden regression test (Proposta Daycoval):
    - Entrada: texto nativo (pdfplumber) salvo
    - Saída: campos estruturados do contrato
    """
    raw_text = _load_text(FIXTURES / "proposta_daycoval_native.txt")
    expected = _load_json(GOLDEN / "proposta_daycoval_expected.json")

    # ajuste o import conforme seu projeto
    from parsers.proposta_daycoval import analyze_proposta_daycoval

    fields, dbg = analyze_proposta_daycoval(raw_text=raw_text, filename="andersonsantos.pdf")

    assert fields == expected, f"Proposta golden mismatch.\nGot: {fields}\nDbg: {dbg}"
