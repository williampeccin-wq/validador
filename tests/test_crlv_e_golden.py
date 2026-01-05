from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsers.crlv_e import analyze_crlv_e

GOLDENS_DIR = Path(__file__).parent / "goldens" / "crlv_e"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_contract_invariants(out: dict) -> None:
    assert out["mode"] in ("native", "ocr")
    assert "debug" in out
    dbg = out["debug"]
    assert "checks" in dbg and isinstance(dbg["checks"], dict)
    assert "warnings" in dbg and isinstance(dbg["warnings"], list)


@pytest.mark.golden
@pytest.mark.parametrize(
    "pdf_name",
    [
        "CRLV_E_EXEMPLO_01.pdf",
    ],
)
def test_crlv_e_golden(pdf_name: str) -> None:
    pdf_path = GOLDENS_DIR / pdf_name
    assert pdf_path.exists(), f"PDF não encontrado: {pdf_path}"

    out = analyze_crlv_e(str(pdf_path))
    _assert_contract_invariants(out)

    golden_path = GOLDENS_DIR / (Path(pdf_name).stem + ".json")

    if os.getenv("WRITE_GOLDEN") == "1":
        _write_json(golden_path, out)
        pytest.skip(f"Golden atualizado: {golden_path}")

    expected = _load_json(golden_path)
    assert out == expected
