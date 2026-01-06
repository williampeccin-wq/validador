from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ======================================================================================
# Helpers
# ======================================================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _norm_spaces_upper(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    return " ".join(v.upper().split())


def _digits_only(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    return "".join(c for c in v if c.isdigit()) or None


def _norm_date(v: Optional[str]) -> Optional[str]:
    """
    Normaliza datas comuns:
    - DD/MM/YYYY
    - YYYY-MM-DD
    Retorna YYYY-MM-DD ou None
    """
    if not v:
        return None

    v = v.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _safe_data(doc: Optional[dict]) -> dict:
    if not isinstance(doc, dict):
        return {}
    if "data" in doc and isinstance(doc["data"], dict):
        return doc["data"]
    return doc


def _explain_pair(raw: Optional[str], normalized: Optional[str]) -> Dict[str, Optional[str]]:
    return {"raw": raw, "normalized": normalized}


def _mk_explain(field: str, status: str, p: dict, c: dict) -> str:
    """
    String curta e determinística para auditoria/UX.
    """
    pr = p.get("raw")
    cr = c.get("raw")
    pn = p.get("normalized")
    cn = c.get("normalized")
    return (
        f"{field}: status={status}; "
        f"proposta(raw={pr}, norm={pn}); "
        f"cnh(raw={cr}, norm={cn})"
    )


# ======================================================================================
# Core builder
# ======================================================================================

def build_proposta_cnh_report(
    *,
    case_id: str,
    # aliases aceitos pelos testes
    proposta_data: Optional[dict] = None,
    cnh_data: Optional[dict] = None,
    # compat com runner
    proposta_payload: Optional[dict] = None,
    cnh_payload: Optional[dict] = None,
    proposta_read_error: Optional[str] = None,
    cnh_read_error: Optional[str] = None,
) -> Dict[str, Any]:

    proposta_src = proposta_data if proposta_data is not None else proposta_payload
    cnh_src = cnh_data if cnh_data is not None else cnh_payload

    proposta = _safe_data(proposta_src)
    cnh = _safe_data(cnh_src)

    # ===== raw values =====
    cpf_prop_raw = _norm_str(proposta.get("cpf"))
    cpf_cnh_raw = _norm_str(cnh.get("cpf"))

    nome_prop_raw = _norm_str(proposta.get("nome_financiado") or proposta.get("nome"))
    nome_cnh_raw = _norm_str(cnh.get("nome"))

    dn_prop_raw = _norm_str(proposta.get("data_nascimento"))
    dn_cnh_raw = _norm_str(cnh.get("data_nascimento"))

    # ===== normalized values =====
    cpf_prop_norm = _digits_only(cpf_prop_raw)
    cpf_cnh_norm = _digits_only(cpf_cnh_raw)

    nome_prop_norm = _norm_spaces_upper(nome_prop_raw)
    nome_cnh_norm = _norm_spaces_upper(nome_cnh_raw)

    dn_prop_norm = _norm_date(dn_prop_raw)
    dn_cnh_norm = _norm_date(dn_cnh_raw)

    fields = {
        "cpf": {
            "proposta": _explain_pair(cpf_prop_raw, cpf_prop_norm),
            "cnh": _explain_pair(cpf_cnh_raw, cpf_cnh_norm),
        },
        "nome": {
            "proposta": _explain_pair(nome_prop_raw, nome_prop_norm),
            "cnh": _explain_pair(nome_cnh_raw, nome_cnh_norm),
        },
        "data_nascimento": {
            "proposta": _explain_pair(dn_prop_raw, dn_prop_norm),
            "cnh": _explain_pair(dn_cnh_raw, dn_cnh_norm),
        },
    }

    sections = {"equal": [], "divergent": [], "missing": []}

    for field, payload in fields.items():
        p = payload["proposta"]
        c = payload["cnh"]

        p_raw = p.get("raw")
        c_raw = c.get("raw")
        p_norm = p.get("normalized")
        c_norm = c.get("normalized")

        if p_raw is None or c_raw is None:
            status = "missing"
            item = {
                "field": field,
                "status": status,
                "proposta": p,
                "cnh": c,
            }
            item["explain"] = _mk_explain(field, status, p, c)
            sections["missing"].append(item)
            continue

        if p_norm is None or c_norm is None:
            status = "not_comparable"
            item = {
                "field": field,
                "status": status,
                "proposta": p,
                "cnh": c,
            }
            item["explain"] = _mk_explain(field, status, p, c)
            sections["missing"].append(item)
            continue

        if p_norm == c_norm:
            status = "equal"
            item = {
                "field": field,
                "status": status,
                "proposta": p,
                "cnh": c,
            }
            item["explain"] = _mk_explain(field, status, p, c)
            sections["equal"].append(item)
        else:
            status = "different"
            item = {
                "field": field,
                "status": status,
                "proposta": p,
                "cnh": c,
            }
            item["explain"] = _mk_explain(field, status, p, c)
            sections["divergent"].append(item)

    summary = {
        "total_fields": len(fields),
        "equal": len(sections["equal"]),
        "divergent": len(sections["divergent"]),
        "missing": len(sections["missing"]),
    }

    report = {
        "case_id": case_id,
        "created_at": _utc_now_iso(),
        "validator": "proposta_vs_cnh",
        "summary": summary,
        "sections": sections,
        "inputs": {
            "proposta_found": bool(proposta_src),
            "cnh_found": bool(cnh_src),
            "proposta_read_error": proposta_read_error,
            "cnh_read_error": cnh_read_error,
        },
    }

    return report
