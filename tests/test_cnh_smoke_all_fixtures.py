# tests/test_cnh_smoke_all_fixtures.py
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from orchestrator.phase1 import start_case, collect_document


FIXTURES_DIR = Path("tests/fixtures/cnh")


def _list_fixture_pdfs() -> list[str]:
    return sorted(glob.glob(str(FIXTURES_DIR / "*.pdf")))


def _core_flags(data: dict) -> dict:
    return {
        "nome": bool(data.get("nome")),
        "cpf": bool(data.get("cpf")),
        "categoria": bool(data.get("categoria")),
        "data_nascimento": bool(data.get("data_nascimento")),
        "validade": bool(data.get("validade")),
    }


@pytest.mark.smoke
def test_cnh_smoke_all_fixtures_end_to_end():
    """
    SMOKE real (E2E) CNH:
    - PDF -> selector OCR (cnh_best_selector) -> parser (parsers/cnh.py) -> doc JSON (Phase1)
    - Falha se QUALQUER CNH fixture não extrair core fields.

    Observação:
    - Filiação NÃO é exigida aqui (best-effort).
    - Exige raw_text >= 2000 para evitar falso-positivo (extração vazia).
    """
    pdfs = _list_fixture_pdfs()
    assert pdfs, f"Nenhuma CNH encontrada em {FIXTURES_DIR}. Coloque PDFs em tests/fixtures/cnh/*.pdf"

    cid = start_case()
    failures: list[dict] = []

    for pdf_path in pdfs:
        doc = collect_document(cid, pdf_path, document_type="cnh")

        raw_text = doc.get("raw_text") or ""
        raw_len = len(raw_text)

        data = doc.get("data") or {}
        parse_error = doc.get("parse_error")
        extractor_debug = doc.get("extractor_debug") or {}

        core = _core_flags(data)
        ok_core = all(core.values())
        raw_ok = raw_len >= 2000

        if (parse_error is not None) or (not raw_ok) or (not ok_core):
            failures.append(
                {
                    "file": Path(pdf_path).name,
                    "raw_len": raw_len,
                    "parse_error": parse_error,
                    "core": core,
                    "data_sample": {
                        k: data.get(k)
                        for k in ["nome", "cpf", "categoria", "data_nascimento", "validade"]
                    },
                    "extractor_debug": extractor_debug,
                }
            )

    if failures:
        lines = ["CNH smoke falhou em 1+ fixture(s):"]
        for f in failures:
            lines.append(
                f"- {f['file']} raw_len={f['raw_len']} core={f['core']} parse_error={f['parse_error']}"
            )
            lines.append(f"  data_sample={f['data_sample']}")
            lines.append(f"  extractor_debug={f['extractor_debug']}")
        raise AssertionError("\n".join(lines))
