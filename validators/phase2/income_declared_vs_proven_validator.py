# validators/phase2/income_declared_vs_proven_validator.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC
from typing import Any, Dict, List, Optional, Tuple
import re


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _norm_money_br_to_float(v: Any) -> Optional[float]:
    """
    Aceita:
      - "3.700,00", "3700,00", "3700.00", "R$ 3.700,00"
      - int/float
    Retorna float ou None.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None

    s = v.strip()
    if not s or s.lower() == "null":
        return None

    s = re.sub(r"[Rr]\$|\s+", "", s)

    # BR: milhar '.' e decimal ','
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


def _safe_add(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


@dataclass(frozen=True)
class IncomeSourceItem:
    document: str
    strategy: str
    field: str
    path: Optional[str]
    raw: Any
    normalized: Optional[float]
    explain: str


def build_income_declared_vs_proven_report(
    *,
    case_id: str,
    proposta_data: Dict[str, Any],
    holerite_data: Optional[Dict[str, Any]] = None,
    folha_data: Optional[Dict[str, Any]] = None,
    extrato_data: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Phase 2:
    - NÃO bloqueia
    - NÃO aprova/reprova
    - apenas relata: total declarado (salário + outras rendas) vs total comprovado (holerite/folha/extrato)
    - extrato só entra se já houver campo apurado no payload (não inferimos lançamentos aqui)
    """
    _ = today  # reservado para evoluções (p.ex. janelas mensais)

    # -----------------------
    # Declarado (Proposta)
    # -----------------------
    salario_raw = proposta_data.get("salario")
    outras_raw = proposta_data.get("outras_rendas")

    salario = _norm_money_br_to_float(salario_raw)
    outras = _norm_money_br_to_float(outras_raw)

    declared_items = [
        {
            "label": "renda_principal",
            "path": "data.salario",
            "raw": salario_raw,
            "normalized": salario,
        },
        {
            "label": "outras_rendas",
            "path": "data.outras_rendas",
            "raw": outras_raw,
            "normalized": outras,
        },
    ]

    total_declared = _safe_add(salario, outras)

    # -----------------------
    # Comprovado (Docs)
    # -----------------------
    proven_sources: List[IncomeSourceItem] = []

    # Holerite
    if holerite_data is not None:
        raw = holerite_data.get("total_vencimentos")
        val = _norm_money_br_to_float(raw)
        if val is not None:
            proven_sources.append(
                IncomeSourceItem(
                    document="holerite",
                    strategy="salary",
                    field="total_vencimentos",
                    path="data.total_vencimentos",
                    raw=raw,
                    normalized=val,
                    explain="Renda comprovada via holerite (total de vencimentos).",
                )
            )
        else:
            proven_sources.append(
                IncomeSourceItem(
                    document="holerite",
                    strategy="salary",
                    field="total_vencimentos",
                    path="data.total_vencimentos",
                    raw=raw,
                    normalized=None,
                    explain="Holerite presente, mas total_vencimentos ausente ou não parseável.",
                )
            )

    # Folha (depende do seu parser; tentativas comuns)
    if folha_data is not None:
        for field_name in ("remuneracao", "salario", "renda"):
            raw = folha_data.get(field_name)
            val = _norm_money_br_to_float(raw)
            if val is not None:
                proven_sources.append(
                    IncomeSourceItem(
                        document="folha_pagamento",
                        strategy="salary",
                        field=field_name,
                        path=f"data.{field_name}",
                        raw=raw,
                        normalized=val,
                        explain="Renda comprovada via folha de pagamento.",
                    )
                )
                break
        else:
            proven_sources.append(
                IncomeSourceItem(
                    document="folha_pagamento",
                    strategy="salary",
                    field="remuneracao/salario/renda",
                    path=None,
                    raw=None,
                    normalized=None,
                    explain="Folha presente, mas nenhum campo de renda conhecido foi encontrado/parseado.",
                )
            )

    # Extrato: só entra se já houver campo apurado no payload
    if extrato_data is not None:
        candidates = (
            "renda_apurada",
            "renda_recorrente",
            "creditos_recorrentes_total",
            "creditos_validos_total",
        )
        picked: Optional[Tuple[str, Any, Optional[float]]] = None
        for k in candidates:
            raw = extrato_data.get(k)
            val = _norm_money_br_to_float(raw)
            if val is not None:
                picked = (k, raw, val)
                break

        if picked is not None:
            k, raw, val = picked
            proven_sources.append(
                IncomeSourceItem(
                    document="extrato_bancario",
                    strategy="bank_flow",
                    field=k,
                    path=f"data.{k}",
                    raw=raw,
                    normalized=val,
                    explain="Fluxo/renda apurada a partir do extrato (campo previamente calculado no pipeline).",
                )
            )
        else:
            proven_sources.append(
                IncomeSourceItem(
                    document="extrato_bancario",
                    strategy="bank_flow",
                    field="(apuração ausente)",
                    path=None,
                    raw=None,
                    normalized=None,
                    explain="Extrato presente, mas não existe no payload um campo de renda apurada. Nesta fase não inferimos renda a partir de lançamentos.",
                )
            )

    total_proven: Optional[float] = None
    for it in proven_sources:
        total_proven = _safe_add(total_proven, it.normalized)

    # -----------------------
    # Comparação (sem decisão)
    # -----------------------
    declared_present = total_declared is not None and total_declared > 0
    proven_present = total_proven is not None and total_proven > 0

    coverage_ratio: Optional[float] = None
    if not declared_present:
        status = "declared_missing"
    elif not proven_present:
        status = "proven_missing"
    else:
        if total_proven is None or total_declared is None:
            status = "unparseable"
        else:
            coverage_ratio = (total_proven / total_declared) if total_declared > 0 else None
            status = "compatible" if total_proven >= total_declared else "below_declared"

    explain = (
        f"Total declarado na proposta ({total_declared if total_declared is not None else 'N/A'}) "
        f"vs total comprovado ({total_proven if total_proven is not None else 'N/A'})."
    )

    report: Dict[str, Any] = {
        "validator": "income_declared_vs_proven",
        "version": "phase2.income.v2",
        "case_id": case_id,
        "generated_at": _now_utc_iso(),
        "summary": {
            "total_declared": total_declared,
            "total_proven": total_proven,
            "status": status,
            "coverage_ratio": coverage_ratio,
            "declared_present": declared_present,
            "proven_present": proven_present,
        },
        "sections": {
            "declared": {
                "items": declared_items,
                "total": total_declared,
            },
            "proven": {
                "sources": [
                    {
                        "document": s.document,
                        "strategy": s.strategy,
                        "field": s.field,
                        "path": s.path,
                        "raw": s.raw,
                        "normalized": s.normalized,
                        "explain": s.explain,
                    }
                    for s in proven_sources
                ],
                "total": total_proven,
            },
            "comparison": {
                "status": status,
                "explain": explain,
            },
        },
    }
    return report


__all__ = ["build_income_declared_vs_proven_report"]
