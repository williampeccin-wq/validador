from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def extract_nome(raw_text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Extrai o NOME do condutor de forma determinística.

    Ordem:
      1) MRZ (linhas com '<<') — forte e normalmente presente em CNH exportada
      2) Campo visual (ancorado em rótulo NOME/NAME) — fallback

    Retorna (nome, dbg).
    """
    dbg: Dict[str, Any] = {
        "field": "nome",
        "method": None,
        "mrz": {},
        "label": {},
        "candidates": [],
        "chosen": None,
    }

    text = _normalize_text(raw_text)

    mrz_name, mrz_dbg = _extract_nome_from_mrz(text)
    dbg["mrz"] = mrz_dbg
    if mrz_name:
        dbg["method"] = "mrz"
        dbg["chosen"] = mrz_name
        return mrz_name, dbg

    label_name, label_dbg = _extract_nome_from_label(text)
    dbg["label"] = label_dbg
    if label_name:
        dbg["method"] = "label"
        dbg["chosen"] = label_name
        return label_name, dbg

    dbg["method"] = "none"
    return None, dbg


# -------------------------
# Internals
# -------------------------

_MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{10,}$")
_ONLY_LETTERS_SPACES_RE = re.compile(r"[^A-ZÀ-Ü ]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")

# NOTE: removi "UF" daqui (não faz sentido como substring; quebrava FANDARUFF)
_EXCLUDE_SUBSTRINGS = (
    "REPUBLICA",
    "FEDERATIVA",
    "BRASIL",
    "CARTEIRA",
    "NACIONAL",
    "HABILITACAO",
    "HABILITAÇÃO",
    "DOCUMENTO",
    "REGISTRO",
    "VALIDADE",
    "CATEGORIA",
    "CATEGORY",
    "FILIA",
    "FILIAÇÃO",
    "FILIACAO",
    "MAE",
    "MÃE",
    "PAI",
    "ASSINATURA",
    "EMISSAO",
    "EMISSÃO",
    "NASC",
    "NASCIMENTO",
    "DATA",
    "LOCAL",
    "PLACE",
    "NATURALIDADE",
)

# tokens curtos: só bloquear se for palavra inteira
_EXCLUDE_SHORT_WORDS = ("CPF", "RG", "DOC", "CNH", "UF")

_LABEL_RE = re.compile(
    r"(?im)^\s*(?:NOME|NAME)\b"
    r"(?:\s*/\s*(?:NOME|NAME)\b)?"
    r"\s*[:\-]?\s*(?P<inline>.*)$"
)


def _extract_nome_from_label(text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    lines = _lines(text)
    dbg: Dict[str, Any] = {"hit_line": None, "inline": None, "next_line": None}

    for i, line in enumerate(lines):
        m = _LABEL_RE.match(line)
        if not m:
            continue

        dbg["hit_line"] = line
        inline = (m.group("inline") or "").strip()
        dbg["inline"] = inline or None

        cand_inline = _clean_name_candidate(inline)
        if _is_valid_name_candidate(cand_inline):
            return cand_inline, dbg

        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        dbg["next_line"] = next_line or None
        cand_next = _clean_name_candidate(next_line)
        if _is_valid_name_candidate(cand_next):
            return cand_next, dbg

        nxt2 = lines[i + 2].strip() if i + 2 < len(lines) else ""
        joined = (next_line + " " + nxt2).strip()
        cand_joined = _clean_name_candidate(joined)
        if _is_valid_name_candidate(cand_joined):
            dbg["next_line_2"] = nxt2 or None
            return cand_joined, dbg

        return None, dbg

    return None, dbg


def _extract_nome_from_mrz(text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    lines = _lines(text)
    dbg: Dict[str, Any] = {
        "mrz_lines": [],
        "picked": None,
        "parsed": None,
        "candidates": {},
        "decision": None,
        "reason": None,
    }

    mrz_candidates: List[str] = []
    for ln in lines:
        s = ln.strip().upper().replace(" ", "")
        if "<<" not in s:
            continue
        if _MRZ_LINE_RE.match(s):
            mrz_candidates.append(s)

    dbg["mrz_lines"] = mrz_candidates[:10]
    if not mrz_candidates:
        dbg["reason"] = "no_mrz_candidates"
        return None, dbg

    # Escolhe a linha com maior densidade de letras (linha do nome tende a ganhar)
    mrz_line = max(mrz_candidates, key=_mrz_score_line)
    dbg["picked"] = mrz_line

    parsed, parsed_dbg = _parse_mrz_name(mrz_line, full_text=text)
    dbg["parsed"] = parsed
    dbg["candidates"] = parsed_dbg.get("candidates", {})
    dbg["decision"] = parsed_dbg.get("decision")

    if not parsed:
        dbg["reason"] = parsed_dbg.get("reason") or "parse_failed"
        return None, dbg

    candidate = _clean_name_candidate(parsed)
    if _is_valid_name_candidate(candidate):
        return candidate, dbg

    dbg["reason"] = "invalid_after_clean"
    return None, dbg


def _mrz_score_line(s: str) -> Tuple[int, int, int]:
    up = s.upper()
    letters = sum(1 for ch in up if "A" <= ch <= "Z")
    seps = up.count("<")
    digits = sum(1 for ch in up if "0" <= ch <= "9")
    return (letters, seps, -digits)


def _parse_mrz_name(mrz_line: str, *, full_text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Tenta duas interpretações:

    A) passaporte: SOBRENOME<<NOMES<...   -> retorna "PRIMEIRO_NOME SOBRENOME"
    B) CNH fixtures: NOME<<SOBRENOME<SOBRENOME2<... -> retorna "NOME SOBRENOME SOBRENOME2"

    Decisão determinística:
      - Gera candidato A e B
      - Valida ambos
      - Pontua por presença dos tokens em linhas NÃO-MRZ (sem '<')
      - Maior score ganha; empate -> A (para satisfazer unit tests sem texto extra)
    """
    dbg: Dict[str, Any] = {"candidates": {}, "decision": None, "reason": None}

    s = mrz_line.upper()
    if "<<" not in s:
        dbg["reason"] = "no_double_sep"
        return None, dbg

    parts = s.split("<<")
    if len(parts) < 2:
        dbg["reason"] = "split_failed"
        return None, dbg

    left_raw = parts[0]
    right_raw = parts[1]

    # remove prefixo antes do último '<' do lado esquerdo (ex.: "I<BRA...<<")
    if "<" in left_raw:
        left_raw = left_raw.split("<")[-1]

    left_tokens = _mrz_tokens(left_raw)
    right_tokens = _mrz_tokens(right_raw)

    if not left_tokens or not right_tokens:
        dbg["reason"] = "no_tokens"
        return None, dbg

    # candidato A: PRIMEIRO_NOME (do right) + SOBRENOME(s) (do left)
    cand_a_tokens = [right_tokens[0]] + left_tokens
    cand_a = " ".join(cand_a_tokens).strip()

    # candidato B: NOME(s) (left) + SOBRENOME(s) (right)
    cand_b_tokens = left_tokens + right_tokens
    cand_b = " ".join(cand_b_tokens).strip()

    dbg["candidates"]["A"] = {"value": cand_a, "tokens": cand_a_tokens}
    dbg["candidates"]["B"] = {"value": cand_b, "tokens": cand_b_tokens}

    # texto não-MRZ para scoring (linhas sem '<')
    non_mrz_text = " ".join(
        ln.upper() for ln in _lines(full_text) if "<" not in (ln or "")
    )

    def score(tokens: List[str]) -> int:
        if not non_mrz_text.strip():
            return 0
        return sum(1 for t in tokens if t and t in non_mrz_text)

    # validação básica antes de escolher
    a_ok = _is_valid_name_candidate(_clean_name_candidate(cand_a))
    b_ok = _is_valid_name_candidate(_clean_name_candidate(cand_b))

    dbg["candidates"]["A"]["valid"] = a_ok
    dbg["candidates"]["B"]["valid"] = b_ok

    # se só um é válido, escolhe ele
    if a_ok and not b_ok:
        dbg["decision"] = "A_only_valid"
        return cand_a, dbg
    if b_ok and not a_ok:
        dbg["decision"] = "B_only_valid"
        return cand_b, dbg
    if not a_ok and not b_ok:
        dbg["decision"] = "none_valid"
        dbg["reason"] = "both_invalid"
        return None, dbg

    # ambos válidos: escolhe por score
    sa = score(cand_a_tokens)
    sb = score(cand_b_tokens)
    dbg["candidates"]["A"]["score"] = sa
    dbg["candidates"]["B"]["score"] = sb

    if sb > sa:
        dbg["decision"] = "B_by_score"
        return cand_b, dbg
    if sa > sb:
        dbg["decision"] = "A_by_score"
        return cand_a, dbg

    # empate -> A (unit tests sem contexto extra)
    dbg["decision"] = "A_by_tie"
    return cand_a, dbg


