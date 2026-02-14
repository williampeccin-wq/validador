# WQ-VALIDADOR-CNH: incremental hardening (no external deps)
#
# File is intentionally self-contained and defensive:
# - tolerate OCR noise
# - never "invent" fields from headers
# - prefer deterministic anchors (record line / MRZ) when available

def _safe_str(x) -> str:
    return (x or "").strip()


def _u(x) -> str:
    return _safe_str(x).upper()


def _norm_spaces(s: str) -> str:
    return " ".join((s or "").split())


def _only_digits(s: str) -> str:
    import re as _re

    return _re.sub(r"\D+", "", s or "")


def _strip_accents(s: str) -> str:
    import unicodedata as _ud

    return "".join(
        ch for ch in _ud.normalize("NFKD", s or "") if not _ud.combining(ch)
    )


def _clean_tokenish(s: str) -> str:
    # keep letters, numbers, and common MRZ symbols
    import re as _re

    return _re.sub(r"[^A-Z0-9< ]+", " ", _u(s))


# ----------------------------- imports -----------------------------

import re
import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional

# WQ fields_v2 modules (kept optional and side-effect free)
from parsers.cnh_fields.naturalidade import extract_naturalidade as _wq_extract_naturalidade
from parsers.cnh_fields.nome import extract_nome as _wq_extract_nome

try:
    from parsers.cnh_fields.categoria import extract_categoria as _wq_extract_categoria
except Exception:
    _wq_extract_categoria = None  # type: ignore


# ----------------------------- regexes -----------------------------

_RE_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_RE_ALPHA = re.compile(r"[A-Z]")
_RE_CPF_DIGITS = re.compile(r"\b\d{11}\b")

# MRZ (CNH) — linha com datas YYMMDD (nascimento) + sexo + YYMMDD (validade)
_RE_MRZ_DATES = re.compile(r"(?P<b>\d{6})\d[MF<](?P<e>\d{6})")
_RE_MRZ_COMPACT = re.compile(r"[^A-Z0-9<]+")


def _mrz_compact(s: str) -> str:
    return _RE_MRZ_COMPACT.sub("", (s or "").upper())


def _yymmdd_to_date(yymmdd: str, kind: str) -> Optional[dt.date]:
    """Converte YYMMDD (MRZ) para date.

    kind:
      - 'birth': resolve século usando o ano atual (ex.: 93 -> 1993, 03 -> 2003).
      - 'exp': validade tende a ser futura; usa heurística simples (<=69 -> 2000+, >=70 -> 1900+).
    """
    if not yymmdd or len(yymmdd) != 6 or not yymmdd.isdigit():
        return None

    yy = int(yymmdd[0:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])

    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None

    cur_yy = dt.date.today().year % 100

    if kind == "birth":
        year = 2000 + yy if yy <= cur_yy else 1900 + yy
    else:
        year = 2000 + yy if yy <= 69 else 1900 + yy

    try:
        return dt.date(year, mm, dd)
    except ValueError:
        return None


