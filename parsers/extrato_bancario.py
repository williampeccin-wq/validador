# parsers/extrato_bancario.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
import io
import re

# PDF native
try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore

# pdfminer fallback
try:  # pragma: no cover
    from pdfminer.high_level import extract_text as pdfminer_extract_text  # type: ignore
except Exception:  # pragma: no cover
    pdfminer_extract_text = None  # type: ignore

# OCR opcional
try:  # pragma: no cover
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore

try:  # pragma: no cover
    from pdf2image import convert_from_bytes  # type: ignore
except Exception:  # pragma: no cover
    convert_from_bytes = None  # type: ignore


# =========================
# Estruturas
# =========================

@dataclass(frozen=True)
class PageDebug:
    page: int
    native_len: int = 0
    ocr_len: int = 0


@dataclass(frozen=True)
class StrategyResult:
    name: str
    lancamentos: List[Dict[str, Any]]
    matched_lines: int
    discarded_lines: int
    notes: List[str]


# =========================
# Regex / utilidades
# =========================

_BUILD_ID = "2026-01-02-extrato-pj-rowassembly-v8"

_MULTISPACE_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SALDO_DO_DIA_RE = re.compile(r"\bSALDO\s+DO\s+DIA\b", re.IGNORECASE)
_SALDO_ANTERIOR_RE = re.compile(r"\bSALDO\s+ANTERIOR\b", re.IGNORECASE)

# valores BR “normal”
_VAL_BR_RE = re.compile(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2}")

# valores BR “relaxado” (aceita espaços dentro): "1. 666, 44", "1.183, 46"
_VAL_BR_RELAX_RE = re.compile(
    r"[+-]?\d{1,3}(?:\.\s*\d{3})*,\s*\d{2}|[+-]?\d+,\s*\d{2}"
)

_DOT_GROUP_RE = re.compile(r"(\d)\.\s+(\d{3})")
_COMMA_DEC_RE = re.compile(r"(\d),\s+(\d{2})")
_MINUS_SPACE_RE = re.compile(r"(-)\s+(R?\$?\s*\d)")

# separadores comuns + slashes unicode que aparecem em PDF text extraction
# '/', '-', '.', '／'(FF0F), '⁄'(2044), '∕'(2215), '⧸'(29F8)
_DATE_SEP_CLASS = r"[/\-\.\uFF0F\u2044\u2215\u29F8]"

# data "flex" (1-2 dígitos dia/mês, 2-4 ano) com separadores acima OU espaços como separador
# Ex.: 05/08/2025, 5-8-25, 05⁄08⁄2025, 05 08 2025
_DATE_FLEX_RE = re.compile(
    rf"(\d{{1,2}})\s*(?:{_DATE_SEP_CLASS}|\s)\s*(\d{{1,2}})\s*(?:{_DATE_SEP_CLASS}|\s)\s*(\d{{2,4}})"
)

# data colada no texto: 05/08/2025PREST -> 05/08/2025 PREST
_DATE_GLUE_RE = re.compile(
    rf"(\d{{1,2}}\s*(?:{_DATE_SEP_CLASS})\s*\d{{1,2}}\s*(?:{_DATE_SEP_CLASS})\s*\d{{2,4}})([A-Za-zÇçÃãÕõÉéÊêÍíÓóÚú])"
)

_ITAU_LINE_RE = re.compile(
    r"^\s*(\d{2}/\d{2}/\d{4})\s+(.*?)\s+([+-]?\d[\d\.]*,\d{2})(?:\s*([DC]))?\s*$"
)

_MONTHS_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

_LONG_DATE_RE = re.compile(
    r"^\s*(\d{1,2})\s+de\s+([A-Za-zÇçÃãÕõÉéÊêÍíÓóÚú]+)\s+de\s+(\d{4})(?:\b.*)?$",
    re.IGNORECASE,
)

_MONTH_SECTION_RE = re.compile(r"^\s*([A-Za-zÇçÃãÕõÉéÊêÍíÓóÚú]+)\s+(\d{4})\b", re.IGNORECASE)
_DUAL_DATE_LINE_RE = re.compile(
    r"^\s*(\d{2})/(\d{2})\s+(\d{2})/(\d{2})\s+(.*?)\s+([+-]?\s*-?R\$\s*\d[\d\.]*,\d{2}|[+-]?\d[\d\.]*,\d{2})\s*$",
    re.IGNORECASE,
)

