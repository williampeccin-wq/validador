# parsers/cnh.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# Normalização básica (contrato do golden)
# ============================================================

_NAME_JOINERS = {"DE", "DA", "DO", "DAS", "DOS", "E"}

_OCR_DIGIT_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "S": "5",
        "B": "8",
        "Z": "2",
        "G": "6",
    }
)


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _upper(s: str) -> str:
    return _strip_accents(s or "").upper()


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _cleanup_name(s: str) -> Optional[str]:
    if not s:
        return None

    u = _upper(s)
    u = re.sub(r"[^A-Z0-9 ]+", " ", u)
    u = _collapse_spaces(u)
    if not u:
        return None

    toks = u.split()
    cleaned: List[str] = []
    for t in toks:
        if t in _NAME_JOINERS:
            cleaned.append(t)
            continue
        if len(t) <= 2:
            continue
        cleaned.append(t)

    while cleaned and cleaned[0] in _NAME_JOINERS:
        cleaned.pop(0)
    while cleaned and cleaned[-1] in _NAME_JOINERS:
        cleaned.pop()

    collapsed: List[str] = []
    for t in cleaned:
        if collapsed and t in _NAME_JOINERS and collapsed[-1] in _NAME_JOINERS:
            continue
        collapsed.append(t)

    out = " ".join(collapsed).strip()
    return out or None


def _title_city(s: str) -> Optional[str]:
    if not s:
        return None
    u = _upper(s)
    u = re.sub(r"[^A-Z ]+", " ", u)
    u = _collapse_spaces(u)
    if not u:
        return None
    return u.title()


# ============================================================
# Datas dd/mm/yyyy
# ============================================================

def _find_dates_ddmmyyyy(text: str) -> List[str]:
    return re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", _upper(text))


def _parse_date_ddmmyyyy(d: str) -> Optional[date]:
    try:
        dd, mm, yyyy = d.split("/")
        return date(int(yyyy), int(mm), int(dd))
    except Exception:
        return None


# ============================================================
# CPF (checksum + tolerância OCR + sliding window)
# ============================================================

def _normalize_ocr_digits(s: str) -> str:
    if not s:
        return ""
    u = _upper(s)
    return u.translate(_OCR_DIGIT_TRANSLATION)


def _cpf_is_valid(cpf11: str) -> bool:
    if not cpf11 or len(cpf11) != 11 or not cpf11.isdigit():
        return False
    if cpf11 == cpf11[0] * 11:
        return False

    nums = [int(c) for c in cpf11]

    s1 = sum(nums[i] * (10 - i) for i in range(9))
    dv1 = (s1 * 10) % 11
    dv1 = 0 if dv1 == 10 else dv1
    if dv1 != nums[9]:
        return False

    s2 = sum(nums[i] * (11 - i) for i in range(10))
    dv2 = (s2 * 10) % 11
    dv2 = 0 if dv2 == 10 else dv2
    return dv2 == nums[10]


def _cpf_candidates_from_digit_stream(digits: str) -> List[str]:
    """
    Extrai candidatos por janela móvel de 11 dígitos em um stream contínuo.
    Retorna todos os CPFs válidos (checksum ok) na ordem em que aparecem.
    """
    out: List[str] = []
    if not digits or len(digits) < 11:
        return out

    for i in range(0, len(digits) - 10):
        cand = digits[i : i + 11]
        if _cpf_is_valid(cand):
            # evita duplicado imediato
            if not out or out[-1] != cand:
                out.append(cand)
    return out


def _extract_cpf(text: str) -> Optional[str]:
    """
    Estratégia robusta:
      1) procurar âncora "CPF" e olhar uma janela de caracteres depois dela
         - normaliza OCR->dígitos
         - gera stream de dígitos contínuo e faz sliding window
      2) fallback: varre o documento inteiro (stream contínuo) e faz sliding window
    """
    if not text:
        return None

    norm = _normalize_ocr_digits(text)

    # 1) Âncoras "CPF" (janela de 200 caracteres após a âncora)
    for m in re.finditer(r"\bCPF\b", norm):
        start = m.end()
        chunk = norm[start : start + 200]
        digits = re.sub(r"[^0-9]", "", chunk)
        cands = _cpf_candidates_from_digit_stream(digits)
        if cands:
            return cands[0]

    # 2) Fallback global: stream contínuo
    digits_all = re.sub(r"[^0-9]", "", norm)
    cands_all = _cpf_candidates_from_digit_stream(digits_all)
    if cands_all:
        return cands_all[0]

    return None


# ============================================================
# Nome / Nascimento / Local / Validade / Filiação
# ============================================================

