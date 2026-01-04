from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsers.atpv import analyze_atpv


ROOT = Path(__file__).resolve().parents[1]
GOLDENS_DIR = ROOT / "tests" / "goldens" / "atpv"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_contract_invariants(out: dict) -> None:
    assert isinstance(out, dict)

    # Passo 5: mode explícito no output
    assert "mode" in out, "output deve conter a chave 'mode'"
    assert out["mode"] in ("native", "ocr"), "mode deve ser 'native' ou 'ocr'"

    # Debug mínimo e coerente
    assert "debug" in out and isinstance(out["debug"], dict), "output deve conter 'debug' dict"
    dbg = out["debug"]

    assert "mode" in dbg, "debug deve conter 'mode'"
    assert dbg["mode"] in ("native", "ocr")
    assert dbg["mode"] == out["mode"], "debug.mode deve bater com mode"

    for k in ("native_text_len", "ocr_text_len", "min_text_len_threshold", "ocr_dpi"):
        assert k in dbg, f"debug deve conter '{k}'"
        assert isinstance(dbg[k], int), f"debug.{k} deve ser int"

    assert "pages" in dbg and isinstance(dbg["pages"], list), "debug.pages deve existir e ser list"
    for page in dbg["pages"]:
        assert isinstance(page, dict)
        assert isinstance(page.get("page"), int)
        assert isinstance(page.get("native_len"), int)
        assert isinstance(page.get("ocr_len"), int)

    # Coerência mínima (sem heurística: não deduz mode; apenas valida plausibilidade)
    if out["mode"] == "native":
        assert dbg["native_text_len"] > 0, "native deve ter texto nativo > 0"
        assert dbg["ocr_text_len"] >= 0
    else:
        assert dbg["ocr_text_len"] > 0, "ocr deve ter texto OCR > 0"
        assert dbg["native_text_len"] >= 0

    # Campos opcionais: apenas sanidade de tipo se vierem preenchidos
    for k in ("comprador_nome", "vendedor_nome", "cpf", "cnpj", "placa", "renavam"):
        if k in out and out[k] is not None:
            assert isinstance(out[k], str)
            assert out[k].strip() != ""


@pytest.mark.golden
@pytest.mark.parametrize(
    "pdf_name",
    [
        "ATPV_EXEMPLO_01.pdf",
        "ATPV_EXEMPLO_02.pdf",
    ],
)
def test_atpv_golden(pdf_name: str) -> None:
    pdf_path = GOLDENS_DIR / pdf_name
    assert pdf_path.exists(), f"PDF não encontrado: {pdf_path}"

    out = analyze_atpv(str(pdf_path))
    _assert_contract_invariants(out)

    golden_path = GOLDENS_DIR / (Path(pdf_name).stem + ".json")

    if os.getenv("WRITE_GOLDEN") == "1":
        _write_json(golden_path, out)
        pytest.skip(f"Golden atualizado: {golden_path}")

    expected = _load_json(golden_path)
    assert out == expected