_MONTH_HEADER_RE = re.compile(r"^\s*([A-Za-zÇçÃãÕõÉéÊêÍíÓóÚú]+)\s+(\d{4})\b", re.IGNORECASE)
_DAY_MM_RE = re.compile(r"^\s*(\d{2})/(\d{2})\s*$")
_GENERIC_DDMMYYYY_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s*(.*)$")


def _compact_numbers_in_line(s: str) -> str:
    if not s:
        return s
    s = _DOT_GROUP_RE.sub(r"\1.\2", s)
    s = _COMMA_DEC_RE.sub(r"\1,\2", s)
    s = _MINUS_SPACE_RE.sub(r"\1\2", s)
    for _ in range(3):
        s = _DOT_GROUP_RE.sub(r"\1.\2", s)
        s = _COMMA_DEC_RE.sub(r"\1,\2", s)
        s = _MINUS_SPACE_RE.sub(r"\1\2", s)
    return s


def _explode_line_on_dates(ln: str) -> List[str]:
    matches = list(_DATE_FLEX_RE.finditer(ln))
    if len(matches) <= 1:
        return [ln]

    out: List[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ln)
        chunk = ln[start:end].strip()
        if chunk:
            out.append(chunk)
    return out if out else [ln]


def _normalize_lines(text: str) -> List[str]:
    out: List[str] = []
    for ln in (text or "").splitlines():
        ln2 = _compact_numbers_in_line(ln)
        ln2 = _DATE_GLUE_RE.sub(r"\1 \2", ln2)
        ln2 = _MULTISPACE_RE.sub(" ", ln2).strip()
        if not ln2:
            continue

        if len(list(_DATE_FLEX_RE.finditer(ln2))) >= 2:
            out.extend(_explode_line_on_dates(ln2))
        else:
            out.append(ln2)

    return out


def _normalize_ddmmyyyy_from_groups(d: str, m: str, y: str) -> Optional[str]:
    try:
        dd = int(d)
        mm = int(m)
        yy = int(y)
        if yy < 100:
            yy += 2000
        if not (1 <= dd <= 31 and 1 <= mm <= 12 and 1900 <= yy <= 2100):
            return None
        return f"{dd:02d}/{mm:02d}/{yy:04d}"
    except Exception:
        return None


def _to_iso_date_from_ddmmyyyy(ddmmyyyy: str) -> str:
    return datetime.strptime(ddmmyyyy, "%d/%m/%Y").strftime("%Y-%m-%d")


def _parse_brl_number(num: str) -> float:
    s = (num or "").strip()
    s = s.replace("−", "-")
    s = s.replace("R$", "").replace("r$", "").strip()
    s = s.replace(" ", "")
    neg = s.startswith("-")
    s2 = s.replace("+", "").replace("-", "")
    s2 = s2.replace(".", "").replace(",", ".")
    v = float(s2)
    return -v if neg else v


def _clean_desc(s: str) -> str:
    return _MULTISPACE_RE.sub(" ", (s or "")).strip()


def _extract_first_money_value(ln: str) -> Optional[float]:
    m = re.search(r"([+-]?\s*R\$\s*\d[\d\.]*,\d{2})", ln, flags=re.IGNORECASE)
    if m:
        raw = m.group(1).replace("R$", "").replace("r$", "").strip()
        raw = raw.replace(" ", "")
        if m.group(1).strip().startswith("-"):
            raw = "-" + raw.lstrip("+-")
        return _parse_brl_number(raw)

    nums = _VAL_BR_RE.findall(ln)
    if nums:
        return _parse_brl_number(nums[0])
    return None


def _find_money_tokens_relaxed(s: str) -> List[str]:
    toks = _VAL_BR_RELAX_RE.findall(s or "")
    return [re.sub(r"\s+", "", t) for t in toks]


def _find_date_anywhere(ln: str) -> Optional[Tuple[str, str]]:
    m = _DATE_FLEX_RE.search(ln)
    if not m:
        return None

    ddmmyyyy = _normalize_ddmmyyyy_from_groups(m.group(1), m.group(2), m.group(3))
    if not ddmmyyyy:
        return None

    rest = (ln[m.end():] or "").strip()
    return ddmmyyyy, rest


