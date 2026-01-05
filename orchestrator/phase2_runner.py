# orchestrator/phase2_runner.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report
from validators.phase2.cnh_validity_validator import build_cnh_validity_report

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class Phase2RunResult:
    case_id: str
    report_path: Path
    report: JsonDict

    # 🔒 CONTRATO PÚBLICO (mantido)
    proposta_json_path: Optional[str]
    cnh_json_path: Optional[str]

    # extra (novo, não quebra testes)
    inputs: Dict[str, Optional[str]]


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_json_in_dir(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return None
    files = sorted(dir_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _load_latest_phase1_doc(
    *,
    storage_root: Path,
    case_id: str,
    document_type: str,
) -> Optional[JsonDict]:
    doc_dir = storage_root / "phase1" / case_id / document_type
    latest = _latest_json_in_dir(doc_dir)
    if latest is None:
        return None
    return _read_json(latest)


# =============================================================================
# Phase 2 — Proposta ↔ CNH
# =============================================================================

def run_phase2_proposta_cnh(
    *,
    case_id: str,
    storage_root: Path = Path("storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    proposta_doc = _load_latest_phase1_doc(
        storage_root=storage_root,
        case_id=case_id,
        document_type="proposta_daycoval",
    )
    cnh_doc = _load_latest_phase1_doc(
        storage_root=storage_root,
        case_id=case_id,
        document_type="cnh",
    )

    proposta_json_path: Optional[str] = None
    cnh_json_path: Optional[str] = None

    proposta_data: Dict[str, Any] = {}
    cnh_data: Dict[str, Any] = {}

    if proposta_doc is not None:
        proposta_json_path = str(
            (storage_root / "phase1" / case_id / "proposta_daycoval").resolve()
        )
        proposta_data = proposta_doc.get("data") or {}

    if cnh_doc is not None:
        cnh_json_path = str(
            (storage_root / "phase1" / case_id / "cnh").resolve()
        )
        cnh_data = cnh_doc.get("data") or {}

    meta = {
        "inputs": {
            "proposta_json_path": proposta_json_path,
            "cnh_json_path": cnh_json_path,
        }
    }

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta_data if isinstance(proposta_data, dict) else {},
        cnh_data=cnh_data if isinstance(cnh_data, dict) else {},
        meta=meta,
    )

    report_path = storage_root / "phase2" / case_id / "reports" / "proposta_vs_cnh.json"
    if write_report:
        _write_json(report_path, report)

    return Phase2RunResult(
        case_id=case_id,
        report_path=report_path,
        report=report,
        proposta_json_path=proposta_json_path,
        cnh_json_path=cnh_json_path,
        inputs=meta["inputs"],
    )


# =============================================================================
# Phase 2.A — CNH validity
# =============================================================================

def run_phase2_cnh_validity(
    *,
    case_id: str,
    storage_root: Path = Path("storage"),
    write_report: bool = True,
    today: Optional[date] = None,
) -> Phase2RunResult:
    cnh_doc = _load_latest_phase1_doc(
        storage_root=storage_root,
        case_id=case_id,
        document_type="cnh",
    )

    cnh_json_path: Optional[str] = None
    cnh_data: Dict[str, Any] = {}

    if cnh_doc is not None:
        cnh_json_path = str(
            (storage_root / "phase1" / case_id / "cnh").resolve()
        )
        data = cnh_doc.get("data") or {}
        cnh_data = data if isinstance(data, dict) else {}

    meta = {
        "inputs": {
            "cnh_json_path": cnh_json_path,
        }
    }

    report = build_cnh_validity_report(
        case_id=case_id,
        cnh_data=cnh_data,
        meta=meta,
        today=today,
    )

    report_path = storage_root / "phase2" / case_id / "reports" / "cnh_validity.json"
    if write_report:
        _write_json(report_path, report)

    return Phase2RunResult(
        case_id=case_id,
        report_path=report_path,
        report=report,
        proposta_json_path=None,
        cnh_json_path=cnh_json_path,
        inputs=meta["inputs"],
    )
