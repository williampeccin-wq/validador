from __future__ import annotations

import re
from typing import Any, Optional, Tuple

# Categorias CNH (inclui combinações mais comuns)
_VALID_CATS = ("AB", "AC", "AD", "AE", "B", "C", "D", "E", "A")
_RE_CAT = re.compile(r"\b(AB|AC|AD|AE|B|C|D|E|A)\b")

_RE_11 = re.compile(r"\b\d{11}\b")
_RE_CPF_FMT = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")

# "CAT.HAB", "CAT HAB", "CATHAB" etc (robusto a ruído e pontuação)
def _compact(u: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (u or "").upper())


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _upper(s: str) -> str:
    return _norm_spaces(s).upper()


def _safe_get(lines: list[str], idx: int) -> str:
    if 0 <= idx < len(lines):
        return lines[idx]
    return ""


def _is_pure_cat_line(u: str) -> Optional[str]:
    """
    Linha com valor "puro" da categoria (ex.: "AE", "AB", "B")
    """
    u = _upper(u)
    if not u:
        return None
    # remove wrappers comuns: parênteses, pipes etc.
    u2 = re.sub(r"^[\s\(\[\{<\|]+", "", u)
    u2 = re.sub(r"[\s\)\]\}>\|]+$", "", u2)
    u2 = _upper(u2)
    if u2 in _VALID_CATS:
        return u2
    return None


def _pick_cat_by_earliest(after_u: str) -> Tuple[Optional[str], dict]:
    """
    Escolhe a categoria pela PRIMEIRA ocorrência (menor índice) no trecho "after".
    Isso evita regressão tipo: "B | Cm E E LT" virar "E".
    """
    after_u = after_u or ""
    hits = []
    for m in _RE_CAT.finditer(after_u):
        cat = m.group(1)
        if cat in _VALID_CATS:
            hits.append((m.start(), cat))

    dbg: dict[str, Any] = {"after": after_u, "candidates": [c for _, c in hits]}

    if not hits:
        dbg["chosen"] = None
        return None, dbg

    hits.sort(key=lambda t: t[0])  # menor posição primeiro
    chosen = hits[0][1]
    dbg["chosen"] = chosen
    dbg["chosen_pos"] = hits[0][0]
    return chosen, dbg


def extract_categoria(raw_text: str) -> Tuple[Optional[str], dict]:
    """
    Retorna (categoria, dbg).

    Estratégia:
      1) Âncora CAT.HAB (várias formas) -> tenta linha seguinte "pura" (AE etc)
      2) Caso contrário, busca linha do REGISTRO (11 dígitos) próxima da âncora e pega categoria
         no trecho após o registro (earliest match).
      3) Fallback: rótulo "CATEGORIA" em linhas próximas.
    """
    lines = (raw_text or "").splitlines()
    dbg: dict[str, Any] = {"field": "categoria", "method": "none"}

    # 1) CAT.HAB anchors
    anchor_idxs: list[int] = []
    for i, ln in enumerate(lines):
        cu = _compact(ln)
        if "CAT" in cu and "HAB" in cu:
            anchor_idxs.append(i)

    for i in anchor_idxs:
        hit = {"anchor": "cat_hab", "line_index": i, "line": lines[i]}
        window = [lines[i], _safe_get(lines, i + 1), _safe_get(lines, i + 2), _safe_get(lines, i + 3)]
        # 1a) next line pure value (ex.: "AE")
        pure = _is_pure_cat_line(window[1])
        if pure:
            dbg2 = {
                "field": "categoria",
                "method": "anchor_cat_hab_next_line",
                "hit": hit,
                "window": window[:2],
                "candidates": [pure],
                "chosen": pure,
                "after_max_pos": 8,
            }
            return pure, dbg2

        # 1b) record line search near anchor
        # procura uma linha "de registro": tem cpf formatado OU pelo menos 11 dígitos; pegamos o ÚLTIMO bloco de 11
        best_line_idx: Optional[int] = None
        best_after: Optional[str] = None
        best_pick_dbg: Optional[dict] = None
        best_cat: Optional[str] = None

        for k in (i, i + 1, i + 2, i + 3):
            if not (0 <= k < len(lines)):
                continue
            u = _upper(lines[k])
            # precisa ter 11 dígitos (registro) em algum lugar
            mask = re.sub(r"\D", " ", u)
            blocks = list(_RE_11.finditer(mask))
            if not blocks:
                continue

            reg = blocks[-1]  # registro tende a ser o último 11-dígitos na linha
            # substr após o fim do "registro" (mesmo índice do mask, mas serve bem no u porque tamanhos iguais ao u? não)
            # Para não depender de alinhamento mask/u, usamos o índice do match dentro do mask apenas para estimar
            # e usamos uma heurística: pega um "tail" do u e escolhe earliest categoria nele.
            # Melhor: achar o próprio 11-dígitos no u e usar o último occurrence real.
            reg_digits = mask[reg.start() : reg.end()].replace(" ", "")
            if not reg_digits or len(reg_digits) != 11:
                continue

            # encontra a última ocorrência desses dígitos no u
            pos = u.rfind(reg_digits)
            if pos < 0:
                continue
            after_u = u[pos + len(reg_digits) : pos + len(reg_digits) + 40]
            cat, pick_dbg = _pick_cat_by_earliest(after_u)

            # se não achou categoria aqui, segue
            if not cat:
                continue

            # guarda o primeiro candidato bom; como _pick_cat_by_earliest já garante ordem,
            # preferimos a linha mais próxima do anchor e com categoria mais cedo no after.
            if best_cat is None:
                best_line_idx = k
                best_after = after_u
                best_pick_dbg = pick_dbg
                best_cat = cat
            else:
                # desempate: menor distância ao anchor, depois menor chosen_pos no after
                assert best_line_idx is not None and best_pick_dbg is not None
                dist_new = abs(k - i)
                dist_old = abs(best_line_idx - i)
                pos_new = int(pick_dbg.get("chosen_pos") or 10**9)
                pos_old = int(best_pick_dbg.get("chosen_pos") or 10**9)
                if (dist_new, pos_new) < (dist_old, pos_old):
                    best_line_idx = k
                    best_after = after_u
                    best_pick_dbg = pick_dbg
                    best_cat = cat

        if best_cat:
            dbg2 = {
                "field": "categoria",
                "method": "anchor_cat_hab_record_line",
                "hit": hit,
                "window": window[:3],
                "after": best_after,
                "candidates": (best_pick_dbg or {}).get("candidates") if isinstance(best_pick_dbg, dict) else [],
                "chosen": best_cat,
                "reason": "record_line_after_reg_earliest",
                "after_max_pos": 8,
            }
            # extra para debug (não quebra contrato)
            if isinstance(best_pick_dbg, dict):
                dbg2["pick_dbg"] = best_pick_dbg
                dbg2["record_line_index"] = best_line_idx
            return best_cat, dbg2

    # 2) Fallback: "CATEGORIA" label (simples)
    for i, ln in enumerate(lines):
        u = _upper(ln)
        if "CATEGORIA" in u:
            # tenta próxima linha como valor
            cand = _is_pure_cat_line(_safe_get(lines, i + 1))
            if cand:
                dbg2 = {
                    "field": "categoria",
                    "method": "anchor_categoria",
                    "hit": {"anchor": "categoria", "line_index": i, "line": ln},
                    "window": [ln, _safe_get(lines, i + 1)],
                    "candidates": [cand],
                    "chosen": cand,
                }
                return cand, dbg2

    return None, dbg
