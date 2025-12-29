# parsers/extrato_bancario.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re

# Dependências opcionais (OCR / PDF)
try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore


@dataclass(frozen=True)
class PageDebug:
    page: int
    native_len: int = 0
    ocr_len: int = 0


_DATE_RE = re.compile(
    r"^\s*(\d{2}/\d{2}/\d{4})\s+(.*?)\s+([+-]?\d[\d\.]*,\d{2})(?:\s*([DC]))?\s*$"
)
_ONLY_DATE_PREFIX_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+")
_MULTISPACE_RE = re.compile(r"\s+")
_SALDO_DO_DIA_RE = re.compile(r"\bSALDO\s+DO\s+DIA\b", re.IGNORECASE)


def analyze_extrato_bancario(
    file_bytes: bytes,
    filename: str,
    *,
    min_text_len_threshold: int = 800,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    """
    Extrato bancário (MVP):
      - Extrai texto nativo via pdfplumber (se PDF).
      - Faz OCR fallback se texto nativo for insuficiente.
      - Faz parsing por regex + heurística:
          * linhas iniciando com dd/mm/yyyy
          * ignora "SALDO DO DIA"
      - Retorna lista de lançamentos [{data, descricao, valor}]
    """
    debug: Dict[str, Any] = {
        "mode": None,
        "native_text_len": 0,
        "ocr_text_len": 0,
        "pages": [],
        "min_text_len_threshold": min_text_len_threshold,
        "ocr_dpi": ocr_dpi,
        "parsing": {"matched_lines": 0, "discarded_lines": 0, "notes": []},
    }

    is_pdf = filename.lower().endswith(".pdf")

    native_text = ""
    pages_dbg: List[PageDebug] = []
    if is_pdf:
        native_text, pages_dbg = _extract_text_native_pdfplumber(file_bytes)
        debug["native_text_len"] = len(native_text)

    use_ocr = (not is_pdf) or (len(native_text) < min_text_len_threshold)
    if use_ocr:
        ocr_text, pages_dbg_ocr = _extract_text_ocr(file_bytes, filename, dpi=ocr_dpi)
        debug["ocr_text_len"] = len(ocr_text)

        # Mescla debug de páginas
        pages_dbg = _merge_pages_debug(pages_dbg, pages_dbg_ocr)

        # Se o OCR veio vazio e existe nativo, ainda tenta nativo
        if ocr_text.strip():
            text = ocr_text
            debug["mode"] = "ocr"
        else:
            text = native_text
            debug["mode"] = "native" if native_text.strip() else "ocr"
            debug["parsing"]["notes"].append(
                "OCR returned empty text; falling back to native text if available."
            )
    else:
        text = native_text
        debug["mode"] = "native"

    debug["pages"] = [
        {"page": p.page, "native_len": p.native_len, "ocr_len": p.ocr_len} for p in pages_dbg
    ]

    lines = _normalize_lines(text)
    lancamentos, parsing_dbg = _parse_transactions(lines)
    debug["parsing"].update(parsing_dbg)

    # Metadados MVP: mantemos como null/unknown por enquanto
    result: Dict[str, Any] = {
        "banco": "itau",  # MVP: fixture atual é Itaú; generalize depois
        "periodo": {"inicio": None, "fim": None},
        "agencia": None,
        "conta": None,
        "titular": None,
        "lancamentos": lancamentos,
        "debug": debug,
    }

    return result


def _extract_text_native_pdfplumber(file_bytes: bytes) -> Tuple[str, List[PageDebug]]:
    if pdfplumber is None:
        return "", []

    text_parts: List[str] = []
    pages_dbg: List[PageDebug] = []
    try:
        from io import BytesIO

        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                t = page.extract_text() or ""
                text_parts.append(t)
                pages_dbg.append(PageDebug(page=idx, native_len=len(t), ocr_len=0))
    except Exception:
        # Falha silenciosa aqui é OK no MVP; OCR pode salvar
        return "", []

    return "\n".join(text_parts), pages_dbg


def _extract_text_ocr(file_bytes: bytes, filename: str, *, dpi: int = 300) -> Tuple[str, List[PageDebug]]:
    """
    OCR fallback:
      - PDF: pdf2image -> PIL -> pytesseract
      - Imagem: PIL -> pytesseract
    Dependências esperadas (opcionais):
      - pytesseract
      - pillow
      - pdf2image (para PDF) + poppler instalado no sistema
    """
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return "", []

    pages_dbg: List[PageDebug] = []
    texts: List[str] = []

    is_pdf = filename.lower().endswith(".pdf")
    if is_pdf:
        try:
            from pdf2image import convert_from_bytes  # type: ignore

            images = convert_from_bytes(file_bytes, dpi=dpi)
            for idx, img in enumerate(images, start=1):
                t = pytesseract.image_to_string(img, lang="por") or ""
                texts.append(t)
                pages_dbg.append(PageDebug(page=idx, native_len=0, ocr_len=len(t)))
        except Exception:
            return "", []
    else:
        try:
            from io import BytesIO

            img = Image.open(BytesIO(file_bytes))
            t = pytesseract.image_to_string(img, lang="por") or ""
            texts.append(t)
            pages_dbg.append(PageDebug(page=1, native_len=0, ocr_len=len(t)))
        except Exception:
            return "", []

    return "\n".join(texts), pages_dbg


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


def _normalize_lines(text: str) -> List[str]:
    """
    Normaliza o texto em linhas "parseáveis":
      - remove espaços duplicados
      - remove linhas vazias
      - preserva a ordem
    """
    raw_lines = (text or "").splitlines()
    out: List[str] = []
    for ln in raw_lines:
        ln2 = _MULTISPACE_RE.sub(" ", ln).strip()
        if ln2:
            out.append(ln2)
    return out


def _parse_transactions(lines: List[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Heurística Itaú v1:
      - Linha de transação: começa com dd/mm/yyyy e termina com valor BR.
      - Ignora "SALDO DO DIA"
      - Se uma linha não tem data no começo, ela pode ser continuação de descrição:
          -> concatena na última transação aberta (futuro).
    """
    lancamentos: List[Dict[str, Any]] = []
    matched = 0
    discarded = 0
    notes: List[str] = []

    open_tx_idx: Optional[int] = None

    for ln in lines:
        if not _ONLY_DATE_PREFIX_RE.match(ln):
            # possível continuação de descrição (evolução futura)
            if open_tx_idx is not None:
                lancamentos[open_tx_idx]["descricao"] = (
                    lancamentos[open_tx_idx]["descricao"] + " " + ln
                ).strip()
            continue

        m = _DATE_RE.match(ln)
        if not m:
            discarded += 1
            continue

        date_br, desc, value_br, dc_flag = m.group(1), m.group(2), m.group(3), m.group(4)

        if _SALDO_DO_DIA_RE.search(desc):
            discarded += 1
            open_tx_idx = None
            continue

        try:
            date_iso = _to_iso_date(date_br)
        except Exception:
            discarded += 1
            continue

        try:
            val = _parse_brl_value(value_br, dc_flag)
        except Exception:
            discarded += 1
            continue

        desc_norm = _MULTISPACE_RE.sub(" ", desc).strip()

        tx = {"data": date_iso, "descricao": desc_norm, "valor": val}
        lancamentos.append(tx)
        matched += 1

        open_tx_idx = None

    return lancamentos, {"matched_lines": matched, "discarded_lines": discarded, "notes": notes}


def _to_iso_date(ddmmyyyy: str) -> str:
    dt = datetime.strptime(ddmmyyyy, "%d/%m/%Y")
    return dt.strftime("%Y-%m-%d")


def _parse_brl_value(value_br: str, dc_flag: Optional[str]) -> float:
    """
    Converte valor pt-BR em float.
      - "2.657,37" -> 2657.37
      - "-2.657,37" -> -2657.37
      - Se flag D/C existir, ela manda no sinal (D negativo, C positivo).
    """
    s = value_br.strip()

    negative = s.startswith("-")
    s2 = s.replace(".", "").replace(",", ".")
    s2 = s2.replace("+", "").replace("-", "").strip()

    val = float(s2)

    if dc_flag:
        flag = dc_flag.upper()
        if flag == "D":
            return -abs(val)
        if flag == "C":
            return abs(val)

    return -val if negative else val
