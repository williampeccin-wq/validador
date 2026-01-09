# parsers/extrato_bancario_text.py
from __future__ import annotations

from typing import Any, Callable, Dict, List
from datetime import datetime

from parsers import extrato_bancario as eb


def analyze_extrato_bancario_from_text(
    raw_text: str,
    filename: str = "extrato.txt",
) -> Dict[str, Any]:
    """
    Parser determinístico de extrato bancário a partir de texto já extraído.

    Objetivo:
      - evitar dependência de PDF/binário nos testes
      - manter a mesma estrutura retornada por analyze_extrato_bancario: {"lancamentos": [...], "debug": {...}}
    """
    debug: Dict[str, Any] = {
        "build_id": getattr(eb, "_BUILD_ID", "unknown"),
        "mode": "text",
        "native_text_len": len(raw_text or ""),
        "ocr_text_len": 0,
        "pages": [],
        "min_text_len_threshold": None,
        "ocr_dpi": None,
        "chosen_strategy": "none",
        "strategy_scores": [],
        "strategy_names": [],
        "source_filename": filename,
    }

    try:
        lines = eb._normalize_lines(raw_text or "")

        strategies: List[Callable[[List[str]], eb.StrategyResult]] = [
            eb._parse_itau_line_end_value,
            eb._parse_pj_tabular_multivalue,
            eb._parse_month_sections_dual_dates,
            eb._parse_inter_inline,
            eb._parse_month_columnar_zip,
            eb._parse_generic_ddmmyyyy_last_value,
        ]
        debug["strategy_names"] = [getattr(fn, "__name__", "<unknown>") for fn in strategies]

        results: List[eb.StrategyResult] = []
        for fn in strategies:
            try:
                results.append(fn(lines))
            except Exception as e:
                results.append(
                    eb.StrategyResult(
                        name=getattr(fn, "__name__", "unknown"),
                        lancamentos=[],
                        matched_lines=0,
                        discarded_lines=0,
                        notes=[f"strategy crashed: {e!r}"],
                    )
                )

        chosen = eb._choose_best(results)
        debug["chosen_strategy"] = chosen.name
        debug["strategy_scores"] = [
            {
                "name": r.name,
                "tx": len(r.lancamentos),
                "matched": r.matched_lines,
                "discarded": r.discarded_lines,
                "score": eb._score_strategy(r),
                "notes": r.notes,
            }
            for r in results
        ]
        debug["created_at"] = datetime.utcnow().isoformat() + "Z"

        return {"lancamentos": chosen.lancamentos, "debug": debug}

    except Exception as e:
        debug["chosen_strategy"] = "crashed"
        debug["strategy_scores"] = [{"name": "analyze_extrato_bancario_from_text", "error": repr(e)}]
        debug["created_at"] = datetime.utcnow().isoformat() + "Z"
        return {"lancamentos": [], "debug": debug}
