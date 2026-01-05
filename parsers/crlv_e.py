from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 800

# =========================
# Regexes
# =========================
_PLACA_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")
_RENAVAM_RE = re.compile(r"\b(\d{11})\b")
_CHASSI_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_ANO_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_CPF_MASKED_RE = re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b")
_DATE_RE = re.compile(r"\b([0-3]?\d)/([01]?\d)/((?:19|20)\d{2})\b")

_NOISE_RE = re.compile(
    r"(DENATRAN|SENATRAN|SEGURADO|DEPARTAMENTO|QR\s*CODE|DPVAT)",
    re.IGNORECASE,
)

# =========================
# Public API
# =========================
def analyze_crlv_e(
    pdf_path: str,
    *,
    min_text_len_threshold: int = MIN_TEXT_LEN_THRESHOLD_DEFAULT,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    native_text, pages_native_len = _extract_native_text(pdf_path)

    if len(native_text) >= min_text_len_threshold:
        mode = "native"
        ocr_text = ""
        pages_ocr_len = [0 for _ in pages_native_len]
    else:
        mode = "ocr"
        ocr_text, pages_ocr_len = _ocr_pdf_to_text(pdf_path, dpi=ocr_dpi)

    text = native_text if mode == "native" else ocr_text
    lines = _clean_lines(text)

    extracted = _extract_fields(lines)

    debug_pages = [
        {
            "page": i + 1,
            "native_len": pages_native_len[i] if i < len(pages_native_len) else 0,
            "ocr_len": pages_ocr_len[i] if i < len(pages_ocr_len) else 0,
        }
        for i in range(max(len(pages_native_len), len(pages_ocr_len)))
    ]

    out: Dict[str, Any] = {
        **extracted,
        "mode": mode,
        "debug": {
            "mode": mode,
            "native_text_len": len(native_text),
            "ocr_text_len": len(ocr_text),
            "min_text_len_threshold": min_text_len_threshold,
            "ocr_dpi": ocr_dpi,
            "pages": debug_pages,
            "checks": {},
            "warnings": [],
        },
    }

    _run_soft_checks(out)
    return out


# =========================
# Text extraction
# =========================
def _extract_native_text(pdf_path: str) -> Tuple[str, List[int]]:
    import pdfplumber

    texts, lens = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            texts.append(t)
            lens.append(len(t))
    return "\n".join(texts), lens


def _ocr_pdf_to_text(pdf_path: str, *, dpi: int) -> Tuple[str, List[int]]:
    from pdf2image import convert_from_path
    import pytesseract

    texts, lens = [], []
    for img in convert_from_path(pdf_path, dpi=dpi):
        t = pytesseract.image_to_string(img, lang="por") or ""
        texts.append(t)
        lens.append(len(t))
    return "\n".join(texts), lens


# =========================
# Parsing helpers
# =========================
def _clean_lines(text: str) -> List[str]:
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l:
            continue
        if _NOISE_RE.search(l):
            continue
        out.append(l)
    return out


def _extract_fields(lines: List[str]) -> Dict[str, Any]:
    blob = " ".join(lines).upper()

    placa = _PLACA_RE.search(blob)
    renavam = _RENAVAM_RE.search(blob)
    chassi = _CHASSI_RE.search(blob)

    marca_modelo = _tabular_value(lines, "MARCA/MODELO")
    categoria = _tabular_value(lines, "CATEGORIA")
    combustivel = _tabular_value(lines, "COMBUST")
    cor = _tabular_value(lines, "COR")

    ano_fab_mod = _tabular_value(lines, "ANO FAB/MOD")
    ano_fabricacao, ano_modelo = _split_ano(ano_fab_mod)

    proprietario_nome = _tabular_value(lines, "PROPRIET")
    proprietario_doc = _extract_cpf(lines)

    uf_licenciamento = _tabular_value(lines, "UF")
    local_emissao = _tabular_value(lines, "LOCAL")

    data_emissao = _extract_date(blob)

    return {
        "placa": placa.group(1) if placa else None,
        "renavam": renavam.group(1) if renavam else None,
        "chassi": chassi.group(1) if chassi else None,
        "marca_modelo": marca_modelo,
        "ano_fabricacao": ano_fabricacao,
        "ano_modelo": ano_modelo,
        "categoria": categoria,
        "combustivel": combustivel,
        "cor": cor,
        "proprietario_nome": proprietario_nome,
        "proprietario_doc": proprietario_doc,
        "uf_licenciamento": uf_licenciamento,
        "local_emissao": local_emissao,
        "data_emissao": data_emissao,
    }


def _tabular_value(lines: List[str], label: str) -> Optional[str]:
    for i, l in enumerate(lines):
        if label in l.upper():
            tail = l.split(label, 1)[-1].strip(" :")
            if tail:
                return tail
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    return None


def _split_ano(v: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not v:
        return None, None
    years = _ANO_RE.findall(v)
    if len(years) >= 2:
        return years[0], years[1]
    if len(years) == 1:
        return years[0], years[0]
    return None, None


def _extract_cpf(lines: List[str]) -> Optional[str]:
    for l in lines:
        if "PROPRIET" in l.upper():
            m = _CPF_MASKED_RE.search(l)
            if m:
                return m.group(1)
    return None


def _extract_date(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{d.zfill(2)}/{mth.zfill(2)}/{y}"


# =========================
# Soft checks
# =========================
def _renavam_is_valid(renavam: Optional[str]) -> Tuple[bool, str]:
    if not renavam or len(renavam) != 11:
        return False, "invalid"
    base = renavam[:10]
    dv_expected = int(renavam[10])
    weights = [2, 3, 4, 5, 6, 7, 8, 9]

    total, w = 0, 0
    for d in reversed(base):
        total += int(d) * weights[w]
        w = (w + 1) % len(weights)

    dv = 11 - (total % 11)
    if dv >= 10:
        dv = 0
    return dv == dv_expected, "ok" if dv == dv_expected else "dv_mismatch"


def _run_soft_checks(out: Dict[str, Any]) -> None:
    dbg = out["debug"]
    checks = dbg["checks"]
    warnings = dbg["warnings"]

    ren = out.get("renavam")
    ok, reason = _renavam_is_valid(ren)
    checks["renavam"] = {
        "raw": ren,
        "normalized": ren or "",
        "dv_ok": ok,
        "reason": reason,
    }
    if ren and not ok:
        warnings.append(f"RENAVAM inválido ({reason})")
