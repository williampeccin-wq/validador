# validators/phase2/proposta_cnh_senatran_validator.py
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

JsonDict = Dict[str, Any]

_RE_DIGITS = re.compile(r"\d+")
_STOPWORDS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _only_digits(v: Optional[Any]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    digits = "".join(_RE_DIGITS.findall(s))
    return digits or None


def _remove_accents(txt: str) -> str:
    nfkd = unicodedata.normalize("NFKD", txt)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def _normalize_name_tokens(v: Optional[Any]) -> List[str]:
    """
    Tolerante (B):
      - remove acentos
      - uppercase
      - tokeniza por espaços
      - remove stopwords (DE/DA/DO/DAS/DOS/E)
    """
    if v is None:
        return []
    s = str(v).strip()
    if not s:
        return []
    s = _remove_accents(s).upper()
    s = re.sub(r"\s+", " ", s).strip()
    toks = [t for t in s.split(" ") if t and t not in _STOPWORDS]
    return toks


def _name_match_tolerant(proposta_nome: Optional[Any], cnh_nome: Optional[Any]) -> Tuple[Optional[bool], JsonDict]:
    """
    Match tolerante:
      - exige FIRST e LAST tokens iguais (após normalização)
      - exige que os tokens do menor conjunto estejam contidos no maior (subset)
    Retorna:
      - None: não comparável (faltando algum lado)
      - True / False: comparável
    """
    p = _normalize_name_tokens(proposta_nome)
    c = _normalize_name_tokens(cnh_nome)

    dbg: JsonDict = {
        "strategy": "tolerant_tokens_subset_with_first_last",
        "proposta_tokens": p,
        "cnh_tokens": c,
        "stopwords": sorted(_STOPWORDS),
    }

    if not p and not c:
        return None, {**dbg, "reason": "both_missing"}
    if not p or not c:
        return None, {**dbg, "reason": "one_missing"}

    p_first, p_last = p[0], p[-1]
    c_first, c_last = c[0], c[-1]

    if p_first != c_first or p_last != c_last:
        return False, {**dbg, "reason": "first_last_mismatch", "first_last": {"proposta": [p_first, p_last], "cnh": [c_first, c_last]}}

    sp, sc = set(p), set(c)
    small, big = (sp, sc) if len(sp) <= len(sc) else (sc, sp)
    ok_subset = small.issubset(big)

    return bool(ok_subset), {**dbg, "reason": "subset_check", "subset_ok": ok_subset}


_DATE_DDMMYYYY = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")
_DATE_YYYYMMDD = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def _parse_date_any(v: Optional[Any]) -> Tuple[Optional[date], Optional[str]]:
    if v is None:
        return None, None
    s = str(v).strip()
    if not s:
        return None, None

    m = _DATE_DDMMYYYY.match(s)
    if m:
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = date(yyyy, mm, dd)
            return d, d.isoformat()
        except ValueError:
            return None, None

    m = _DATE_YYYYMMDD.match(s)
    if m:
        yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = date(yyyy, mm, dd)
            return d, d.isoformat()
        except ValueError:
            return None, None

    return None, None


def _mk_check(*, check_id: str, status: str, message: str, evidence: Optional[JsonDict] = None) -> JsonDict:
    return {"id": check_id, "status": status, "message": message, "evidence": evidence or {}}


def build_proposta_cnh_senatran_checks(
    *,
    case_id: str,
    proposta_data: Optional[JsonDict],
    cnh_senatran_data: Optional[JsonDict],
) -> List[JsonDict]:
    """
    Gera checks (Phase 2) para CNH_SENATRAN ↔ Proposta:
      - nome (tolerante)
      - cpf (estrito digits)
      - validade (CNH-only: presente + parseável)
      - categoria (CNH-only: presente)
    """
    proposta_data = proposta_data or {}
    cnh_senatran_data = cnh_senatran_data or {}

    # Extractors
    proposta_nome = proposta_data.get("nome_financiado") or proposta_data.get("nome")
    proposta_cpf = proposta_data.get("cpf")

    cnh_nome = cnh_senatran_data.get("nome") or cnh_senatran_data.get("nome_completo")
    cnh_cpf = cnh_senatran_data.get("cpf")
    cnh_validade = cnh_senatran_data.get("validade")
    cnh_categoria = cnh_senatran_data.get("categoria")

    # 1) Nome (tolerante)
    name_cmp, name_dbg = _name_match_tolerant(proposta_nome, cnh_nome)
    if name_cmp is None:
        st_nome = "MISSING"
        msg_nome = "Cannot compare nome: missing/unusable on proposta or cnh_senatran"
    elif name_cmp is True:
        st_nome = "OK"
        msg_nome = "Nome matches (tolerant)"
    else:
        st_nome = "WARN"
        msg_nome = "Nome mismatch (tolerant)"
    chk_nome = _mk_check(
        check_id="identity.proposta_vs_cnh_senatran.nome",
        status=st_nome,
        message=msg_nome,
        evidence={
            "proposta": {"path": "data.nome_financiado|data.nome", "raw": proposta_nome},
            "cnh_senatran": {"path": "data.nome|data.nome_completo", "raw": cnh_nome},
            "debug": name_dbg,
        },
    )

    # 2) CPF (estrito)
    pcpf = _only_digits(proposta_cpf)
    ccpf = _only_digits(cnh_cpf)
    if not pcpf or not ccpf:
        st_cpf = "MISSING"
        msg_cpf = "Cannot compare cpf: missing/unusable on proposta or cnh_senatran"
    elif pcpf == ccpf:
        st_cpf = "OK"
        msg_cpf = "CPF matches"
    else:
        st_cpf = "WARN"
        msg_cpf = "CPF mismatch"
    chk_cpf = _mk_check(
        check_id="identity.proposta_vs_cnh_senatran.cpf",
        status=st_cpf,
        message=msg_cpf,
        evidence={
            "proposta": {"path": "data.cpf", "raw": proposta_cpf, "normalized": pcpf},
            "cnh_senatran": {"path": "data.cpf", "raw": cnh_cpf, "normalized": ccpf},
        },
    )

    # 3) Validade (CNH-only: presente + parseável)
    d_validade, iso_validade = _parse_date_any(cnh_validade)
    if cnh_validade is None or (isinstance(cnh_validade, str) and not cnh_validade.strip()):
        st_val = "MISSING"
        msg_val = "CNH validade missing"
    elif d_validade is None:
        st_val = "WARN"
        msg_val = "CNH validade present but unparseable"
    else:
        st_val = "OK"
        msg_val = "CNH validade present and parseable"
    chk_validade = _mk_check(
        check_id="identity.cnh_senatran.validade",
        status=st_val,
        message=msg_val,
        evidence={
            "cnh_senatran": {"path": "data.validade", "raw": cnh_validade, "normalized": iso_validade},
        },
    )

    # 4) Categoria (CNH-only: presente)
    cat = str(cnh_categoria).strip() if cnh_categoria is not None else ""
    if not cat:
        st_cat = "MISSING"
        msg_cat = "CNH categoria missing"
    else:
        st_cat = "OK"
        msg_cat = "CNH categoria present"
    chk_categoria = _mk_check(
        check_id="identity.cnh_senatran.categoria",
        status=st_cat,
        message=msg_cat,
        evidence={
            "cnh_senatran": {"path": "data.categoria", "raw": cnh_categoria, "normalized": cat or None},
        },
    )

    return [chk_nome, chk_cpf, chk_validade, chk_categoria]
