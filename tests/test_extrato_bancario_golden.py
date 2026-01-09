# tests/test_extrato_bancario_golden.py
from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURE_TXT = Path("tests/fixtures/extrato_itau_2024_06_native.txt")
GOLDEN_JSON = Path("tests/goldens/extrato_itau_2024_06.json")


def test_extrato_itau_2024_06_golden_from_text() -> None:
    """
    Extrato deve ser testado de forma determinística a partir do texto já extraído.
    Enquanto o TXT não existir, o teste deve xfail (infra), não falhar.
    """
    if not FIXTURE_TXT.exists():
        pytest.xfail(
            f"Text fixture ainda não gerada/versionada: {FIXTURE_TXT}. "
            "Gere a partir do PDF local (uma vez) e adicione o TXT no repo. "
            "Este xfail deve ser removido automaticamente quando o arquivo existir."
        )

    if not GOLDEN_JSON.exists():
        pytest.xfail(
            f"Golden JSON ausente: {GOLDEN_JSON}. "
            "Adicione o golden correspondente (sem PDF)."
        )

    raw_text = FIXTURE_TXT.read_text(encoding="utf-8", errors="replace")
    expected = json.loads(GOLDEN_JSON.read_text(encoding="utf-8"))

    # Import sensível: apenas depois que sabemos que fixtures existem
    # (evita ImportError em tempo de coleta)
    from parsers.extrato_bancario_text import analyze_extrato_bancario_from_text

    data = analyze_extrato_bancario_from_text(raw_text, filename=FIXTURE_TXT.name)
    assert isinstance(data, dict)
    assert "lancamentos" in data

    assert data["lancamentos"] == expected
