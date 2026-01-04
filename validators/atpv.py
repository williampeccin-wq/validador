# validators/atpv.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Dict, List, Optional


# =========================
# Tipos / Resultado
# =========================

@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: List[str]
    normalized: Dict[str, Any]


# =========================
# Normalização de chaves
# =========================

REQUIRED_FIELDS = (
    "placa",
    "renavam",
    "chassi",
    "comprador_cpf_cnpj",
    "data_venda",
    "valor_venda",
)

_PLATE_RE = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")  # Mercosul/antiga compat
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # VIN 17 chars, exclui I,O,Q

# Aceita dd/mm/aaaa
_DATE_FMT = "%d/%m/%Y"


def validate_atpv(parsed: Dict[str, Any]) -> ValidationResult:
    """
    Validação dura (hard fail) para ATPV.

    Obrigatórios:
      - placa
      - renavam
      - chassi
      - comprador_cpf_cnpj
      - data_venda
      - valor_venda

    Retorna:
      - is_valid
      - errors (lista de strings estáveis)
      - normalized (campos normalizados)
    """
    normalized = _normalize_keys(parsed)

    errors: List[str] = []

    # 1) Obrigatórios: presença + não vazio
    missing = [k for k in REQUIRED_FIELDS if not _has_value(normalized.get(k))]
    if missing:
        for k in missing:
            errors.append(f"missing_required:{k}")

    # 2) Placa
    placa = normalized.get("placa")
    if _has_value(placa):
        placa_n = _normalize_placa(str(placa))
        normalized["placa"] = placa_n
        if not _PLATE_RE.match(placa_n):
            errors.append("invalid:placa_format")

    # 3) CPF/CNPJ comprador
    doc = normalized.get("comprador_cpf_cnpj")
    if _has_value(doc):
        doc_n = _only_digits(str(doc))
        normalized["comprador_cpf_cnpj"] = doc_n
        if len(doc_n) == 11:
            if not _is_valid_cpf(doc_n):
                errors.append("invalid:comprador_cpf")
        elif len(doc_n) == 14:
            if not _is_valid_cnpj(doc_n):
                errors.append("invalid:comprador_cnpj")
        else:
            errors.append("invalid:comprador_cpf_cnpj_len")

    # 4) RENAVAM
    renavam = normalized.get("renavam")
    if _has_value(renavam):
        ren_n = _only_digits(str(renavam))
        normalized["renavam"] = ren_n

        # RENAVAM não pode ser CPF/CNPJ válido (mesmo número)
        if len(ren_n) == 11 and _is_valid_cpf(ren_n):
            errors.append("invalid:renavam_is_cpf")
        if len(ren_n) == 14 and _is_valid_cnpj(ren_n):
            errors.append("invalid:renavam_is_cnpj")

        # Regra estrutural (aceita 9-11; se 11 valida DV)
        if len(ren_n) not in (9, 10, 11):
            errors.append("invalid:renavam_len")
        elif len(ren_n) == 11:
            if not _is_valid_renavam_11(ren_n):
                errors.append("invalid:renavam_checkdigit")

    # 4.5) Conflito cruzado: RENAVAM não pode ser igual ao doc do comprador,
    # mesmo que o doc esteja inválido como CPF/CNPJ.
    if _has_value(normalized.get("renavam")) and _has_value(normalized.get("comprador_cpf_cnpj")):
        if str(normalized["renavam"]) == str(normalized["comprador_cpf_cnpj"]):
            errors.append("invalid:renavam_equals_comprador_doc")

    # 5) Chassi (VIN)
    chassi = normalized.get("chassi")
    if _has_value(chassi):
        vin = _normalize_vin(str(chassi))
        normalized["chassi"] = vin
        if not _VIN_RE.match(vin):
            errors.append("invalid:chassi_vin_format")

    # 6) Data venda (dd/mm/aaaa)
    data_venda = normalized.get("data_venda")
    if _has_value(data_venda):
        dv = str(data_venda).strip()
        if not _is_valid_date(dv):
            errors.append("invalid:data_venda_format")
        else:
            normalized["data_venda"] = dv

    # 7) Valor venda (decimal > 0)
    valor_venda = normalized.get("valor_venda")
    if _has_value(valor_venda):
        parsed_val = _parse_brl_money(valor_venda)
        if parsed_val is None:
            errors.append("invalid:valor_venda_format")
        else:
            if parsed_val <= 0:
                errors.append("invalid:valor_venda_nonpositive")
            normalized["valor_venda"] = parsed_val

    return ValidationResult(is_valid=(len(errors) == 0), errors=errors, normalized=normalized)