def _extract_birth_validade_from_mrz(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai (nascimento, validade) do MRZ se existir no raw_text."""
    for ln in (text or "").splitlines():
        s = _mrz_compact(ln)
        if "<<" not in s:
            # reduz falsos positivos: MRZ normalmente tem <<<
            continue
        m = _RE_MRZ_DATES.search(s)
        if not m:
            continue
        b = _yymmdd_to_date(m.group("b"), "birth")
        e = _yymmdd_to_date(m.group("e"), "exp")
        if b and e:
            return b.strftime("%d/%m/%Y"), e.strftime("%d/%m/%Y")
    return None, None


def _date_to_dt(d: str) -> dt.date:
    # dd/mm/yyyy -> date (assume válido pois vem de regex)
    return dt.datetime.strptime(d, "%d/%m/%Y").date()


# ----------------------------- dataclasses -----------------------------


@dataclass
class CnhDbg:
    mode: str = "unknown"
    low_signal: bool = False
    fields_v2: Optional[dict[str, Any]] = None


# ----------------------------- helpers -----------------------------


def extract_dates(text: str) -> list[str]:
    # Extracts dd/mm/yyyy occurrences as strings.
    return [m.group(1) for m in _RE_DATE.finditer(text or "")]


def _safe_lines(text: str) -> list[str]:
    return (text or "").splitlines()


def _has_any_letters(s: str) -> bool:
    return bool(_RE_ALPHA.search(_u(s)))


# ----------------------------- legacy extractions -----------------------------


def _extract_nome_legacy(text: str) -> Optional[str]:
    # Legacy heuristic: look for "NOME" label and read subsequent line
    lines = _safe_lines(text)
    for i, ln in enumerate(lines):
        U = _u(ln)
        if "NOME" in U and "NAME" in U:
            # common: "NOME / NAME" then next non-empty line
            for j in range(i + 1, min(i + 6, len(lines))):
                cand = _norm_spaces(_u(lines[j]))
                if cand and _has_any_letters(cand) and "FILIA" not in cand:
                    # avoid headers
                    if "REPUBLICA" in cand or "CARTEIRA" in cand:
                        continue
                    return cand
        if U.strip() in ("NOME", "NOME/NAME", "NOME / NAME"):
            for j in range(i + 1, min(i + 6, len(lines))):
                cand = _norm_spaces(_u(lines[j]))
                if cand and _has_any_letters(cand) and "FILIA" not in cand:
                    if "REPUBLICA" in cand or "CARTEIRA" in cand:
                        continue
                    return cand
    return None


def _extract_categoria_legacy(text: str) -> Optional[str]:
    # Very conservative: only accept 1-2 letters among known set
    lines = _safe_lines(text)
    allowed = {"A", "B", "C", "D", "E", "AB", "AC", "AD", "AE", "BC", "BD", "BE", "CD", "CE", "DE"}
    for i, ln in enumerate(lines):
        U = _u(ln)
        if "CATEGORIA" in U and "VEIC" not in U:
            # next line might be single letter
            for j in range(i + 1, min(i + 4, len(lines))):
                cand = _norm_spaces(_u(lines[j])).replace(" ", "")
                if cand in allowed:
                    return cand
    return None


def _extract_nascimento_validade(text: str, dates: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Extrai data de nascimento e validade.

    Regra:
    - Preferir MRZ (linha com YYMMDD + sexo + YYMMDD), pois é determinística e evita confundir emissão/1ª habilitação.
    - Fallback: heurística antiga baseada em ordenação de datas extraídas do texto.
    """

    mrz_birth, mrz_exp = _extract_birth_validade_from_mrz(text)
    if mrz_birth or mrz_exp:
        return mrz_birth, mrz_exp

    if not dates:
        return None, None

    # -------- Fallback legado --------
    # nascimento é normalmente o menor ano; validade o maior ano.
    # (pode errar quando houver anos muito antigos em "1ª habilitação", por isso MRZ vem primeiro.)
    nascimento = min(dates, key=_date_to_dt)
    validade = max(dates, key=_date_to_dt)
    return nascimento, validade


def _extract_naturalidade_legacy(text: str) -> tuple[Optional[str], Optional[str]]:
    # Old heuristic: look for "NATURALIDADE" and capture "CIDADE/UF"
    lines = _safe_lines(text)
    for i, ln in enumerate(lines):
        U = _u(ln)
        if "NATURALIDADE" in U:
            # scan forward few lines
            for j in range(i, min(i + 6, len(lines))):
                cand = _u(lines[j])
                # common pattern: "NATURALIDADE" ... then "CIDADE - UF"
                m = re.search(r"\b([A-ZÀ-Ü ]{3,})\s*[-/]\s*([A-Z]{2})\b", _strip_accents(cand))
                if m:
                    cidade = _norm_spaces(m.group(1))
                    uf = m.group(2)
                    return cidade, uf
    return None, None


# ----------------------------- analyze entrypoint -----------------------------


def analyze_cnh(raw_text: str) -> tuple[dict[str, Any], dict[str, Any], Optional[str]]:
    """
    Returns: (fields, dbg, error)
    fields: dict with parsed CNH fields
    dbg: dict with debug info (stable keys)
    error: optional parse error string
    """
    dbg = CnhDbg(mode="cnh_v2", low_signal=False, fields_v2={})
    err: Optional[str] = None

    text = raw_text or ""
    dates = extract_dates(text)

    # ----- fields_v2: NOME -----
    nome = None
    nome_dbg: dict[str, Any] = {}
    try:
        nome, nome_dbg = _wq_extract_nome(text)
    except Exception as e:
        nome = None
        nome_dbg = {"field": "nome", "method": "error", "error": repr(e)}
    if not nome:
        # fallback legacy
        nome = _extract_nome_legacy(text)
        if nome and not nome_dbg:
            nome_dbg = {"field": "nome", "method": "legacy_label"}
    dbg.fields_v2["nome"] = nome_dbg

    # ----- fields_v2: CATEGORIA -----
    categoria = None
    cat_dbg: dict[str, Any] = {}
    if _wq_extract_categoria is not None:
        try:
            categoria, cat_dbg = _wq_extract_categoria(text)  # type: ignore[misc]
        except Exception as e:
            categoria = None
            cat_dbg = {"field": "categoria", "method": "error", "error": repr(e)}
    if not categoria:
        categoria = _extract_categoria_legacy(text)
        if categoria and not cat_dbg:
            cat_dbg = {"field": "categoria", "method": "legacy_categoria"}
    dbg.fields_v2["categoria"] = cat_dbg

    # ----- fields_v2: NATURALIDADE -----
    cidade = None
    uf = None
    nat_dbg: dict[str, Any] = {}
    try:
        cidade, uf, nat_dbg = _wq_extract_naturalidade(text)
    except Exception as e:
        cidade, uf = None, None
        nat_dbg = {"field": "naturalidade", "method": "error", "error": repr(e)}
    if not cidade or not uf:
        lc, lu = _extract_naturalidade_legacy(text)
        if lc and lu:
            cidade, uf = lc, lu
            if not nat_dbg:
                nat_dbg = {"field": "naturalidade", "method": "legacy_lines"}
    dbg.fields_v2["naturalidade"] = nat_dbg

    # ----- nascimento / validade -----
    nascimento, validade = _extract_nascimento_validade(text, dates)

    fields: dict[str, Any] = {
        "document_type": "cnh",
        "nome": nome,
        "categoria": categoria,
        "cidade": cidade,
        "uf": uf,
        "data_nascimento": nascimento,
        "validade": validade,
    }

    # basic parse_missing list (kept stable for smoke scripts)
    missing = []
    if not fields.get("nome"):
        missing.append("nome")
    if not fields.get("categoria"):
        missing.append("categoria")
    if not fields.get("data_nascimento"):
        missing.append("data_nascimento")
    if not fields.get("validade"):
        missing.append("validade")
    if not (fields.get("cidade") and fields.get("uf")):
        missing.append("naturalidade")

    dbg_dict: dict[str, Any] = {
        "mode": dbg.mode,
        "low_signal": dbg.low_signal,
        "fields_v2": dbg.fields_v2,
        "parse_missing": missing,
    }

    return fields, dbg_dict, err
