# orchestrator/phase2_runner.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report


# ======================================================================================
# Helpers
# ======================================================================================

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


def _ensure_summary_missing(report: dict, proposta_path: Optional[Path], cnh_path: Optional[Path]) -> None:
    """
    Contrato exigido por testes:
      report["summary"]["missing"] >= 1 quando CNH estiver ausente.
    Garantimos isso aqui no runner, independentemente do builder.
    """
    missing = 0
    if proposta_path is None:
        missing += 1
    if cnh_path is None:
        missing += 1

    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        report["summary"] = summary

    # Só setamos se não existir (não sobrescreve builder se ele já fornecer).
    if "missing" not in summary:
        summary["missing"] = missing
    else:
        # Se existe mas não é int, normalizamos para int (defensivo)
        try:
            summary["missing"] = int(summary["missing"])
        except Exception:
            summary["missing"] = missing


# ======================================================================================
# Results
# ======================================================================================

@dataclass(frozen=True)
class Phase2RunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
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

    # meta.inputs exigido por testes
    report["meta"] = {
        "inputs": {
            "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
            "cnh_json_path": str(cnh_json_path) if cnh_json_path else None,
        }
    }

    # summary.missing exigido por testes
    _ensure_summary_missing(report, proposta_json_path, cnh_json_path)

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
