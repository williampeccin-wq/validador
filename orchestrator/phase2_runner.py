from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from validators.phase2.income_declared_vs_proven_validator import (
    build_income_declared_vs_proven_report,
)
from validators.phase2.master_report import build_master_report
from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report


JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class Phase2RunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
    report_path: Optional[Path]


@dataclass(frozen=True)
class Phase2MasterReportResult:
    case_id: str
    report_path: Path


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_json(path: Path) -> Optional[JsonDict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pick_latest_json(dir_path: Path) -> Optional[Path]:
    """Pick latest JSON in directory using (mtime, name) ordering."""
    if not dir_path.exists() or not dir_path.is_dir():
        return None
    candidates = sorted(
        [p for p in dir_path.glob("*.json") if p.is_file()],
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    return candidates[-1] if candidates else None


def _extract_data(doc_json: Optional[JsonDict]) -> Optional[JsonDict]:
    """Tolerate Phase 1 envelopes and raw payloads.

    Phase 1 commonly persists:
      {"document_type": "...", "data": {...}, "debug": {...}, ...}

    But older fixtures/tests may persist the data directly.
    """
    if not doc_json:
        return None
    data = doc_json.get("data")
    if isinstance(data, dict):
        return data
    return doc_json


def _phase1_doc_paths(case_id: str, storage_root: Path) -> Tuple[Optional[Path], Optional[Path]]:
    phase1_case_dir = storage_root / "phase1" / case_id
    proposta_json_path = _pick_latest_json(phase1_case_dir / "proposta_daycoval")
    cnh_json_path = _pick_latest_json(phase1_case_dir / "cnh")
    return proposta_json_path, cnh_json_path


def run_phase2_proposta_cnh(
    *,
    case_id: str,
    storage_root: Union[str, Path] = Path("storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    """Run Phase 2 validator: Proposta ↔ CNH.

    Reads the latest Phase 1 JSONs under:
      <storage_root>/phase1/<case_id>/proposta_daycoval/*.json
      <storage_root>/phase1/<case_id>/cnh/*.json

    Writes report to:
      <storage_root>/phase2/<case_id>/reports/proposta_vs_cnh.json
    """
    storage_root = Path(storage_root)

    proposta_json_path, cnh_json_path = _phase1_doc_paths(case_id, storage_root)

    proposta_raw = _safe_read_json(proposta_json_path) if proposta_json_path else None
    cnh_raw = _safe_read_json(cnh_json_path) if cnh_json_path else None

    proposta_data = _extract_data(proposta_raw)
    cnh_data = _extract_data(cnh_raw)

    report: JsonDict = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta_data,
        cnh_data=cnh_data,
    )

    # Runner-level meta (paths). This keeps provenance even if validator contract evolves.
    report.setdefault("meta", {})
    report["meta"].setdefault("inputs", {})
    report["meta"]["inputs"].update(
        {
            "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
            "cnh_json_path": str(cnh_json_path) if cnh_json_path else None,
        }
    )
    report["meta"].setdefault("runner", {})
    report["meta"]["runner"].update(
        {
            "storage_root": str(storage_root),
            "phase": "phase2",
            "runner": "run_phase2_proposta_cnh",
            "generated_at": _utc_iso(),
        }
    )

    report_path: Optional[Path] = None
    if write_report:
        report_dir = storage_root / "phase2" / case_id / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "proposta_vs_cnh.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return Phase2RunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        cnh_json_path=cnh_json_path,
        report_path=report_path,
    )


def run_phase2_income_declared_vs_proven(
    *,
    case_id: str,
    storage_root: Union[str, Path] = Path("storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    """Run Phase 2 validator: income declared vs proven (Proposta ↔ opcionais).

    Today, this runner only wires the Proposta (declared) because Phase 1 optionals
    (holerite/extrato) may not exist yet for a given case.
    """
    storage_root = Path(storage_root)
    phase1_case_dir = storage_root / "phase1" / case_id

    proposta_json_path = _pick_latest_json(phase1_case_dir / "proposta_daycoval")
    proposta_raw = _safe_read_json(proposta_json_path) if proposta_json_path else None
    proposta_data = _extract_data(proposta_raw)

    report: JsonDict
    if not proposta_data:
        # Minimal, non-blocking report when Proposta is missing.
        report = {
            "case_id": case_id,
            "validator": "income_declared_vs_proven",
            "created_at": _utc_iso(),
            "summary": {"missing": 1, "note": "missing proposta_daycoval"},
            "sections": [
                {
                    "id": "minimum_inputs",
                    "title": "Inputs mínimos",
                    "status": "MISSING",
                    "expected": "proposta_daycoval",
                    "found": {"proposta_daycoval": False},
                }
            ],
        }
    else:
        report = build_income_declared_vs_proven_report(
            case_id=case_id,
            proposta_data=proposta_data,
            holerite_data=None,
            extrato_data=None,
        )

    report.setdefault("meta", {})
    report["meta"].setdefault("inputs", {})
    report["meta"]["inputs"].update(
        {
            "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
            "phase1_case_dir": str(phase1_case_dir),
        }
    )
    report["meta"].setdefault("runner", {})
    report["meta"]["runner"].update(
        {
            "storage_root": str(storage_root),
            "phase": "phase2",
            "runner": "run_phase2_income_declared_vs_proven",
            "generated_at": _utc_iso(),
        }
    )

    report_path: Optional[Path] = None
    if write_report:
        report_dir = storage_root / "phase2" / case_id / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "income_declared_vs_proven.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return Phase2RunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        cnh_json_path=None,
        report_path=report_path,
    )


def run_phase2_master_report(
    *,
    case_id: str,
    storage_root: Union[str, Path] = Path("storage"),
) -> Phase2MasterReportResult:
    """Build and persist the Phase 2 master report.

    Calls validators.phase2.master_report.build_master_report(case_id, ...), which:
      - loads latest Phase 1 inputs (if present)
      - computes checks + summary
      - persists to: <phase2_root>/<case_id>/report.json

    Safe even when Phase 1 storage is empty.
    """
    storage_root = Path(storage_root)
    phase1_root = str(storage_root / "phase1")
    phase2_root = str(storage_root / "phase2")

    _ = build_master_report(case_id, phase1_root=phase1_root, phase2_root=phase2_root)

    report_path = Path(phase2_root) / case_id / "report.json"
    return Phase2MasterReportResult(case_id=case_id, report_path=report_path)
