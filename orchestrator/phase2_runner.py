# orchestrator/phase2_runner.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Any


# ======================================================================================
# Helpers
# ======================================================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_latest_json_in_dir(d: Path) -> Optional[Path]:
    if not d.exists():
        return None
    candidates = [p for p in d.glob("*.json") if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _safe_read_json(p: Optional[Path]) -> Tuple[dict, Optional[str]]:
    if p is None or not p.exists():
        return {}, "missing_file"
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except json.JSONDecodeError:
        return {}, "invalid_json"
    except Exception:
        return {}, "read_error"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_summary_dict(report: dict) -> dict:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        report["summary"] = summary
    return summary


def _ensure_summary_missing(report: dict, missing_count: int) -> None:
    summary = _ensure_summary_dict(report)
    if "missing" not in summary:
        summary["missing"] = int(missing_count)
    else:
        try:
            summary["missing"] = int(summary["missing"])
        except Exception:
            summary["missing"] = int(missing_count)


def _coerce_money_to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = val if isinstance(val, str) else str(val)
    s = s.strip()
    if not s:
        return None

    s = re.sub(r"[^\d,.\-]", "", s)

    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _get_data_dict(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    if "data" in doc and isinstance(doc.get("data"), dict):
        return doc.get("data") or {}
    return doc


def _first_present_money(d: dict, keys: list[str]) -> Optional[float]:
    for k in keys:
        if k in d:
            f = _coerce_money_to_float(d.get(k))
            if f is not None:
                return f
    return None


# ======================================================================================
# Results
# ======================================================================================

@dataclass(frozen=True)
class Phase2RunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
    report_path: Optional[Path]


@dataclass(frozen=True)
class Phase2IncomeRunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    renda_json_path: Optional[Path]
    renda_document_type: Optional[str]
    report_path: Optional[Path]


# ======================================================================================
# Runner: Proposta vs CNH
# ======================================================================================

def run_phase2_proposta_cnh(
    *,
    case_id: str,
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    # Lazy import (evita travar outros testes/runners por custo de import)
    from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report

    phase1_dir = storage_root / "phase1" / case_id
    proposta_dir = phase1_dir / "proposta_daycoval"
    cnh_dir = phase1_dir / "cnh"

    proposta_json_path = _pick_latest_json_in_dir(proposta_dir)
    cnh_json_path = _pick_latest_json_in_dir(cnh_dir)

    proposta_doc, proposta_err = _safe_read_json(proposta_json_path)
    cnh_doc, cnh_err = _safe_read_json(cnh_json_path)

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_payload=proposta_doc,
        cnh_payload=cnh_doc,
        proposta_read_error=proposta_err,
        cnh_read_error=cnh_err,
    )

    report["meta"] = {
        "inputs": {
            "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
            "cnh_json_path": str(cnh_json_path) if cnh_json_path else None,
        }
    }

    missing_count = 0
    if proposta_json_path is None:
        missing_count += 1
    if cnh_json_path is None:
        missing_count += 1
    _ensure_summary_missing(report, missing_count)

    report_path: Optional[Path] = None
    if write_report:
        report_path = storage_root / "phase2" / case_id / "reports" / "proposta_vs_cnh.json"
        _write_json(report_path, report)

    return Phase2RunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        cnh_json_path=cnh_json_path,
        report_path=report_path,
    )


# ======================================================================================
# Runner: Income declared vs proven
# ======================================================================================

def run_phase2_income_declared_vs_proven(
    *,
    case_id: str,
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2IncomeRunResult:
    phase1_dir = storage_root / "phase1" / case_id

    proposta_json_path = _pick_latest_json_in_dir(phase1_dir / "proposta_daycoval")
    holerite_path = _pick_latest_json_in_dir(phase1_dir / "holerite")
    folha_path = _pick_latest_json_in_dir(phase1_dir / "folha_pagamento")

    renda_json_path: Optional[Path] = None
    renda_document_type: Optional[str] = None
    if holerite_path is not None:
        renda_json_path = holerite_path
        renda_document_type = "holerite"
    elif folha_path is not None:
        renda_json_path = folha_path
        renda_document_type = "folha_pagamento"

    proposta_doc, proposta_err = _safe_read_json(proposta_json_path)
    renda_doc, renda_err = _safe_read_json(renda_json_path)

    proposta_data = _get_data_dict(proposta_doc)
    renda_data = _get_data_dict(renda_doc)

    declared_salario = _first_present_money(
        proposta_data,
        ["salario", "renda", "renda_mensal", "renda_bruta", "renda_declarada"],
    )
    declared_outras = _first_present_money(
        proposta_data,
        ["outras_rendas", "outra_renda", "renda_extra", "renda_complementar"],
    )

    declared_total: Optional[float] = None
    if declared_salario is not None or declared_outras is not None:
        declared_total = float((declared_salario or 0.0) + (declared_outras or 0.0))

    proven_total = _first_present_money(
        renda_data,
        [
            "total_vencimentos",
            "total_proventos",
            "salario",
            "salario_base",
            "liquido",
            "valor_liquido",
            "total_liquido",
        ],
    )

    delta: Optional[float] = None
    if declared_total is not None and proven_total is not None:
        delta = float(proven_total - declared_total)

    notes: list[str] = []
    if proposta_json_path is None:
        notes.append("Proposta ausente: não foi possível ler renda declarada.")
    if renda_json_path is None:
        notes.append("Comprovante de renda ausente (holerite/folha): não foi possível ler renda comprovada.")
    if proposta_err:
        notes.append(f"Erro ao ler proposta: {proposta_err}")
    if renda_err and renda_json_path is not None:
        notes.append(f"Erro ao ler comprovante de renda: {renda_err}")

    declared_present = proposta_json_path is not None
    proven_present = renda_json_path is not None
    proven_missing = not proven_present

    if not declared_present:
        status = "declared_missing"
    elif proven_missing:
        status = "proven_missing"
    else:
        status = "ok"

    report: dict = {
        "case_id": case_id,
        "created_at": _utc_now_iso(),
        "validator": "income_declared_vs_proven",
        "summary": {
            "declared_present": declared_present,
            "proven_present": proven_present,
            "proven_missing": proven_missing,
            "status": status,
        },
        "meta": {
            "inputs": {
                "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
                "renda_json_path": str(renda_json_path) if renda_json_path else None,
                "renda_document_type": renda_document_type,
            }
        },
        "declared": {
            "salario": declared_salario,
            "outras_rendas": declared_outras,
            "total": declared_total,
        },
        "proven": {
            "total": proven_total,
            "document_type": renda_document_type,
        },
        "delta": delta,
        "notes": notes,
    }

    missing_count = 0
    if proposta_json_path is None:
        missing_count += 1
    if renda_json_path is None:
        missing_count += 1
    _ensure_summary_missing(report, missing_count)

    report_path: Optional[Path] = None
    if write_report:
        report_path = storage_root / "phase2" / case_id / "reports" / "income_declared_vs_proven.json"
        _write_json(report_path, report)

    return Phase2IncomeRunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        renda_json_path=renda_json_path,
        renda_document_type=renda_document_type,
        report_path=report_path,
    )