def _looks_like_pj_header_or_noise(rest: str) -> bool:
    up = (rest or "").upper()
    if not up:
        return True
    if up.startswith("DATA") or up.startswith("DESCRI") or "DOCUMENTO" in up:
        return True
    if "CRÉDITO" in up or "CREDITO" in up or "DÉBITO" in up or "DEBITO" in up or "SALDO" in up:
        return True
    if _SALDO_ANTERIOR_RE.search(rest):
        return True
    return False


# =========================
# Extração de texto
# =========================

def _extract_text_native(file_bytes: bytes) -> Tuple[str, List[PageDebug]]:
    text = ""
    pages_dbg: List[PageDebug] = []

    if pdfplumber is not None:
        try:
            parts: List[str] = []
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for idx, page in enumerate(pdf.pages, start=1):
                    t = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                    parts.append(t)
                    pages_dbg.append(PageDebug(page=idx, native_len=len(t), ocr_len=0))
            text = "\n".join(parts)
        except Exception:
            text = ""
            pages_dbg = []

    if (not text.strip()) and pdfminer_extract_text is not None:
        try:
            t = pdfminer_extract_text(io.BytesIO(file_bytes)) or ""
            if t.strip():
                text = t
                pages_dbg = [PageDebug(page=1, native_len=len(t), ocr_len=0)]
        except Exception:
            pass

    return text, pages_dbg


def _extract_text_ocr(file_bytes: bytes, filename: str, *, dpi: int) -> Tuple[str, List[PageDebug]]:
    if pytesseract is None or convert_from_bytes is None:
        return "", []
    if not filename.lower().endswith(".pdf"):
        return "", []
    try:
        images = convert_from_bytes(file_bytes, dpi=dpi)
    except Exception:
        return "", []

    texts: List[str] = []
    dbg: List[PageDebug] = []
    for idx, img in enumerate(images, start=1):
        try:
            t = pytesseract.image_to_string(img, lang="por") or ""
        except Exception:
            t = ""
        texts.append(t)
        dbg.append(PageDebug(page=idx, native_len=0, ocr_len=len(t)))
    return "\n".join(texts), dbg


def _merge_pages_debug(native_pages: List[PageDebug], ocr_pages: List[PageDebug]) -> List[PageDebug]:
    if not native_pages:
        return ocr_pages
    if not ocr_pages:
        return native_pages
    by_page: Dict[int, PageDebug] = {p.page: p for p in native_pages}
    for p in ocr_pages:
        prev = by_page.get(p.page)
        if prev is None:
            by_page[p.page] = p
        else:
            by_page[p.page] = PageDebug(page=p.page, native_len=prev.native_len, ocr_len=p.ocr_len)
    return [by_page[k] for k in sorted(by_page.keys())]


# =========================
# Scoring / chooser
# =========================

def _score_strategy(r: StrategyResult) -> float:
    tx = len(r.lancamentos)
    if tx == 0:
        return -1.0
    base = tx * 1.0 - r.discarded_lines * 0.15
    iso_ok = sum(1 for t in r.lancamentos if isinstance(t.get("data"), str) and _ISO_DATE_RE.match(t["data"]))
    base += (iso_ok / max(1, tx)) * 2.0
    return base


def _choose_best(results: List[StrategyResult]) -> StrategyResult:
    best = results[0]
    best_s = _score_strategy(best)
    for r in results[1:]:
        s = _score_strategy(r)
        if s > best_s:
            best = r
            best_s = s
    return best


# =========================
# Estratégias
# =========================

def _parse_itau_line_end_value(lines: List[str]) -> StrategyResult:
    out: List[Dict[str, Any]] = []
    matched = discarded = 0

    for ln in lines:
        m = _ITAU_LINE_RE.match(ln)
        if not m:
            continue
        dbr, desc, val_br, dc = m.group(1), m.group(2), m.group(3), m.group(4)

        if _SALDO_DO_DIA_RE.search(desc):
            discarded += 1
            continue

        try:
            d_iso = _to_iso_date_from_ddmmyyyy(dbr)
            val = _parse_brl_number(val_br)
        except Exception:
            discarded += 1
            continue

        if dc:
            if dc.upper() == "D":
                val = -abs(val)
            elif dc.upper() == "C":
                val = abs(val)

        desc_norm = _clean_desc(desc)
        if len(desc_norm) < 3:
            discarded += 1
            continue

        out.append({"data": d_iso, "descricao": desc_norm, "valor": float(val)})
        matched += 1

    return StrategyResult("itau_line_end_value", out, matched, discarded, [])


