from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

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
    for l in lines:
        if _RENAVAM_ANCHOR_RE.search(l):
            r = _extract_renavam_from_line(l)
            if r:
                return r
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


def _money_in_line(lines: List[str], key: str) -> Optional[str]:
    for l in lines:
        if key in l.upper():
            m = _MONEY_RE.search(l)
            if m:
                return m.group(0)
    return None


# =========================
# DV cross-check (soft): CPF
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
        return False, "bad_length"
    if d == d[0] * 11:
        return False, "all_equal"

    def dv_calc(digs: str) -> int:
        s = sum(int(d) * w for d, w in zip(digs, range(len(digs) + 1, 1, -1)))
        r = 11 - (s % 11)
        return 0 if r >= 10 else r

    dv1 = dv_calc(d[:9])
    dv2 = dv_calc(d[:9] + str(dv1))
    if d[-2:] != f"{dv1}{dv2}":
        return False, "dv_mismatch"

    return True, "ok"


# =========================
# API pública
# =========================

def analyze_atpv(
    *,
    text: str,
    min_text_len_threshold: int = MIN_TEXT_LEN_THRESHOLD_DEFAULT,
) -> Dict[str, Any]:
    text = _normalize(text)

    if len(text) < min_text_len_threshold:
        return {
            "ok": False,
            "reason": "text_too_short",
            "data": {},
            "warnings": [],
        }

    data = _extract_fields(text)

    warnings: List[str] = []
    checks: Dict[str, Any] = {}

    for k in ("vendedor_cpf_cnpj", "comprador_cpf_cnpj"):
        raw = data.get(k)
        raw_str = raw or ""
        norm = _only_digits(raw_str)
        ok, reason = _cpf_is_valid(norm)

        checks[k] = {
            "raw": raw,
            "normalized": norm,
            "dv_ok": bool(ok),
            "reason": reason,
        }

        if norm and len(norm) == 11 and not ok and reason in ("all_equal", "dv_mismatch"):
            label = "CPF_VENDEDOR" if k == "vendedor_cpf_cnpj" else "CPF_COMPRADOR"
            if reason == "all_equal":
                warnings.append(f"{label} inválido (dígitos repetidos) (extraído='{raw_str}')")
            else:
                warnings.append(f"{label} DV inválido (extraído='{raw_str}')")

    return {
        "ok": True,
        "data": data,
        "checks": checks,
        "warnings": warnings,
    }
