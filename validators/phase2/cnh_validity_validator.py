# validators/phase2/cnh_validity_validator.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, UTC
from typing import Any, Dict, Optional

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class ValidityCheckResult:
    status: str  # "valid" | "expired" | "missing" | "unparseable"
    raw: Optional[str]
    normalized: Optional[str]  # YYYY-MM-DD when parseable
    days_to_expire: Optional[int]  # >=0 when valid, <0 when expired
    explain: str


_DATE_DDMMYYYY = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")
_DATE_YYYYMMDD = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def _parse_validade_to_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None

    m = _DATE_DDMMYYYY.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        try:
            return date(int(yyyy), int(mm), int(dd))
        except ValueError:
            return None

    m = _DATE_YYYYMMDD.match(s)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        try:
            return date(int(yyyy), int(mm), int(dd))
        except ValueError:
            return None

    return None


def _to_yyyy_mm_dd(d: date) -> str:
    return d.isoformat()


def build_cnh_validity_report(
    *,
    case_id: str,
    cnh_data: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> JsonDict:
    """
    Phase 2.A — Validade CNH × data atual
    - Não bloqueia fluxo
    - Não decide aprovado/reprovado
    - Report explicável, determinístico
    - Usa somente o payload persistido (cnh_data = doc["data"])
    """
    meta = meta or {}

    # "today" injetável para teste determinístico
    now = today or date.today()

    raw_validade = cnh_data.get("validade") if isinstance(cnh_data, dict) else None
    parsed = _parse_validade_to_date(raw_validade)

    if raw_validade is None or (isinstance(raw_validade, str) and not raw_validade.strip()):
        result = ValidityCheckResult(
            status="missing",
            raw=None if raw_validade is None else str(raw_validade),
            normalized=None,
            days_to_expire=None,
            explain="Campo 'validade' ausente ou vazio na CNH; não há base para checar expiração.",
        )
    elif parsed is None:
        result = ValidityCheckResult(
            status="unparseable",
            raw=str(raw_validade),
            normalized=None,
            days_to_expire=None,
            explain="Campo 'validade' presente na CNH, porém não foi possível interpretar o formato da data.",
        )
    else:
        delta_days = (parsed - now).days
        if delta_days < 0:
            result = ValidityCheckResult(
                status="expired",
                raw=str(raw_validade),
                normalized=_to_yyyy_mm_dd(parsed),
                days_to_expire=delta_days,
                explain=f"CNH vencida: validade {_to_yyyy_mm_dd(parsed)} é anterior à data atual {now.isoformat()} (diferença {delta_days} dias).",
            )
        else:
            result = ValidityCheckResult(
                status="valid",
                raw=str(raw_validade),
                normalized=_to_yyyy_mm_dd(parsed),
                days_to_expire=delta_days,
                explain=f"CNH válida: validade {_to_yyyy_mm_dd(parsed)} é igual/posterior à data atual {now.isoformat()} (faltam {delta_days} dias).",
            )

    check_item = {
        "check": "cnh_validity",
        "field": "validade",
        "status": result.status,
        "explain": result.explain,
        "today": now.isoformat(),
        "cnh": {
            "path": "data.validade",
            "strategy": "path",
            "raw": result.raw,
            "normalized": result.normalized,
        },
        "derived": {
            "days_to_expire": result.days_to_expire,
        },
    }

    summary = {
        "total_checks": 1,
        "valid": 1 if result.status == "valid" else 0,
        "expired": 1 if result.status == "expired" else 0,
        "missing": 1 if result.status == "missing" else 0,
        "unparseable": 1 if result.status == "unparseable" else 0,
    }

    return {
        "validator": "cnh_validity",
        "version": "phase2.cnh_validity.v1",
        "case_id": case_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "sections": {
            "checks": [check_item],
            "valid": [check_item] if result.status == "valid" else [],
            "expired": [check_item] if result.status == "expired" else [],
            "missing": [check_item] if result.status == "missing" else [],
            "unparseable": [check_item] if result.status == "unparseable" else [],
        },
        "meta": meta,
    }
