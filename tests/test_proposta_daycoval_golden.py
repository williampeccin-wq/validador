import json
from pathlib import Path

from parsers.proposta_daycoval import analyze_proposta_daycoval

FIXTURES = Path("tests/fixtures")
GOLDENS = Path("tests/goldens")


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_proposta_daycoval_golden_from_saved_native_text():
    raw_text = _load_text(FIXTURES / "proposta_daycoval_native.txt")
    expected = _load_json(GOLDENS / "proposta_daycoval_expected.json")

    fields, dbg = analyze_proposta_daycoval(
        raw_text=raw_text,
        filename="andersonsantos.pdf",
        return_debug=True,
    )

    assert fields == expected, f"Got={fields} dbg={dbg}"
