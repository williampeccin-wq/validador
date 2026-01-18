# parsers/cnh_senatran.py
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

from parsers.cnh import analyze_cnh


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def _upper_noacc(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return _norm_spaces(s).upper()


def _extract_categoria(text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    CNH SENATRAN (layout fixo) normalmente contém "CATEGORIA".
    Captura categorias típicas: A, B, AB, AC, AD, AE, C, D, E.
    """
    u = _upper_noacc(text)

    patterns = [
        r"\bCATEGORIA\b[^\w]{0,12}\b(AB|AC|AD|AE|A|B|C|D|E)\b",
        r"\bCAT\.?\b[^\w]{0,12}\b(AB|AC|AD|AE|A|B|C|D|E)\b",
        r"\bCATEG\b[^\w]{0,12}\b(AB|AC|AD|AE|A|B|C|D|E)\b",
    ]

    for pat in patterns:
        m = re.search(pat, u, flags=re.IGNORECASE)
        if m:
            cat = (m.group(1) or "").strip().upper()
            return cat, {"source": "regex", "pattern": pat, "match": m.group(0)}

    return None, {"source": "none"}


def analyze_cnh_senatran(
    *,
    raw_text: str,
    filename: Optional[str] = None,
    use_gemini: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Parser dedicado para CNH SENATRAN (layout fixo / documento imutável).

    Contrato mínimo para Phase 2 (CNH ↔ Proposta):
      - nome
      - cpf
      - validade
      - categoria

    Observação:
      - Reaproveita analyze_cnh (genérico) para nome/cpf/validade, e injeta categoria.
      - use_gemini default False para testes determinísticos.
    """
    base_fields, base_dbg = analyze_cnh(raw_text=raw_text or "", filename=filename, use_gemini=use_gemini)

    categoria, cat_dbg = _extract_categoria(raw_text or "")

    out = dict(base_fields or {})
    out["categoria"] = categoria

    dbg: Dict[str, Any] = {
        "base": base_dbg or {},
        "categoria": cat_dbg,
        "text_len": len(raw_text or ""),
    }
    return out, dbg
