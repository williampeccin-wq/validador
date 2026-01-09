# tests/test_atpv_golden.py
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


FIXTURES_DIR = Path("tests/fixtures")
GOLDENS_DIR = Path("tests/goldens") / "atpv"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "pdf_name",
    [
        "ATPV_EXEMPLO_01.pdf",
        "ATPV_EXEMPLO_02.pdf",
        "ATPV_JPEG_01.jpg",
    ],
)
def test_atpv_golden(pdf_name: str) -> None:
    ext = Path(pdf_name).suffix.lower()

    # IMAGEM -> OCR não determinístico (por enquanto)
    if ext in (".jpg", ".jpeg", ".png"):
        pytest.xfail(
            "ATPV em imagem depende de OCR determinístico. "
            "Reativar quando pipeline OCR (engine/versão/parâmetros) estiver estabilizado e fixture existir."
        )

    pdf_path = FIXTURES_DIR / pdf_name

    # PDF fixture ausente -> infra, não bug
    if not pdf_path.exists():
        pytest.xfail(
            f"Fixture PDF ainda não versionada em {pdf_path}. "
            "Reativar quando a fixture estiver disponível."
        )

    # Import só depois (evita erro de coleta se o módulo ainda não existir em certos branches)
    from parsers.atpv import analyze_atpv  # ajuste se o nome real for diferente

    out = analyze_atpv(str(pdf_path))
    assert isinstance(out, dict)

    golden_path = GOLDENS_DIR / (Path(pdf_name).stem + ".json")

    if os.getenv("WRITE_GOLDEN") == "1":
        _write_json(golden_path, out)
        pytest.skip(f"Golden atualizado: {golden_path}")

    if not golden_path.exists():
        pytest.xfail(
            f"Golden não encontrado ({golden_path}). "
            "Crie com WRITE_GOLDEN=1 ou adicione o golden ao repositório."
        )

    expected = _load_json(golden_path)
    assert out == expected