def _mrz_tokens(chunk: str) -> List[str]:
    c = chunk
    if "<<<" in c:
        c = c.split("<<<", 1)[0]

    raw = [t for t in c.split("<") if t]
    out: List[str] = []
    for t in raw:
        if any(ch.isdigit() for ch in t):
            continue
        letters = re.sub(r"[^A-ZÀ-Ü]", "", t)
        if len(letters) < 2:
            continue
        out.append(letters)
    return out


def _normalize_text(raw_text: str) -> str:
    t = (raw_text or "").replace("\x00", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    return t


def _lines(text: str) -> List[str]:
    return [ln.rstrip("\n") for ln in text.split("\n")]


def _clean_name_candidate(s: str) -> Optional[str]:
    if not s:
        return None
    up = s.upper().strip()
    up = _ONLY_LETTERS_SPACES_RE.sub(" ", up)
    up = _MULTI_SPACE_RE.sub(" ", up).strip()
    up = " ".join(tok for tok in up.split(" ") if tok)
    return up or None


def _has_short_word(haystack_upper: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", haystack_upper) is not None


def _is_valid_name_candidate(name: Optional[str]) -> bool:
    if not name:
        return False
    if len(name) < 5:
        return False

    toks = name.split()
    if len(toks) < 2:
        return False

    up = name.upper()

    # bloqueios por palavra inteira (curtos)
    for w in _EXCLUDE_SHORT_WORDS:
        if _has_short_word(up, w):
            return False

    # bloqueios por substring (longos)
    for bad in _EXCLUDE_SUBSTRINGS:
        if bad in up:
            return False

    letters = re.sub(r"[^A-ZÀ-Ü]+", "", up)
    if len(letters) < 6:
        return False

    return True