def _parse_pj_tabular_multivalue(lines: List[str]) -> StrategyResult:
    """
    PJ tabular robusto:
      - acha data em qualquer posição
      - se a linha com data não trouxer valores, junta com 1–2 linhas seguintes
        (row assembly), porque o extract_text pode quebrar a tabela.
      - usa 2 últimos valores (movimento, saldo)
    """
    out: List[Dict[str, Any]] = []
    matched = discarded = 0

    seen_date_lines = 0
    no_money = 0
    no_two_vals = 0
    assembled_rows = 0
    skipped_due_to_header = 0

    i = 0
    n = len(lines)

    while i < n:
        ln = lines[i]
        found = _find_date_anywhere(ln)
        if not found:
            i += 1
            continue

        seen_date_lines += 1
        dbr, rest = found

        if _looks_like_pj_header_or_noise(rest):
            skipped_due_to_header += 1
            i += 1
            continue

        # 1) tenta na própria linha
        combined = rest
        toks = _find_money_tokens_relaxed(combined)

        # 2) se não achou dinheiro aqui, tenta montar "row" juntando as próximas linhas
        if not toks:
            extra_parts: List[str] = []
            j = i + 1
            # lookahead curto e seguro (2 linhas)
            while j < n and j <= i + 2:
                nxt = lines[j]
                # se a próxima já tem data, não junta
                if _find_date_anywhere(nxt):
                    break
                # pula cabeçalhos/ruídos, mas ainda permite valores soltos
                if nxt and not _looks_like_pj_header_or_noise(nxt):
                    extra_parts.append(nxt)
                j += 1

            if extra_parts:
                combined = (rest + " " + " ".join(extra_parts)).strip()
                toks = _find_money_tokens_relaxed(combined)
                if toks:
                    assembled_rows += 1
                    # avança o índice consumindo as linhas usadas
                    i = j - 1  # o while do final vai i += 1

        if not toks:
            no_money += 1
            discarded += 1
            i += 1
            continue

        if len(toks) < 2:
            no_two_vals += 1
            discarded += 1
            i += 1
            continue

        mov_tok = toks[-2]
        saldo_tok = toks[-1]

        try:
            d_iso = _to_iso_date_from_ddmmyyyy(dbr)
            mov = _parse_brl_number(mov_tok)
            _ = _parse_brl_number(saldo_tok)
        except Exception:
            discarded += 1
            i += 1
            continue

        desc = _VAL_BR_RELAX_RE.sub(" ", combined)
        desc = desc.replace("R$", " ").replace("r$", " ")
        desc = _clean_desc(desc)

        if len(desc) < 3 or _SALDO_DO_DIA_RE.search(desc):
            discarded += 1
            i += 1
            continue

        out.append({"data": d_iso, "descricao": desc, "valor": float(mov)})
        matched += 1
        i += 1

    notes = [
        "pj_tabular_multivalue: unicode+space date detection + relaxed money + row-assembly lookahead(2)",
        f"seen_date_lines={seen_date_lines}",
        f"skipped_due_to_header={skipped_due_to_header}",
        f"assembled_rows={assembled_rows}",
        f"no_money={no_money}",
        f"no_two_vals={no_two_vals}",
    ]
    return StrategyResult("pj_tabular_multivalue", out, matched, discarded, notes)


def _parse_month_sections_dual_dates(lines: List[str]) -> StrategyResult:
    out: List[Dict[str, Any]] = []
    matched = discarded = 0
    notes = ["month_sections_dual_dates"]

    cur_year: Optional[int] = None
    for ln in lines:
        mh = _MONTH_SECTION_RE.match(ln)
        if mh:
            cur_year = int(mh.group(2))
            continue

        if cur_year is None:
            continue

        if ln.lower().startswith("saldo do dia"):
            continue
        if ln.lower().startswith("data data") or ln.lower().startswith("tipo descrição valor") or ln.lower().startswith("lançamento contábil"):
            continue

        md = _DUAL_DATE_LINE_RE.match(ln)
        if not md:
            continue

        dd1, mm1, desc_raw, val_raw = md.group(1), md.group(2), md.group(5), md.group(6)

        val_s = val_raw.strip().replace(" ", "")
        if val_s.upper().startswith("-R$"):
            val_s = "-" + val_s[3:]
        elif val_s.upper().startswith("R$"):
            val_s = val_s[2:]

        try:
            d_iso = f"{cur_year:04d}-{int(mm1):02d}-{int(dd1):02d}"
            datetime.strptime(d_iso, "%Y-%m-%d")
            v = _parse_brl_number(val_s)
        except Exception:
            discarded += 1
            continue

        desc = _clean_desc(desc_raw)
        if len(desc) < 3:
            discarded += 1
            continue

        out.append({"data": d_iso, "descricao": desc, "valor": float(v)})
        matched += 1

    return StrategyResult("month_sections_dual_dates", out, matched, discarded, notes)