def _extract_nome(text: str) -> Tuple[Optional[str], str]:
    u = _upper(text)

    m = re.search(r"\[\s*([A-Z][A-Z ]{8,80}?)\s*\]", u)
    if m:
        nm = _cleanup_name(m.group(1))
        return nm, "brackets"

    m = re.search(r"NOME\s+E\s+SOBRENOME.*?\n([A-Z][A-Z ]{8,80})", u, flags=re.DOTALL)
    if m:
        nm = _cleanup_name(m.group(1))
        return nm, "label_line"

    lines = [ln.strip() for ln in u.splitlines() if ln.strip()]
    for ln in lines[:12]:
        if len(ln) < 12:
            continue
        if any(ch.isdigit() for ch in ln):
            continue
        cand = _cleanup_name(ln)
        if cand and len(cand.split()) >= 2:
            return cand, "topline"

    return None, "none"


def _extract_nascimento_cidade_uf(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    u = _upper(text)

    m = re.search(
        r"DATA,\s*LOCAL\s*E\s*UF\s*DE\s*NASCIMENTO.*?(\d{2}/\d{2}/\d{4})\s*,\s*([A-Z ]{3,60})\s*,\s*([A-Z]{2})",
        u,
        flags=re.DOTALL,
    )
    if m:
        nasc = m.group(1)
        city = _title_city(m.group(2))
        uf = m.group(3)
        return nasc, city, uf, "anchored"

    m = re.search(r"(\d{2}/\d{2}/\d{4})\s*,\s*([A-Z ]{3,60})\s*,\s*([A-Z]{2})", u)
    if m:
        nasc = m.group(1)
        city = _title_city(m.group(2))
        uf = m.group(3)
        return nasc, city, uf, "fallback_tuple"

    return None, None, None, "none"


def _extract_validade(text: str) -> Tuple[Optional[str], str]:
    dates = _find_dates_ddmmyyyy(text)
    parsed: List[Tuple[date, str]] = []
    for d in dates:
        dd = _parse_date_ddmmyyyy(d)
        if dd:
            parsed.append((dd, d))

    if not parsed:
        return None, "none"

    parsed.sort(key=lambda x: x[0])
    return parsed[-1][1], "max_date"


def _extract_filiacao(text: str) -> Tuple[List[str], str]:
    u = _upper(text)
    lines = [ln.strip() for ln in u.splitlines() if ln.strip()]

    for i, ln in enumerate(lines):
        if "FILIA" in ln:
            out: List[str] = []
            for j in range(i + 1, min(i + 12, len(lines))):
                cand = _cleanup_name(lines[j])
                if not cand:
                    continue
                if "ASSINATURA" in cand or "OBSERV" in cand or "DOCUMENTO" in cand:
                    continue
                if cand not in out:
                    out.append(cand)
                if len(out) >= 2:
                    break
            return out[:2], "lines_after_label"

    m = re.search(r"FILIA[ÇC]AO(.{0,650})", u, flags=re.DOTALL)
    if m:
        chunk = m.group(1)
        chunk_lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        out: List[str] = []
        for ln in chunk_lines[:12]:
            cand = _cleanup_name(ln)
            if cand and cand not in out:
                out.append(cand)
            if len(out) >= 2:
                break
        return out[:2], "regex_block"

    return [], "none"


# ============================================================
# Contrato (mantém exatamente as chaves do golden)
# ============================================================

@dataclass
class CNHResult:
    nome: Optional[str] = None
    cpf: Optional[str] = None
    data_nascimento: Optional[str] = None
    cidade_nascimento: Optional[str] = None
    uf_nascimento: Optional[str] = None
    validade: Optional[str] = None
    filiacao: List[str] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)


class CNHParser:
    def parse_text(self, text: str) -> CNHResult:
        t = text or ""

        nome, nome_src = _extract_nome(t)
        cpf = _extract_cpf(t)

        nasc, city, uf, nasc_src = _extract_nascimento_cidade_uf(t)
        validade, val_src = _extract_validade(t)

        filiacao, fil_src = _extract_filiacao(t)

        dbg = {
            "text_len": len(t),
            "sources": {
                "nome": nome_src,
                "cpf": "sliding_window_checksum_with_anchor",
                "nascimento": nasc_src,
                "validade": val_src,
                "filiacao": fil_src,
            },
        }

        return CNHResult(
            nome=nome,
            cpf=cpf,
            data_nascimento=nasc,
            cidade_nascimento=city,
            uf_nascimento=uf,
            validade=validade,
            filiacao=filiacao,
            debug=dbg,
        )

    def to_dict(self, result: CNHResult) -> Dict[str, Any]:
        d = asdict(result)
        d["debug"] = d.get("debug") or {}
        d["filiacao"] = d.get("filiacao") or []
        return d


def analyze_cnh(
    *,
    raw_text: str,
    filename: Optional[str] = None,
    use_gemini: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    parser = CNHParser()
    res = parser.parse_text(raw_text or "")
    d = parser.to_dict(res)
    dbg = d.pop("debug", {}) or {}
    return d, dbg
