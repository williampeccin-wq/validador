from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_ALLOWED_1 = {"A", "B", "C", "D", "E"}
_ALLOWED_2 = {"AB", "AC", "AD", "AE"}
_ALLOWED = _ALLOWED_1 | _ALLOWED_2

_RE_CAT_2 = re.compile(r"\b(AB|AC|AD|AE)\b", re.IGNORECASE)
_RE_CAT_1 = re.compile(r"\b([A-E])\b", re.IGNORECASE)

_RE_CPF_DOTTED = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_RE_11DIG = re.compile(r"\b\d{11}\b")

_RE_ANCHOR_CATHAB = re.compile(r"(?i)\bCAT(?:\.|\s*)HAB\b")
_RE_ANCHOR_CATEGORIA = re.compile(r"(?i)\bCATEG(?:ORIA|ORY)\b")

_AFTER_MAX_POS = 8
_AFTER_LEN = 40


def extract_categoria(raw_text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Estratégia (determinística, auditável):
      1) CAT.HAB header + próxima linha "pura" (ex.: 'AE')
         -> method: anchor_cat_hab_record_line (compat com testes)
      2) CAT.HAB header + linha seguinte contendo CPF/registro + categoria
         -> method: anchor_cat_hab_record_line (compat com testes)
      3) linha de registro (CPF + 11 dígitos) e categoria colada no after (<=8 chars)
         -> method: anchor_cat_hab_record_line (compat com testes)
      4) fallback âncora CATEGORIA + próxima linha -> method: anchor_categoria
      5) none
    """
    dbg: Dict[str, Any] = {
        "field": "categoria",
        "method": "none",
        "hit": None,
        "window": None,
        "candidates": [],
        "chosen": None,
        "reason": None,
        "after_max_pos": _AFTER_MAX_POS,
    }

    lines = _lines(_normalize_text(raw_text))
    if not lines:
        dbg["reason"] = "empty"
        return None, dbg

    # (1) CAT.HAB header + próxima linha pura (ou header+linha registro)
    cat, info = _scan_cat_hab_anchor(lines)
    if cat:
        dbg.update(info)
        dbg["method"] = "anchor_cat_hab_record_line"
        dbg["chosen"] = cat
        return cat, dbg

    # (2) record_line (CPF + registro) com regra after<=8
    cat, info = _scan_record_lines(lines)
    if cat:
        dbg.update(info)
        dbg["method"] = "anchor_cat_hab_record_line"
        dbg["chosen"] = cat
        return cat, dbg

    # (3) fallback "CATEGORIA"
    cat, info = _scan_categoria_anchor(lines)
    if cat:
        dbg.update(info)
        dbg["method"] = "anchor_categoria"
        dbg["chosen"] = cat
        return cat, dbg

    dbg["reason"] = "not_found"
    return None, dbg


# -----------------------
# internals
# -----------------------

def _normalize_text(raw_text: str) -> str:
    t = (raw_text or "").replace("\x00", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    return t


def _lines(text: str) -> list[str]:
    return [ln.rstrip("\n") for ln in (text or "").split("\n")]


def _upper(s: str) -> str:
    return (s or "").upper()


def _only_digits_mask(u: str) -> str:
    return re.sub(r"\D", " ", u)


def _extract_after_registro(u: str, registro_end: int) -> str:
    return u[registro_end : registro_end + _AFTER_LEN]


def _pure_value(line: str) -> Optional[str]:
    if not line:
        return None
    u = re.sub(r"[^A-Z]", " ", _upper(line))
    toks = [t for t in u.split() if t]
    if len(toks) != 1:
        return None
    tok = toks[0]
    return tok if tok in _ALLOWED else None


def _pick_from_after(after: str) -> Tuple[Optional[str], List[str], str, Optional[int]]:
    if not after:
        return None, [], "empty_after", None

    found: List[Tuple[int, int, str]] = []
    all_cands: List[str] = []

    for m in _RE_CAT_2.finditer(after):
        cand = m.group(1).upper()
        pos = m.start(1)
        all_cands.append(cand)
        if pos <= _AFTER_MAX_POS:
            found.append((pos, 0, cand))

    toks = [(m.group(1).upper(), m.start(1)) for m in _RE_CAT_1.finditer(after)]
    for i in range(len(toks) - 1):
        c1, p1 = toks[i]
        c2, p2 = toks[i + 1]
        if p1 > _AFTER_MAX_POS:
            continue
        if p2 - p1 > 4:
            continue
        pair = c1 + c2
        all_cands.append(pair)
        if pair in _ALLOWED_2 and p1 <= _AFTER_MAX_POS:
            found.append((p1, 0, pair))

    for m in _RE_CAT_1.finditer(after):
        cand = m.group(1).upper()
        pos = m.start(1)
        all_cands.append(cand)
        if pos <= _AFTER_MAX_POS:
            found.append((pos, 1, cand))

    if not found:
        return None, all_cands, "no_candidate_within_after_max_pos", None

    found.sort(key=lambda x: (x[0], x[1], 0 if len(x[2]) == 2 else 1))
    chosen = found[0][2]
    chosen_pos = found[0][0]

    if chosen not in _ALLOWED:
        return None, all_cands, "invalid_chosen", chosen_pos

    return chosen, all_cands, "picked_by_after_near_registro", chosen_pos


def _scan_cat_hab_anchor(lines: list[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Cobre:
      - "9 CAT.HAB\nAE\n" (próxima linha pura)
      - "4d ... CAT.HAB\n<linha do registro com CPF + 11 + categoria>"
    """
    info: Dict[str, Any] = {"hit": None, "window": None, "candidates": [], "reason": None}

    for i, ln in enumerate(lines):
        if not _RE_ANCHOR_CATHAB.search(ln or ""):
            continue

        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        info["hit"] = {"anchor": "cat_hab", "line_index": i, "line": ln}
        info["window"] = [ln, nxt]

        # 1) próxima linha pura
        pure = _pure_value(nxt)
        if pure:
            info["candidates"] = [pure]
            info["reason"] = "pure_next_line"
            return pure, info

        # 2) próxima linha é record_line (CPF + 11digits) -> extrai do AFTER do registro
        u = _upper(nxt)
        if _RE_CPF_DOTTED.search(u):
            mask = _only_digits_mask(u)
            blocks = list(_RE_11DIG.finditer(mask))
            if blocks:
                reg = blocks[-1]
                after = _extract_after_registro(u, reg.end())
                cat, cands, reason, pos = _pick_from_after(after)
                if cat:
                    info["candidates"] = cands
                    info["reason"] = "cat_hab_header_then_record_line"
                    info["after"] = after
                    info["after_pos"] = pos
                    return cat, info

        info["reason"] = "anchor_found_but_no_candidate"
        return None, info

    info["reason"] = "anchor_not_found"
    return None, info


