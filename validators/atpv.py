from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Dict, List, Optional


# =========================
# Resultado
# =========================

@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: List[str]
    normalized: Dict[str, Any]


# =========================
# Regras de contrato (hard)
# =========================
REQUIRED_FIELDS = (
    "placa",
    "renavam",
    "chassi",
    "valor_venda",
    "comprador_cpf_cnpj",
    "comprador_nome",
    "vendedor_nome",
)

_PLATE_RE = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")  # Mercosul/antiga compat
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # VIN 17 chars, exclui I,O,Q

# Nome humano simples: >= 2 tokens, apenas letras/acentos/espaços
_NAME_CHARS_RE = re.compile(r"[^A-ZÀ-Ü ]")
_NAME_OK_RE = re.compile(r"^[A-ZÀ-Ü ]+$")

_BAD_NAME_SNIPPETS = (
    "IDENTIFICAÇÃO DO VENDEDOR",
    "IDENTIFICACAO DO VENDEDOR",
    "IDENTIFICAÇÃO DO COMPRADOR",
    "IDENTIFICACAO DO COMPRADOR",
    "O REGISTRO DESTE VEÍCULO",
    "O REGISTRO DESTE VEICULO",
    "CÓDIGO RENAVAM",
    "CODIGO RENAVAM",
    "COR PREDOMINANTE",
    "CHASSI LOCAL",
    "PLACA",
    "RENAVAM",
    "VALOR",
    "MUNICÍPIO",
    "MUNICIPIO",
)

# Aceita dd/mm/aaaa (se você voltar a usar datas em outra camada)
_DATE_FMT = "%d/%m/%Y"


def validate_atpv(parsed: Dict[str, Any]) -> ValidationResult:
    """
    Validador duro para ATPV (camada de consistência + DV):
      - RENAVAM: zfill(11) se 9/10, valida DV se 11
      - CPF/CNPJ: valida DV conforme tamanho
      - nomes: valida "nome humano"
      - regras cruzadas: renavam_is_cpf, renavam_equals_comprador_doc
    """
    normalized = _normalize_keys(parsed)
    errors: List[str] = []

    # 1) Presença obrigatória
    for k in REQUIRED_FIELDS:
        if not _has_value(normalized.get(k)):
            errors.append(f"missing_required:{k}")

    # 2) Placa
    if _has_value(normalized.get("placa")):
        placa = _normalize_placa(str(normalized["placa"]))
        normalized["placa"] = placa
        if not _PLATE_RE.match(placa):
            errors.append("invalid:placa_format")

    # 3) Chassi (VIN)
    if _has_value(normalized.get("chassi")):
        chassi = _normalize_vin(str(normalized["chassi"]))
        normalized["chassi"] = chassi
        if not _VIN_RE.match(chassi):
            errors.append("invalid:chassi_vin_format")

    # 4) Valor venda
    if _has_value(normalized.get("valor_venda")):
        v = _parse_brl_money(normalized["valor_venda"])
        if v is None:
            errors.append("invalid:valor_venda_format")
        else:
            if v <= 0:
                errors.append("invalid:valor_venda_nonpositive")
            normalized["valor_venda"] = v

    # 5) Nome comprador
    if _has_value(normalized.get("comprador_nome")):
        cn = _normalize_name(str(normalized["comprador_nome"]))
        normalized["comprador_nome"] = cn
        if not _is_human_name(cn):
            errors.append("invalid:comprador_nome")

    # 6) Nome vendedor
    if _has_value(normalized.get("vendedor_nome")):
        vn = _normalize_name(str(normalized["vendedor_nome"]))
        normalized["vendedor_nome"] = vn
        if not _is_human_name(vn):
            errors.append("invalid:vendedor_nome")

    # 7) CPF/CNPJ comprador (DV)
    comprador_doc_raw = normalized.get("comprador_cpf_cnpj")
    if _has_value(comprador_doc_raw):
        comprador_doc = _only_digits(str(comprador_doc_raw))
        normalized["comprador_cpf_cnpj"] = comprador_doc
        if len(comprador_doc) == 11:
            if not _is_valid_cpf(comprador_doc):
                errors.append("invalid:comprador_cpf")
        elif len(comprador_doc) == 14:
            if not _is_valid_cnpj(comprador_doc):
                errors.append("invalid:comprador_cnpj")
        else:
            errors.append("invalid:comprador_cpf_cnpj_len")

    # 8) RENAVAM: zfill + DV
    renavam_raw = normalized.get("renavam")
    renavam_norm: Optional[str] = None
    if _has_value(renavam_raw):
        renavam_norm = _normalize_renavam_to_11(str(renavam_raw))
        normalized["renavam"] = renavam_norm

        if renavam_norm is None:
            errors.append("invalid:renavam_len")
        else:
            # Agora é 11 => valida DV
            if not _is_valid_renavam_11(renavam_norm):
                errors.append("invalid:renavam_checkdigit")

            # Se RENAVAM também for CPF válido => fortíssimo sinal de campo trocado
            if _is_valid_cpf(renavam_norm):
                errors.append("invalid:renavam_is_cpf")

    # 9) Regras cruzadas
    comprador_doc = normalized.get("comprador_cpf_cnpj")
    if renavam_norm and comprador_doc and renavam_norm == comprador_doc:
        errors.append("invalid:renavam_equals_comprador_doc")

    return ValidationResult(is_valid=(len(errors) == 0), errors=errors, normalized=normalized)


