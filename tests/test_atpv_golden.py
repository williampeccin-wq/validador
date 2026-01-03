# tests/test_atpv_golden.py
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsers.atpv import analyze_atpv

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "atpv"
GOLDENS_DIR = Path(__file__).parent / "goldens" / "atpv"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _should_write_golden() -> bool:
    return os.environ.get("WRITE_GOLDEN", "").strip() == "1"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "ATPV_EXEMPLO_01.pdf",
        "ATPV_EXEMPLO_02.jpg",
    ],
)
def test_atpv_golden(fixture_name: str) -> None:
    fixture_path = FIXTURES_DIR / fixture_name
    if not fixture_path.exists():
        pytest.fail(f"Fixture não encontrado: {fixture_path}")

    write_golden = _should_write_golden()

    # Regra:
    # - Ao gerar golden: strict=False (para não morrer por missing enquanto evoluímos o parser)
    # - No teste normal: strict=True (qualidade)
    got = analyze_atpv(fixture_path, strict=not write_golden)

    golden_path = GOLDENS_DIR / f"{fixture_path.stem}.json"

    if write_golden:
        _write_json(golden_path, got)
        pytest.skip(f"Golden atualizado: {golden_path}")

    if not golden_path.exists():
        pytest.fail(
            f"Golden ausente: {golden_path}. "
            f"Rode com WRITE_GOLDEN=1 para criar o golden a partir do resultado atual."
        )

    expected = _load_json(golden_path)

    # Para evitar flakiness: debug pode variar. Compara separadamente.
    got_debug = got.pop("debug", None)
    expected.pop("debug", None)

    assert got == expected

    # Debug mínimo estável
    assert isinstance(got_debug, dict)
    assert got_debug.get("mode") in ("native", "ocr")
    assert isinstance(got_debug.get("min_text_len_threshold"), int)
