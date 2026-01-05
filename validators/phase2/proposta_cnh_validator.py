# validators/phase2/proposta_cnh_validator.py
from __future__ import annotations

from typing import Any, Dict, Optional, List
import re

JsonDict = Dict[str, Any]


# =========================
# Normalização
# =========================

def _norm_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    return " ".join(v.upper().split())


def _norm_cpf(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    digits = "".join(c for c in v if c.isdigit())
    return digits if len(digits) == 11 else None


def _norm_date(v: Optional[str]) -> Optional[str]:
    if not v:
        return None

    s = str(v).strip()

    # DD/MM/YYYY → YYYY-MM-DD
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.groups()
        return f"{yyyy}-{mm}-{dd}"

    # YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s

    return None


# =========================
# Helpers
# =========================

def _get(d: Dict[str, Any], key: str) -> Any:
    return d.get(key) if isinstance(d, dict) else None


def _derive_nome_mae_from_cnh(cnh: Dict[str, Any]) -> Optional[str]:
    filiacao = cnh.get("filiacao")
    if isinstance(filiacao, list) and len(filiacao) >= 2:
        return filiacao[1]
    return None


# =========================
# Builder Phase 2
# =========================

def build_proposta_cnh_report(
    *,
    case_id: str,
    proposta_data: Optional[Dict[str, Any]] = None,
    cnh_data: Optional[Dict[str, Any]] = None,
    proposta_doc: Optional[Dict[str, Any]] = None,
    cnh_doc: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> JsonDict:
    proposta = proposta_data or proposta_doc or {}
    cnh = cnh_data or cnh_doc or {}
    meta = meta or {}

    fields: List[Dict[str, Any]] = []

    def compare(field: str, p_raw, c_raw, norm_fn, *, c_strategy="path", c_path=None):
        p_norm = norm_fn(p_raw)
        c_norm = norm_fn(c_raw)

        if p_norm is None and c_norm is None:
            status = "missing"
            detail = "missing_both"
            explain = "Campo ausente ou ilegível em ambos os documentos."
        elif p_norm is None:
            status = "missing"
            detail = "missing_proposta"
            explain = "Campo presente na CNH e ausente ou ilegível na Proposta."
        elif c_norm is None:
            status = "missing"
            detail = "missing_cnh"
            explain = "Campo presente na Proposta e ausente ou ilegível na CNH."
        elif p_norm == c_norm:
            status = "equal"
            detail = None
            explain = "Valores normalizados são idênticos entre Proposta e CNH."
        else:
            status = "different"
            detail = None
            explain = "Valores normalizados divergem entre Proposta e CNH."

        fields.append({
            "field": field,
            "status": status,
            "status_detail": detail,
            "explain": explain,
            "proposta": {
                "raw": p_raw,
                "normalized": p_norm,
                "strategy": "path",
            },
            "cnh": {
                "raw": c_raw,
                "normalized": c_norm,
                "strategy": c_strategy,
                "path": c_path,
            },
        })

    # ===== Comparações =====

    compare("cpf",
        _get(proposta, "cpf"),
        _get(cnh, "cpf"),
        _norm_cpf,
        c_path="cpf",
    )

    compare("nome",
        _get(proposta, "nome_financiado"),
        _get(cnh, "nome"),
        _norm_str,
        c_path="nome",
    )

    compare("data_nascimento",
        _get(proposta, "data_nascimento"),
        _get(cnh, "data_nascimento"),
        _norm_date,
        c_path="data_nascimento",
    )

    compare("cidade_nascimento",
        _get(proposta, "cidade_nascimento"),
        _get(cnh, "cidade_nascimento"),
        _norm_str,
        c_path="cidade_nascimento",
    )

    compare("uf_nascimento",
        _get(proposta, "uf"),
        _get(cnh, "uf_nascimento"),
        _norm_str,
        c_path="uf_nascimento",
    )

    compare("nome_mae",
        _get(proposta, "nome_mae"),
        _derive_nome_mae_from_cnh(cnh),
        _norm_str,
        c_strategy="derive",
        c_path="filiacao[1]",
    )

    summary = {
        "total_fields": len(fields),
        "comparable": len(fields),
        "equal": sum(f["status"] == "equal" for f in fields),
        "different": sum(f["status"] == "different" for f in fields),
        "missing": sum(f["status"] == "missing" for f in fields),
        "not_comparable": 0,
    }

    return {
        "validator": "proposta_vs_cnh",
        "case_id": case_id,
        "summary": summary,
        "sections": {
            "all": fields,
            "equal": [f for f in fields if f["status"] == "equal"],
            "different": [f for f in fields if f["status"] == "different"],
            "missing": [f for f in fields if f["status"] == "missing"],
        },
        "meta": meta,
    }
