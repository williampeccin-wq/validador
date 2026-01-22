# tests/test_cnh_golden.py
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsers.cnh import analyze_cnh


HERE = Path(__file__).resolve().parent
FIXTURES_DIR = HERE / "fixtures"
GOLDENS_DIR = HERE / "goldens"


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _analyze(raw_text: str, filename: str) -> tuple[dict, dict]:
    """
    Contrato: analyze_cnh retorna (fields, debug)
    - fields: dict contratual da CNH (congelado pelo golden)
    - debug : dict auxiliar (não congelado integralmente)
    """
    res = analyze_cnh(raw_text=raw_text, filename=filename)
    assert isinstance(res, tuple) and len(res) == 2, "analyze_cnh deve retornar (fields, dbg)"
    fields, dbg = res
    assert isinstance(fields, dict), "fields deve ser dict"
    assert isinstance(dbg, dict), "dbg deve ser dict"
    return fields, dbg


@pytest.mark.parametrize(
    "fixture_txt, expected_json, filename",
    [
        # CNH “DIGITAL” (na prática: SENATRAN/SERPRO) — Anderson
        (
            FIXTURES_DIR / "cnh_ocr.txt",
            GOLDENS_DIR / "cnh_expected.json",
            "CNH DIGITAL.pdf",
        ),
        # CNH SENATRAN / Detalhamento — Lucas
        (
            FIXTURES_DIR / "cnh_senatran_lucas_ocr.txt",
            GOLDENS_DIR / "cnh_senatran_lucas_expected.json",
            "lucasTambreValidCNH.pdf",
        ),
    ],
)
def test_cnh_golden_from_saved_ocr_text(fixture_txt: Path, expected_json: Path, filename: str):
    """
    Teste GOLDEN do DOCUMENTO CNH (Opção A):

    - CNH é UM documento, com UM contrato.
    - Origem/layout (PDF, app, “CNH DIGITAL”, “Detalhamento”) não cria um novo tipo.
    - Neste repo, os exemplos são SENATRAN (dbg.mode == "senatran").
    """
    assert fixture_txt.exists(), f"Fixture não encontrado: {fixture_txt}"

    raw_text = _load_text(fixture_txt)

    fields, dbg = _analyze(raw_text=raw_text, filename=filename)

    # Regra de arquitetura desta opção:
    assert dbg.get("mode") == "senatran", f"CNH deve estar em modo senatran. dbg={dbg}"

    # Se quiser atualizar conscientemente o golden:
    if os.getenv("UPDATE_GOLDEN") == "1":
        _write_json(expected_json, fields)

    assert expected_json.exists(), (
        f"Golden não encontrado: {expected_json}\n"
        f"Rode com UPDATE_GOLDEN=1 para gerar."
    )
    expected = _load_json(expected_json)

    # Congela o contrato por igualdade exata
    assert fields == expected, f"Got={fields} dbg={dbg}"
