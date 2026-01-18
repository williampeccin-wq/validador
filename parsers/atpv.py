from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

# Reusa normalização + DV RENAVAM do validador duro (best-effort só seta se válido)
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.atpv import _normalize_renavam_to_11 as _normalize_renavam_to_11  # type: ignore

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 800

_PLATE_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_MONEY_RE = re.compile(r"(R\$\s*)?(\d{1,3}(\.\d{3})*|\d+),\d{2}\b")

_RENAVAM_ANCHOR_RE = re.compile(r"\bRENAVAM\b", re.IGNORECASE)

SELLER_SECTION = "IDENTIFICAÇÃO DO VENDEDOR"
BUYER_SECTION = "IDENTIFICAÇÃO DO COMPRADOR"


# =========================
# Helpers básicos
# =========================

def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _normalize(s: str) -> str:
    return (s or "").replace("\x00", " ").strip()


def _lines(s: str) -> List[str]:
    return [l.strip() for l in (s or "").splitlines() if l.strip()]


def _safe_value(v: Optional[str]) -> Optional[str]:
    return v if v else None


def _first_match(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text or "")
    return m.group(1) if m else None


def _normalize_name(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return " ".join(s.split())


def _slice_between(lines: List[str], start: str, end: str) -> List[str]:
    out, take = [], False
    for l in lines:
        if start in l:
            take = True
            continue
        if end in l and take:
            break
        if take:
            out.append(l)
    return out


def _slice_from(lines: List[str], start: str) -> List[str]:
    out, take = [], False
    for l in lines:
        if start in l:
            take = True
            continue
        if take:
            out.append(l)
    return out


# =========================
# RENAVAM (best-effort)
# =========================

def _extract_renavam_from_line(line: str) -> Optional[str]:
    """
    Extrai RENAVAM apenas se a âncora RENAVAM estiver na MESMA linha.
    Regra conservadora para evitar falso positivo.
    """
    if not line or not _RENAVAM_ANCHOR_RE.search(line):
        return None

    digits = _only_digits(line)

    # Preferencialmente 11 dígitos; aceitar 9–11 apenas com âncora forte
    if len(digits) == 11:
        return digits
    if 9 <= len(digits) <= 11:
        return digits

    return None


def _extract_renavam(lines: List[str]) -> Optional[str]:
    """Extrai RENAVAM com heurística conservadora.

    Regras:
      1) Preferir âncora + dígitos na mesma linha.
      2) Se a âncora estiver sozinha (sem dígitos), olhar 1 linha abaixo (layout tabular comum).
      3) Só retorna se normalizar para 11 e DV for válido (evita falso positivo e evita quebrar Phase2).
    """
    for i, l in enumerate(lines):
        if not _RENAVAM_ANCHOR_RE.search(l):
            continue

        # Caso 1: mesma linha
        r = _extract_renavam_from_line(l)
        if r:
            r11 = _normalize_renavam_to_11(r)
            if r11 and _is_valid_renavam_11(r11):
                return r11

        # Caso 2: âncora sem dígitos -> linha seguinte (bem conservador)
        if i + 1 < len(lines):
            nxt = lines[i + 1]

            # "pureza": evitar pegar texto solto
            nxt_digits = _only_digits(nxt)
            nxt_noise = re.sub(r"[0-9\s\.\-]", "", nxt)
            if nxt_digits and (9 <= len(nxt_digits) <= 11) and len(nxt_noise.strip()) <= 1:
                r11 = _normalize_renavam_to_11(nxt_digits)
                if r11 and _is_valid_renavam_11(r11):
                    return r11

    return None


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

    renavam = _extract_renavam(lines)

    data: Dict[str, Any] = {
        "placa": placa,
        "chassi": chassi,
        "valor": valor,
        "vendedor_nome": vendedor_nome,
        "vendedor_cpf_cnpj": vendedor_doc,
        "comprador_nome": comprador_nome,
        "comprador_cpf_cnpj": comprador_doc,
    }

    # NÃO quebrar goldens: só seta se existir
    if renavam:
        data["renavam"] = renavam

    return data


def _value_after_label(lines: List[str], label: str) -> Optional[str]:
    label = label.upper()
    for l in lines:
        if label in l.upper():
            parts = l.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return None


def _extract_doc(block: List[str]) -> Optional[str]:
    for l in block:
        m = _CPF_RE.search(l) or _CNPJ_RE.search(l)
        if m:
            return m.group(1)
    return None


def _money_in_line(lines: List[str], label: str) -> Optional[str]:
    label = label.upper()
    for l in lines:
        if label in l.upper():
            m = _MONEY_RE.search(l)
            if m:
                return m.group(0).strip()
    return None


# =========================
# Public API
# =========================

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
    data = _extract_fields(text)

    debug_pages = [
        {
            "page": i + 1,
            "native_len": pages_native_len[i] if i < len(pages_native_len) else 0,
            "ocr_len": pages_ocr_len[i] if i < len(pages_ocr_len) else 0,
        }
        for i in range(max(len(pages_native_len), len(pages_ocr_len)))
    ]

    return {
        "ok": True,
        "data": data,
        "mode": mode,
        "debug": {
            "mode": mode,
            "native_text_len": len(native_text),
            "ocr_text_len": len(ocr_text),
            "min_text_len_threshold": min_text_len_threshold,
            "ocr_dpi": ocr_dpi,
            "pages": debug_pages,
            "warnings": [],
            "checks": {},
        },
    }


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
