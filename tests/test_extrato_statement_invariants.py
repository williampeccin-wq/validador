# tests/test_extrato_statement_invariants.py
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import pytest

from parsers.extrato_bancario import analyze_extrato_bancario


HERE = Path(__file__).resolve().parent
FIX_DIR = HERE / "fixtures_private"

PDFS = sorted(p for p in FIX_DIR.glob("*.pdf") if not p.name.lower().startswith("comprovante"))


def _debug_summary(data: dict) -> str:
    dbg = data.get("debug") or {}
    out = []
    out.append(f'build_id={dbg.get("build_id")}')
    out.append(f'mode={dbg.get("mode")} native_len={dbg.get("native_text_len")} ocr_len={dbg.get("ocr_text_len")}')
    out.append(f'chosen_strategy={dbg.get("chosen_strategy")}')
    out.append(f'strategy_names={dbg.get("strategy_names")}')
    out.append("strategy_scores:")
    for s in (dbg.get("strategy_scores") or []):
        if not isinstance(s, dict):
            out.append(f"  - {s!r}")
            continue
        out.append(
            f'  - {s.get("name")}: tx={s.get("tx")} matched={s.get("matched")} discarded={s.get("discarded")} score={s.get("score")} notes={s.get("notes")}'
        )
    return "\n".join(out)


def _assert_iso_date(date_str: str) -> None:
    datetime.strptime(date_str, "%Y-%m-%d")


@pytest.mark.parametrize("pdf_path", PDFS, ids=lambda p: str(p))
def test_extrato_invariants(pdf_path: Path):
    data = analyze_extrato_bancario(pdf_path.read_bytes(), pdf_path.name)

    assert isinstance(data, dict)
    assert "lancamentos" in data
    lancs = data["lancamentos"]
    assert isinstance(lancs, list)

    if len(lancs) < 1:
        pytest.fail(f"0 lançamentos extraídos em {pdf_path}\n{_debug_summary(data)}")

    for i, tx in enumerate(lancs[:200]):
        assert isinstance(tx, dict), f"tx[{i}] não é dict em {pdf_path}"
        assert "data" in tx and "descricao" in tx and "valor" in tx, f"tx[{i}] faltando campos em {pdf_path}: {tx}"
        assert isinstance(tx["data"], str) and tx["data"], f"tx[{i}] data inválida em {pdf_path}: {tx}"
        _assert_iso_date(tx["data"])
        assert isinstance(tx["descricao"], str) and len(tx["descricao"].strip()) >= 3, f"tx[{i}] descricao inválida em {pdf_path}: {tx}"
        assert isinstance(tx["valor"], (int, float)), f"tx[{i}] valor não numérico em {pdf_path}: {tx}"

    dbg = data.get("debug")
    assert isinstance(dbg, dict), f"debug ausente ou inválido em {pdf_path}"
    assert "chosen_strategy" in dbg
    assert "strategy_scores" in dbg