def _normalize_keys(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte outputs heterogêneos do parser em um schema canonical.
    Não inventa valores: apenas mapeia chaves existentes.
    """
    out = dict(parsed) if isinstance(parsed, dict) else {}

    # Canonical: comprador_cpf_cnpj
    if not _has_value(out.get("comprador_cpf_cnpj")):
        # alguns outputs têm cpf/cnpj soltos
        if _has_value(out.get("cpf")):
            out["comprador_cpf_cnpj"] = out.get("cpf")
        elif _has_value(out.get("cnpj")):
            out["comprador_cpf_cnpj"] = out.get("cnpj")

    # Canonical: data_venda
    if not _has_value(out.get("data_venda")):
        for k in ("data_compra", "data_venda_compra", "data_transacao", "data"):
            if _has_value(out.get(k)):
                out["data_venda"] = out.get(k)
                break

    # Canonical: valor_venda
    if not _has_value(out.get("valor_venda")):
        for k in ("valor_compra", "valor_transacao", "valor"):
            if _has_value(out.get(k)):
                out["valor_venda"] = out.get(k)
                break

    # Canonical: chassi
    if not _has_value(out.get("chassi")):
        for k in ("vin", "numero_chassi"):
            if _has_value(out.get(k)):
                out["chassi"] = out.get(k)
                break

    return out


# =========================
# Helpers
# =========================

def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    return True


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _normalize_placa(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper().strip())


def _normalize_vin(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper().strip())


def _is_valid_date(s: str) -> bool:
    try:
        datetime.strptime(s.strip(), _DATE_FMT)
        return True
    except Exception:
        return False


def _parse_brl_money(v: Any) -> Optional[float]:
    """
    Aceita:
      - número (int/float)
      - "1234.56"
      - "1.234,56"
      - "R$ 1.234,56"
    Retorna float em reais.
    """
    if isinstance(v, (int, float)):
        return float(v)

    s = str(v).strip()
    if s == "":
        return None

    s = s.replace("R$", "").strip()
    s = re.sub(r"\s+", "", s)

    # "1.234,56" -> "1234.56"
    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


# =========================
# CPF / CNPJ
# =========================

def _is_valid_cpf(cpf: str) -> bool:
    cpf = _only_digits(cpf)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False

    def dv(nums: str, weights: List[int]) -> int:
        s = sum(int(n) * w for n, w in zip(nums, weights))
        r = s % 11
        return 0 if r < 2 else 11 - r

    d1 = dv(cpf[:9], list(range(10, 1, -1)))
    d2 = dv(cpf[:9] + str(d1), list(range(11, 1, -1)))
    return cpf[-2:] == f"{d1}{d2}"


def _is_valid_cnpj(cnpj: str) -> bool:
    cnpj = _only_digits(cnpj)
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False

    def dv(nums: str, weights: List[int]) -> int:
        s = sum(int(n) * w for n, w in zip(nums, weights))
        r = s % 11
        return 0 if r < 2 else 11 - r

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1

    d1 = dv(cnpj[:12], w1)
    d2 = dv(cnpj[:12] + str(d1), w2)
    return cnpj[-2:] == f"{d1}{d2}"


# =========================
# RENAVAM (11 dígitos)
# =========================

def _is_valid_renavam_11(ren: str) -> bool:
    """
    Validação de DV para RENAVAM 11 dígitos.

    Algoritmo:
      - pega os 10 primeiros dígitos
      - aplica pesos 2..9 repetindo da direita p/ esquerda
      - soma, mod 11; dv = (11 - mod) % 11; se dv == 10 -> 0
    """
    ren = _only_digits(ren)
    if len(ren) != 11:
        return False

    base = ren[:10]
    dv_expected = int(ren[10])

    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    w_i = 0
    for ch in reversed(base):
        total += int(ch) * weights[w_i]
        w_i = (w_i + 1) % len(weights)

    mod = total % 11
    dv = (11 - mod) % 11
    if dv == 10:
        dv = 0
    return dv == dv_expected