# =========================
# Normalização de chaves
# =========================

def _normalize_keys(parsed: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(parsed) if isinstance(parsed, dict) else {}

    # Canonical comprador_cpf_cnpj
    if not _has_value(out.get("comprador_cpf_cnpj")):
        if _has_value(out.get("cpf")):
            out["comprador_cpf_cnpj"] = out.get("cpf")
        elif _has_value(out.get("cnpj")):
            out["comprador_cpf_cnpj"] = out.get("cnpj")

    # Canonical chassi
    if not _has_value(out.get("chassi")):
        for k in ("vin", "numero_chassi"):
            if _has_value(out.get(k)):
                out["chassi"] = out.get(k)
                break

    # Canonical valor_venda
    if not _has_value(out.get("valor_venda")):
        for k in ("valor_compra", "valor_transacao", "valor"):
            if _has_value(out.get(k)):
                out["valor_venda"] = out.get(k)
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


def _normalize_name(s: str) -> str:
    s = s.strip().upper()
    s = _NAME_CHARS_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _is_human_name(s: str) -> bool:
    if not s:
        return False
    if len(s) < 8:
        return False
    if any(bad in s for bad in _BAD_NAME_SNIPPETS):
        return False
    if not _NAME_OK_RE.match(s):
        return False
    parts = [p for p in s.split(" ") if p]
    if len(parts) < 2:
        return False
    # pelo menos 2 tokens com tamanho razoável
    if sum(1 for p in parts if len(p) >= 2) < 2:
        return False
    return True


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

    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


# =========================
# CPF / CNPJ (DV público)
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
# RENAVAM (normalização + DV)
# =========================

def _normalize_renavam_to_11(value: str) -> Optional[str]:
    """
    Regra do usuário:
      - 9 dígitos  -> zfill(11) (2 zeros à esquerda)
      - 10 dígitos -> zfill(11) (1 zero à esquerda)
      - 11 dígitos -> mantém
      - demais -> None
    """
    d = _only_digits(value)
    if len(d) in (9, 10):
        return d.zfill(11)
    if len(d) == 11:
        return d
    return None


def _is_valid_renavam_11(ren: str) -> bool:
    """
    DV RENAVAM 11 dígitos (método comum):
      - usa os 10 primeiros dígitos
      - pesos 2..9 repetindo da direita p/ esquerda
      - dv = (11 - (soma % 11)) % 11; se dv==10 -> 0
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
