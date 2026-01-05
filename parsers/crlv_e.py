from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 800

# =========================
# Regexes básicas
# =========================
_PLACA_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")
_RENAVAM_RE = re.compile(r"\b(\d{11})\b")
_CHASSI_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_ANO_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_DATE_RE = re.compile(r"\b([0-3]?\d)/([01]?\d)/((?:19|20)\d{2})\b")

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
    lines = _lines(text)

    extracted = _extract_fields(lines)

    debug_pages = []
    for i in range(max(len(pages_native_len), len(pages_ocr_len))):
        debug_pages.append(
            {
                "page": i + 1,
                "native_len": pages_native_len[i] if i < len(pages_native_len) else 0,
                "ocr_len": pages_ocr_len[i] if i < len(pages_ocr_len) else 0,
            }
        )

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
        },
    }

    # Blindagem mínima obrigatória
    dbg = out.setdefault("debug", {})
    dbg.setdefault("checks", {})
    dbg.setdefault("warnings", [])

    _run_soft_checks(out)

    return out


# =========================
# Extração de texto
# =========================
def _extract_native_text(pdf_path: str) -> Tuple[str, List[int]]:
    import pdfplumber

    texts, lens = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            texts.append(t)
            lens.append(len(t))
    return "\n".join(texts).strip(), lens


def _ocr_pdf_to_text(pdf_path: str, *, dpi: int) -> Tuple[str, List[int]]:
    from pdf2image import convert_from_path
    import pytesseract

    texts, lens = [], []
    for img in convert_from_path(pdf_path, dpi=dpi):
        t = pytesseract.image_to_string(img, lang="por") or ""
        texts.append(t.strip())
        lens.append(len(t))
    return "\n".join(texts).strip(), lens


# =========================
# Parsing por labels
# =========================
def _extract_fields(lines: List[str]) -> Dict[str, Any]:
    upper = [l.upper() for l in lines]

    placa = _first_match(_PLACA_RE, " ".join(upper))
    renavam = _first_match(_RENAVAM_RE, " ".join(upper))
    chassi = _first_match(_CHASSI_RE, " ".join(upper))

    marca_modelo = _value_after_label(upper, lines, "MARCA/MODELO")
    categoria = _value_after_label(upper, lines, "CATEGORIA")
    combustivel = _value_after_label(upper, lines, "COMBUSTÍVEL")
    cor = _value_after_label(upper, lines, "COR")

    ano_fab_mod = _value_after_label(upper, lines, "ANO FAB/MOD")
    ano_fabricacao, ano_modelo = _split_ano_fab_mod(ano_fab_mod)

    proprietario_nome = _value_after_label(upper, lines, "PROPRIETÁRIO")
    proprietario_doc = _extract_doc(lines)

    uf_licenciamento = _value_after_label(upper, lines, "UF")
    local_emissao = _value_after_label(upper, lines, "LOCAL")
    data_emissao = _first_match(_DATE_RE, " ".join(lines))
    if data_emissao:
        data_emissao = f"{data_emissao[0]}/{data_emissao[1]}/{data_emissao[2]}"

    return {
        "placa": placa,
        "renavam": renavam,
        "chassi": chassi,
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


def _lines(text: str) -> List[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


def _first_match(rx: re.Pattern, s: str):
    m = rx.search(s)
    return m.group(1) if m else None


def _value_after_label(upper: List[str], raw: List[str], label: str) -> Optional[str]:
    for i, u in enumerate(upper):
        if u.startswith(label):
            parts = raw[i].split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
            if i + 1 < len(raw):
                return raw[i + 1].strip()
    return None


def _split_ano_fab_mod(v: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not v:
        return None, None
    years = _ANO_RE.findall(v)
    if len(years) >= 2:
        return years[0], years[1]
    if len(years) == 1:
        return years[0], years[0]
    return None, None


def _extract_doc(lines: List[str]) -> Optional[str]:
    for l in lines:
        m = _CPF_RE.search(l) or _CNPJ_RE.search(l)
        if m:
            return m.group(1)
    return None


# =========================
# Soft checks
# =========================
def _renavam_is_valid(renavam: Optional[str]) -> Tuple[bool, str]:
    if not renavam:
        return False, "empty"
    if len(renavam) != 11:
        return False, "bad_length"

    base = renavam[:10]
    dv_expected = int(renavam[10])
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    w = 0
    for d in reversed(base):
        total += int(d) * weights[w]
        w = (w + 1) % len(weights)
    dv = 11 - (total % 11)
    if dv >= 10:
        dv = 0
    return (dv == dv_expected), "ok" if dv == dv_expected else "dv_mismatch"


def _run_soft_checks(out: Dict[str, Any]) -> None:
    dbg = out["debug"]
    checks = dbg["checks"]
    warnings = dbg["warnings"]

    # RENAVAM
    ren = out.get("renavam")
    ok, reason = _renavam_is_valid(ren)
    checks["renavam"] = {
        "raw": ren,
        "normalized": ren or "",
        "dv_ok": bool(ok),
        "reason": reason,
    }
    if ren and not ok and reason in ("bad_length", "dv_mismatch"):
        warnings.append(f"RENAVAM inválido ({reason})")

    # Coerência ano
    af = out.get("ano_fabricacao")
    am = out.get("ano_modelo")
    if af and am:
        try:
            if int(am) < int(af):
                warnings.append("ANO_MODELO menor que ANO_FABRICACAO")
        except ValueError:
            pass