def _parse_inter_inline(lines: List[str]) -> StrategyResult:
    out: List[Dict[str, Any]] = []
    matched = discarded = 0
    notes = ["inter_inline"]

    cur_date_iso: Optional[str] = None
    for ln in lines:
        mh = _LONG_DATE_RE.match(ln)
        if mh:
            dd = int(mh.group(1))
            mes_nome = _clean_desc(mh.group(2)).lower()
            yyyy = int(mh.group(3))
            mes = _MONTHS_PT.get(mes_nome)
            cur_date_iso = f"{yyyy:04d}-{mes:02d}-{dd:02d}" if mes else None
            continue

        if cur_date_iso is None:
            continue

        if _SALDO_DO_DIA_RE.search(ln):
            continue

        v = _extract_first_money_value(_compact_numbers_in_line(ln))
        if v is None:
            continue

        desc = _VAL_BR_RELAX_RE.sub(" ", ln)
        desc = desc.replace("R$", " ").replace("r$", " ")
        desc = _clean_desc(desc)

        if len(desc) < 3:
            discarded += 1
            continue

        out.append({"data": cur_date_iso, "descricao": desc, "valor": float(v)})
        matched += 1

    return StrategyResult("inter_inline", out, matched, discarded, notes)


def _parse_month_columnar_zip(lines: List[str]) -> StrategyResult:
    out: List[Dict[str, Any]] = []
    matched = discarded = 0
    notes = ["month_columnar_zip"]

    cur_year: Optional[int] = None
    dates_ddmm: List[Tuple[int, int]] = []
    descs: List[str] = []
    values: List[float] = []
    in_dates = in_desc = in_values = False

    def flush() -> None:
        nonlocal matched, discarded, dates_ddmm, descs, values, out, cur_year
        if cur_year is None:
            dates_ddmm, descs, values = [], [], []
            return
        n = min(len(dates_ddmm), len(descs), len(values))
        if n <= 0:
            dates_ddmm, descs, values = [], [], []
            return
        for k in range(n):
            dd, mm = dates_ddmm[k]
            try:
                d_iso = f"{cur_year:04d}-{mm:02d}-{dd:02d}"
                datetime.strptime(d_iso, "%Y-%m-%d")
            except Exception:
                discarded += 1
                continue
            desc = _clean_desc(descs[k])
            if len(desc) < 3:
                discarded += 1
                continue
            out.append({"data": d_iso, "descricao": desc, "valor": float(values[k])})
            matched += 1
        dates_ddmm, descs, values = [], [], []

    for ln in lines:
        m_month = _MONTH_HEADER_RE.match(ln)
        if m_month:
            flush()
            cur_year = int(m_month.group(2))
            in_dates = in_desc = in_values = False
            continue

        low = ln.strip().lower()
        if low in {"data", "lançamento", "data lançamento"}:
            in_dates, in_desc, in_values = True, False, False
            continue
        if low in {"descrição", "descricao"}:
            in_dates, in_desc, in_values = False, True, False
            continue
        if low == "valor":
            in_dates, in_desc, in_values = False, False, True
            continue

        if in_dates:
            md = _DAY_MM_RE.match(ln)
            if md:
                dates_ddmm.append((int(md.group(1)), int(md.group(2))))
                continue

        if in_desc:
            if not ln.strip():
                continue
            if not _VAL_BR_RELAX_RE.search(ln) and not _DAY_MM_RE.match(ln):
                descs.append(ln)
                continue

        if in_values:
            if _VAL_BR_RELAX_RE.fullmatch(ln.strip()) or ln.strip().replace(" ", "").startswith(("R$", "-R$", "+R$")):
                v = _extract_first_money_value(_compact_numbers_in_line(ln))
                if v is not None:
                    values.append(v)
                continue

    flush()
    return StrategyResult("month_columnar_zip", out, matched, discarded, notes)


