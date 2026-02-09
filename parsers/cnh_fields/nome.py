from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def extract_nome(raw_text: str) -> Tuple[Optional[str], Dict[str, Any]]:
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
        "considered": [],
    }

    mrz_candidates: List[str] = []
    for ln in lines:
        s = ln.strip().upper().replace(" ", "")
        if "<<" not in s:
            continue
        if _MRZ_LINE_RE.match(s):
            mrz_candidates.append(s)

    dbg["mrz_lines"] = mrz_candidates[:20]
    if not mrz_candidates:
        dbg["reason"] = "no_mrz_candidates"
        return None, dbg

    context_has_doc_header = any(s.startswith("I<BRA") or s.startswith("P<BRA") for s in mrz_candidates)

    # Texto NÃO-MRZ para scoring (linhas sem '<'): aproxima do “visual”
    non_mrz_text = " ".join(ln.upper() for ln in lines if "<" not in (ln or "")).strip()

    # Considera apenas linhas que parecem “linha de nome”:
    # - tem '<<'
    # - não começa com I<... ou P<... (header)
    # - não é a linha “numérica” (muitos dígitos)
    name_lines = []
    for s in mrz_candidates:
        if s.startswith("I<") or s.startswith("P<"):
            continue
        digits = sum(1 for ch in s if ch.isdigit())
        if digits >= 8:
            continue
        name_lines.append(s)

    if not name_lines:
        dbg["reason"] = "no_name_like_mrz_lines"
        return None, dbg

    best: Optional[Dict[str, Any]] = None

    for s in name_lines:
        picked_is_doc_header = s.startswith("I<") or s.startswith("P<")

        parsed, parsed_dbg = _parse_mrz_name(
            s,
            full_text=text,
            context_has_doc_header=context_has_doc_header,
            picked_is_doc_header=picked_is_doc_header,
        )

        if not parsed:
            dbg["considered"].append(
                {
                    "line": s,
                    "ok": False,
                    "decision": parsed_dbg.get("decision"),
                    "reason": parsed_dbg.get("reason"),
                }
            )
            continue

        cleaned = _clean_name_candidate(parsed)
        if not _is_valid_name_candidate(cleaned):
            dbg["considered"].append(
                {
                    "line": s,
                    "ok": False,
                    "decision": parsed_dbg.get("decision"),
                    "reason": "invalid_after_clean",
                    "parsed": parsed,
                }
            )
            continue

        chosen_side = "A" if str(parsed_dbg.get("decision", "")).startswith("A") else "B"
        tokens = []
        cand = parsed_dbg.get("candidates", {}).get(chosen_side, {})
        if isinstance(cand, dict):
            tokens = cand.get("tokens") or []
        if not isinstance(tokens, list):
            tokens = []

        score = _token_hit_score(non_mrz_text, tokens)

        item = {
            "line": s,
            "ok": True,
            "parsed": cleaned,
            "decision": parsed_dbg.get("decision"),
            "score": score,
            "tokens": tokens,
        }
        dbg["considered"].append(item)

        if best is None:
            best = item
        else:
            # maior score ganha
            if item["score"] > best["score"]:
                best = item
            elif item["score"] == best["score"]:
                # tie determinístico: preferir a linha que aparece primeiro no MRZ block
                # (estável e auditável, e tende a escolher a primeira ocorrência “boa”)
                best = best

    if not best:
        dbg["reason"] = "no_valid_parsed_candidate"
        return None, dbg

    dbg["picked"] = best["line"]
    dbg["parsed"] = best["parsed"]
    dbg["decision"] = best["decision"]
    dbg["candidates"] = {"selected": {"tokens": best.get("tokens"), "score": best.get("score")}}

    return best["parsed"], dbg


def _token_hit_score(non_mrz_text: str, tokens: List[str]) -> int:
    if not non_mrz_text or not tokens:
        return 0
    return sum(1 for t in tokens if isinstance(t, str) and t and t in non_mrz_text)


def _parse_mrz_name(
    mrz_line: str,
    *,
    full_text: str,
    context_has_doc_header: bool,
    picked_is_doc_header: bool,
) -> Tuple[Optional[str], Dict[str, Any]]:
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

    if "<" in left_raw:
        left_raw = left_raw.split("<")[-1]

    left_tokens = _mrz_tokens(left_raw)
    right_tokens = _mrz_tokens(right_raw)

    if not left_tokens or not right_tokens:
        dbg["reason"] = "no_tokens"
        return None, dbg

    cand_a_tokens = [right_tokens[0]] + left_tokens
    cand_a = " ".join(cand_a_tokens).strip()

    cand_b_tokens = left_tokens + right_tokens
    cand_b = " ".join(cand_b_tokens).strip()

    dbg["candidates"]["A"] = {"value": cand_a, "tokens": cand_a_tokens}
    dbg["candidates"]["B"] = {"value": cand_b, "tokens": cand_b_tokens}

    non_mrz_lines = [ln.upper() for ln in _lines(full_text) if "<" not in (ln or "")]
    non_mrz_text = " ".join(non_mrz_lines)

    def score(tokens: List[str]) -> int:
        if not non_mrz_text.strip():
            return 0
        return sum(1 for t in tokens if t and t in non_mrz_text)

    a_ok = _is_valid_name_candidate(_clean_name_candidate(cand_a))
    b_ok = _is_valid_name_candidate(_clean_name_candidate(cand_b))

    dbg["candidates"]["A"]["valid"] = a_ok
    dbg["candidates"]["B"]["valid"] = b_ok

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

    if context_has_doc_header and not picked_is_doc_header:
        if not non_mrz_text.strip() and len(left_tokens) == 1 and len(right_tokens) >= 2:
            dbg["decision"] = "A_by_tie_passport_shape"
            return cand_a, dbg

        if len(right_tokens) > len(left_tokens) and non_mrz_text.strip():
            dbg["decision"] = "B_by_tie_cnh_tokens"
            return cand_b, dbg

        if non_mrz_text.strip():
            left_first = left_tokens[0]
            right_first = right_tokens[0]
            pos_left = non_mrz_text.find(left_first) if left_first else -1
            pos_right = non_mrz_text.find(right_first) if right_first else -1
            dbg["candidates"]["tie_positions"] = {"left": pos_left, "right": pos_right}

            if pos_left != -1 and pos_right != -1:
                if pos_left < pos_right:
                    dbg["decision"] = "B_by_tie_cnh_order"
                    return cand_b, dbg
                if pos_right < pos_left:
                    dbg["decision"] = "A_by_tie_cnh_order"
                    return cand_a, dbg

        dbg["decision"] = "A_by_tie"
        return cand_a, dbg

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

    for w in _EXCLUDE_SHORT_WORDS:
        if _has_short_word(up, w):
            return False

    for bad in _EXCLUDE_SUBSTRINGS:
        if bad in up:
            return False

    letters = re.sub(r"[^A-ZÀ-Ü]+", "", up)
    if len(letters) < 6:
        return False

    return True
