# tests/test_extrato_bancario_golden.py
from __future__ import annotations

import json
from pathlib import Path

from parsers.extrato_bancario import analyze_extrato_bancario


FIXTURE = Path("tests/fixtures/extrato_itau_2024_06.pdf")
GOLDEN = Path("tests/golden/extrato_itau_2024_06.json")


def test_extrato_itau_2024_06_golden():
    assert FIXTURE.exists(), f"Missing fixture: {FIXTURE}"

    data = analyze_extrato_bancario(FIXTURE.read_bytes(), FIXTURE.name)

    assert "lancamentos" in data
    got = data["lancamentos"]

    assert GOLDEN.exists(), (
        f"Missing golden file: {GOLDEN}\n"
        "Create it with the expected output (see tests/golden/extrato_itau_2024_06.json)."
    )

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    # MVP: valida somente lançamentos (ordem e valores)
    assert got == expected