def _parse_generic_ddmmyyyy_last_value(lines: List[str]) -> StrategyResult:
    out: List[Dict[str, Any]] = []
    matched = discarded = 0
    notes = ["generic_ddmmyyyy_last_value"]

    for ln in lines:
        m = _GENERIC_DDMMYYYY_RE.match(ln)
        if not m:
            continue
        dbr, rest = m.group(1), m.group(2)

        toks = _find_money_tokens_relaxed(rest)
        if not toks:
            continue

        try:
            d_iso = _to_iso_date_from_ddmmyyyy(dbr)
            val = _parse_brl_number(toks[-1])
        except Exception:
            discarded += 1
            continue

        desc = _VAL_BR_RELAX_RE.sub(" ", rest)
        desc = desc.replace("R$", " ").replace("r$", " ")
        desc = _clean_desc(desc)

        if len(desc) < 3:
            discarded += 1
            continue

        out.append({"data": d_iso, "descricao": desc, "valor": float(val)})
        matched += 1

    return StrategyResult("generic_ddmmyyyy_last_value", out, matched, discarded, notes)


# =========================
# API pública
# =========================

def analyze_extrato_bancario(
    file_bytes: bytes,
    filename: str,
    *,
    min_text_len_threshold: int = 800,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    debug: Dict[str, Any] = {
        "build_id": _BUILD_ID,
        "mode": "unknown",
        "native_text_len": 0,
        "ocr_text_len": 0,
        "pages": [],
        "min_text_len_threshold": min_text_len_threshold,
        "ocr_dpi": ocr_dpi,
        "chosen_strategy": "none",
        "strategy_scores": [],
        "strategy_names": [],
    }

    try:
        is_pdf = filename.lower().endswith(".pdf")

        native_text = ""
        native_pages: List[PageDebug] = []
        if is_pdf:
            native_text, native_pages = _extract_text_native(file_bytes)
            debug["native_text_len"] = len(native_text)

        use_ocr = (not is_pdf) or (len(native_text) < min_text_len_threshold)
        if use_ocr:
            ocr_text, ocr_pages = _extract_text_ocr(file_bytes, filename, dpi=ocr_dpi)
            debug["ocr_text_len"] = len(ocr_text)
            pages_dbg = _merge_pages_debug(native_pages, ocr_pages)

            text = ocr_text if ocr_text.strip() else native_text
            debug["mode"] = "ocr" if ocr_text.strip() else ("native" if native_text.strip() else "ocr")
        else:
            pages_dbg = native_pages
            text = native_text
            debug["mode"] = "native"

        debug["pages"] = [{"page": p.page, "native_len": p.native_len, "ocr_len": p.ocr_len} for p in pages_dbg]

        lines = _normalize_lines(text)

        strategies: List[Callable[[List[str]], StrategyResult]] = [
            _parse_itau_line_end_value,
            _parse_pj_tabular_multivalue,
            _parse_month_sections_dual_dates,
            _parse_inter_inline,
            _parse_month_columnar_zip,
            _parse_generic_ddmmyyyy_last_value,
        ]
        debug["strategy_names"] = [getattr(fn, "__name__", "<unknown>") for fn in strategies]

        results: List[StrategyResult] = []
        for fn in strategies:
            try:
                results.append(fn(lines))
            except Exception as e:
                results.append(StrategyResult(
                    name=getattr(fn, "__name__", "unknown"),
                    lancamentos=[],
                    matched_lines=0,
                    discarded_lines=0,
                    notes=[f"strategy crashed: {e!r}"],
                ))

        chosen = _choose_best(results)
        debug["chosen_strategy"] = chosen.name
        debug["strategy_scores"] = [
            {
                "name": r.name,
                "tx": len(r.lancamentos),
                "matched": r.matched_lines,
                "discarded": r.discarded_lines,
                "score": _score_strategy(r),
                "notes": r.notes,
            }
            for r in results
        ]

        return {"lancamentos": chosen.lancamentos, "debug": debug}

    except Exception as e:
        debug["chosen_strategy"] = "crashed"
        debug["strategy_scores"] = [{"name": "analyze_extrato_bancario", "error": repr(e)}]
        return {"lancamentos": [], "debug": debug}
