
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ======================================================================================
# Normalizers
# ======================================================================================

_RE_DIGITS = re.compile(r"\d+")


def _only_digits(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    digits = "".join(_RE_DIGITS.findall(s))
    return digits or None


def _remove_accents(txt: str) -> str:
    nfkd = unicodedata.normalize("NFKD", txt)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def _normalize_name(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s = _remove_accents(s).upper()
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _normalize_date(v: Optional[str]) -> Optional[str]:
    """
    Normalize to 'DD/MM/YYYY' when possible.
    Accepts:
      - '12/07/1987'
      - '1987-07-12'
      - '1987/07/12'
      - '12-07-1987'
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.fullmatch(r"(\d{4})[-/](\d{2})[-/](\d{2})", s)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        return f"{dd}/{mm}/{yyyy}"

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.fullmatch(r"(\d{2})[-/](\d{2})[-/](\d{4})", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd}/{mm}/{yyyy}"

    # last resort parsing
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue

    return None


def _normalize_value(field: str, v: Optional[Any]) -> Optional[str]:
    if v is None:
        return None
    if field == "cpf":
        return _only_digits(str(v))
    if field == "nome":
        return _normalize_name(str(v))
    if field == "data_nascimento":
        return _normalize_date(str(v))
    s = str(v).strip()
    return s or None


def _now_utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ======================================================================================
# Extractors (field mapping between proposta and CNH)
# ======================================================================================

def _get_proposta_value(field: str, proposta_data: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not proposta_data:
        return None

    if field == "cpf":
        return proposta_data.get("cpf")

    if field == "nome":
        # proposta usa nome_financiado (mas tolera 'nome' se existir)
        return proposta_data.get("nome_financiado") or proposta_data.get("nome")

    if field == "data_nascimento":
        return proposta_data.get("data_nascimento")

    return proposta_data.get(field)


def _get_cnh_value(field: str, cnh_data: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not cnh_data:
        return None

    if field == "cpf":
        return cnh_data.get("cpf")

    if field == "nome":
        return cnh_data.get("nome") or cnh_data.get("nome_completo")

    if field == "data_nascimento":
        return cnh_data.get("data_nascimento")

    return cnh_data.get(field)


# ======================================================================================
# Report builder
# ======================================================================================

def _build_item(field: str, proposta_raw: Optional[Any], cnh_raw: Optional[Any]) -> Dict[str, Any]:
    proposta_norm = _normalize_value(field, proposta_raw)
    cnh_norm = _normalize_value(field, cnh_raw)

    proposta_obj = {"raw": proposta_raw, "normalized": proposta_norm}
    cnh_obj = {"raw": cnh_raw, "normalized": cnh_norm}

    if proposta_norm is None and cnh_norm is None:
        status = "not_comparable"
        explain = "Campo ausente ou não normalizável em ambos os documentos; comparação não aplicável."
    elif proposta_norm is None or cnh_norm is None:
        status = "missing"
        side = "proposta" if proposta_norm is None else "cnh"
        explain = f"Campo ausente ou não normalizável em {side}; não é possível comparar."
    else:
        if proposta_norm == cnh_norm:
            status = "equal"
            explain = "Valores normalizados coincidem entre Proposta e CNH."
        else:
            status = "different"
            explain = "Valores normalizados divergem entre Proposta e CNH."

    return {
        "field": field,
        "status": status,
        "proposta": proposta_obj,
        "cnh": cnh_obj,
        "explain": explain,
    }


def build_proposta_cnh_report(
    case_id: str,
    proposta_data: Optional[Dict[str, Any]],
    cnh_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Relatório explicável (sem decisão) de comparação Proposta↔CNH.

    Contrato esperado pelos testes:
      - report["validator"] == "proposta_vs_cnh"
      - report["sections"] com chaves: equal, different, missing, not_comparable
      - cada item contém: field, status, proposta{raw,normalized}, cnh{raw,normalized}, explain(str)
      - report["summary"]["total_fields"] >= 3
      - não contém 'approved', 'rejected', 'decision'
    """
    fields_to_compare = ["cpf", "nome", "data_nascimento"]

    sections: Dict[str, list] = {
        "equal": [],
        "different": [],
        "missing": [],
        "not_comparable": [],
    }

    for field in fields_to_compare:
        proposta_raw = _get_proposta_value(field, proposta_data)
        cnh_raw = _get_cnh_value(field, cnh_data)

        item = _build_item(field=field, proposta_raw=proposta_raw, cnh_raw=cnh_raw)
        sections[item["status"]].append(item)

    summary = {
        "total_fields": len(fields_to_compare),
        "equal": len(sections["equal"]),
        "different": len(sections["different"]),
        "missing": len(sections["missing"]),
        "not_comparable": len(sections["not_comparable"]),
    }

    return {
        "case_id": case_id,
        "validator": "proposta_vs_cnh",
        "created_at": _now_utc_iso_z(),
        "summary": summary,
        "sections": sections,
    }