def _scan_record_lines(lines: list[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    best: Optional[Tuple[int, int, str, Dict[str, Any]]] = None

    for i, ln in enumerate(lines):
        u = _upper(ln)
        if not _RE_CPF_DOTTED.search(u):
            continue

        mask = _only_digits_mask(u)
        blocks = list(_RE_11DIG.finditer(mask))
        if not blocks:
            continue

        reg = blocks[-1]
        after = _extract_after_registro(u, reg.end())

        cat, cands, reason, pos = _pick_from_after(after)
        if not cat:
            continue

        prefer = 0 if len(cat) == 2 else 1
        info: Dict[str, Any] = {
            "hit": {"anchor": "record_line", "line_index": i, "line": ln},
            "window": [ln],
            "candidates": cands,
            "reason": reason,
            "after": after,
            "after_pos": pos,
        }

        if best is None or (pos, prefer) < (best[0], best[1]):
            best = (pos if pos is not None else 9999, prefer, cat, info)

    if best:
        return best[2], best[3]

    return None, {"reason": "no_record_lines_matched"}


def _scan_categoria_anchor(lines: list[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    info: Dict[str, Any] = {"hit": None, "window": None, "candidates": [], "reason": None}

    for i, ln in enumerate(lines):
        if not _RE_ANCHOR_CATEGORIA.search(ln or ""):
            continue

        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        info["hit"] = {"anchor": "categoria", "line_index": i, "line": ln}
        info["window"] = [ln, nxt]

        pure = _pure_value(nxt)
        if pure:
            info["candidates"] = [pure]
            info["reason"] = "pure_next_line"
            return pure, info

        u = _RE_ANCHOR_CATEGORIA.sub(" ", _upper(ln))
        m2 = _RE_CAT_2.search(u)
        if m2:
            cand = m2.group(1).upper()
            info["candidates"] = [cand]
            info["reason"] = "inline_combo"
            return cand, info
        m1 = _RE_CAT_1.search(u)
        if m1:
            cand = m1.group(1).upper()
            info["candidates"] = [cand]
            info["reason"] = "inline_single"
            return cand, info

        info["reason"] = "anchor_found_but_no_candidate"
        return None, info

    info["reason"] = "anchor_not_found"
    return None, info
