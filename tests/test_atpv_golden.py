import json
import os
from pathlib import Path

import pytest

from parsers.atpv import analyze_atpv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "atpv"
GOLDENS_DIR = ROOT / "tests" / "goldens" / "atpv"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "ATPV_EXEMPLO_01.pdf",
        "ATPV_EXEMPLO_02.jpg",
    ],
)
def test_atpv_golden(fixture_name: str) -> None:
    fixture_path = FIXTURES_DIR / fixture_name
    assert fixture_path.exists(), f"Fixture não encontrado: {fixture_path}"

    got = analyze_atpv(fixture_path)

    golden_path = GOLDENS_DIR / (fixture_path.stem + ".json")
    write_golden = os.getenv("WRITE_GOLDEN", "").strip() == "1"

    if write_golden:
        GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
        with open(golden_path, "w", encoding="utf-8") as f:
            json.dump(got, f, ensure_ascii=False, indent=2, sort_keys=True)
        pytest.skip(f"Golden atualizado: {golden_path}")

    assert golden_path.exists(), f"Golden não encontrado: {golden_path}"

    with open(golden_path, "r", encoding="utf-8") as f:
        expected = json.load(f)

    assert got == expected
