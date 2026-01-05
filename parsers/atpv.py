from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 800

_PLATE_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_MONEY_RE = re.compile(r"(R\$\s*)?(\d{1,3}(\.\d{3})*|\d+),\d{2}\b")

SELLER_SECTION = "IDENTIFICAÇÃO DO VENDEDOR"
BUYER_SECTION = "IDENTIFICAÇÃO DO COMPRADOR"

# Palavras que INVALIDAM valor semântico
FORBIDDEN_VALUE_TOKENS = (
    "CPF",
    "CNPJ",
    "EMAIL",
    "E MAIL",
    "MUNICIPIO",
    "MUNICÍPIO",
    "RESIDENCIA",
    "RESIDÊNCIA",
    "UF",
    "LOCAL",
)

_NAME_CHARS_RE = re.compile(r"[^A-ZÀ-Ü ]")


def analyze_atpv(
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
    extracted = _extract_fields(text)

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

    # ============================================================
    # Blindagem de sanidade: checks/warnings SEMPRE presentes
    # e cross-check DV (CPF/RENAVAM) SEM bloquear extração
    # ============================================================
    dbg = out.setdefault("debug", {})
    dbg.setdefault("checks", {})
    dbg.setdefault("warnings", [])

    _run_soft_dv_checks(out)

    return out


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
# Extração segura
# =========================

def _extract_fields(text: str) -> Dict[str, Any]:
    norm = _normalize(text)
    lines = _lines(norm)

    seller = _slice_between(lines, SELLER_SECTION, BUYER_SECTION)
    buyer = _slice_from(lines, BUYER_SECTION)

    vendedor_nome = _safe_value(_normalize_name(_value_after_label(seller, "NOME")))
    vendedor_doc = _extract_doc(seller)

    comprador_nome = _safe_value(_normalize_name(_value_after_label(buyer, "NOME")))
    comprador_doc = _extract_doc(buyer)

    placa = _safe_value(_first_match(_PLATE_RE, norm))
    chassi = _safe_value(_first_match(_VIN_RE, norm))
    valor = _safe_value(_money_in_line(lines, "VALOR"))

    return {
        "placa": placa,
        "renavam": None,  # EXEMPLO_01 não suporta parse seguro
        "chassi": chassi,
        "valor_venda": valor,
        "comprador_nome": comprador_nome,
        "vendedor_nome": vendedor_nome,
        "comprador_cpf_cnpj": _only_digits(comprador_doc) if comprador_doc else None,
        "vendedor_cpf_cnpj": _only_digits(vendedor_doc) if vendedor_doc else None,
    }


def _safe_value(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    u = v.upper()
    if any(t in u for t in FORBIDDEN_VALUE_TOKENS):
        return None
    return v


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u00ad", "")).strip()


def _lines(s: str) -> List[str]:
    return [l.strip() for l in s.splitlines() if l.strip()]


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _normalize_name(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = _NAME_CHARS_RE.sub(" ", s.upper())
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t if len(t.split()) >= 2 else None


def _first_match(rx: re.Pattern, s: str) -> Optional[str]:
    m = rx.search(s)
    return m.group(1) if m else None


def _slice_between(lines: List[str], a: str, b: str) -> List[str]:
    try:
        i = next(i for i, l in enumerate(lines) if a in l.upper())
    except StopIteration:
        return []
    try:
        j = next(j for j, l in enumerate(lines[i + 1 :], i + 1) if b in l.upper())
        return lines[i:j]
    except StopIteration:
        return lines[i:]


def _slice_from(lines: List[str], a: str) -> List[str]:
    try:
        i = next(i for i, l in enumerate(lines) if a in l.upper())
        return lines[i:]
    except StopIteration:
        return []


def _value_after_label(block: List[str], label: str) -> Optional[str]:
    for i, l in enumerate(block):
        if l.upper() == label.upper():
            return block[i + 1] if i + 1 < len(block) else None
    return None


def _extract_doc(block: List[str]) -> Optional[str]:
    for l in block:
        m = _CPF_RE.search(l) or _CNPJ_RE.search(l)
        if m:
            return m.group(1)
    return None


def _money_in_line(lines: List[str], key: str) -> Optional[str]:
    for l in lines:
        if key in l.upper():
            m = _MONEY_RE.search(l)
            if m:
                return m.group(0)
    return None


# =========================
# DV cross-check (soft): CPF + RENAVAM
# =========================

def _cpf_is_valid(cpf_digits: str) -> Tuple[bool, str]:
    """
    cpf_digits: apenas dígitos.
    Retorna (ok, reason): ok|empty|bad_length|all_equal|dv_mismatch|not_applicable
    """
    d = _only_digits(cpf_digits or "")
    if not d:
        return False, "empty"
    if len(d) != 11:
        # Não é CPF (pode ser CNPJ, ou lixo). Não gera warning.
        return False, "bad_length"
    if d == d[0] * 11:
        return False, "all_equal"

    nums = [int(x) for x in d]

    s1 = sum(nums[i] * (10 - i) for i in range(9))
    dv1 = (s1 * 10) % 11
    dv1 = 0 if dv1 == 10 else dv1

    s2 = sum(nums[i] * (11 - i) for i in range(10))
    dv2 = (s2 * 10) % 11
    dv2 = 0 if dv2 == 10 else dv2

    if nums[9] == dv1 and nums[10] == dv2:
        return True, "ok"
    return False, "dv_mismatch"


def _renavam_is_valid(renavam_digits: str) -> Tuple[bool, str]:
    """
    renavam_digits: apenas dígitos.
    Retorna (ok, reason): ok|empty|bad_length|dv_mismatch
    """
    d = _only_digits(renavam_digits or "")
    if not d:
        return False, "empty"
    if len(d) != 11:
        return False, "bad_length"

    base = d[:10]
    dv_expected = int(d[10])

    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    w_idx = 0
    for ch in reversed(base):
        total += int(ch) * weights[w_idx]
        w_idx = (w_idx + 1) % len(weights)

    mod = total % 11
    dv_calc = 11 - mod
    if dv_calc >= 10:
        dv_calc = 0

    if dv_calc == dv_expected:
        return True, "ok"
    return False, "dv_mismatch"


def _run_soft_dv_checks(out: Dict[str, Any]) -> None:
    """
    Anota em debug.checks e debug.warnings sem bloquear extração.
    Garante determinismo e presença das chaves.
    """
    dbg = out.setdefault("debug", {})
    checks: Dict[str, Any] = dbg.setdefault("checks", {})
    warnings: List[str] = dbg.setdefault("warnings", [])

    # Ordem determinística
    keys = ("vendedor_cpf_cnpj", "comprador_cpf_cnpj", "renavam")

    for k in keys:
        raw = out.get(k)
        raw_str = "" if raw is None else str(raw)
        norm = _only_digits(raw_str)

        if k == "renavam":
            ok, reason = _renavam_is_valid(norm)
            checks[k] = {
                "raw": raw,
                "normalized": norm,
                "dv_ok": bool(ok),
                "reason": reason,
            }

            # Warning só quando existe valor e é realmente um problema de RENAVAM
            if norm and not ok and reason in ("bad_length", "dv_mismatch"):
                if reason == "bad_length":
                    warnings.append(f"RENAVAM com tamanho inválido (extraído='{raw_str}')")
                else:
                    warnings.append(f"RENAVAM DV inválido (extraído='{raw_str}')")

        else:
            # Campo cpf_cnpj: validamos CPF apenas quando 11 dígitos; se não for 11, não avisamos
            ok, reason = _cpf_is_valid(norm)
            checks[k] = {
                "raw": raw,
                "normalized": norm,
                "dv_ok": bool(ok),
                "reason": reason,
            }

            # Warning apenas se parecer CPF (11 dígitos) e falhar de verdade
            if norm and len(norm) == 11 and not ok and reason in ("all_equal", "dv_mismatch"):
                label = "CPF_VENDEDOR" if k == "vendedor_cpf_cnpj" else "CPF_COMPRADOR"
                if reason == "all_equal":
                    warnings.append(f"{label} inválido (dígitos repetidos) (extraído='{raw_str}')")
                else:
                    warnings.append(f"{label} DV inválido (extraído='{raw_str}')")
