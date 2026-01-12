from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


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


def _pick_latest_json_in_dir(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return None
    # robusto: ordena por mtime e depois por nome (estável)
    files = sorted(
        [p for p in dir_path.glob("*.json") if p.is_file()],
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    return files[-1] if files else None


def _safe_read_json(path: Optional[Path]) -> Tuple[Optional[JsonDict], Optional[str]]:
    if path is None:
        return None, "missing_file"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def _extract_data(doc_json: Optional[JsonDict]) -> Optional[JsonDict]:
    """
    Phase 1 geralmente persiste envelope:
      { "document_type": "...", "data": {...}, "debug": {...}, ... }

    Alguns testes/fixtures podem persistir o payload direto.
    Este helper tolera os dois.
    """
    if not doc_json:
        return None
    data = doc_json.get("data")
    if isinstance(data, dict):
        return data
    return doc_json


def run_phase2_proposta_cnh(
    *,
    case_id: str,
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    """
    Lê Phase 1 em:
      storage_root/phase1/<case_id>/proposta_daycoval/*.json
      storage_root/phase1/<case_id>/cnh/*.json

    Escreve Phase 2 em:
      storage_root/phase2/<case_id>/reports/proposta_vs_cnh.json
    """
    from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report

    phase1_dir = storage_root / "phase1" / case_id
    proposta_dir = phase1_dir / "proposta_daycoval"
    cnh_dir = phase1_dir / "cnh"

    proposta_json_path = _pick_latest_json_in_dir(proposta_dir)
    cnh_json_path = _pick_latest_json_in_dir(cnh_dir)

    proposta_doc, _ = _safe_read_json(proposta_json_path)
    cnh_doc, _ = _safe_read_json(cnh_json_path)

    proposta_data = _extract_data(proposta_doc)
    cnh_data = _extract_data(cnh_doc)

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta_data,
        cnh_data=cnh_data,
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
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    """
    Lê Phase 1 em:
      storage_root/phase1/<case_id>/proposta_daycoval/*.json
      storage_root/phase1/<case_id>/holerite/*.json   (opcional)
      storage_root/phase1/<case_id>/extrato_bancario/*.json (opcional)

    Escreve Phase 2 em:
      storage_root/phase2/<case_id>/reports/income_declared_vs_proven.json
    """
    from validators.phase2.income_declared_vs_proven_validator import (
        build_income_declared_vs_proven_report,
    )

    phase1_dir = storage_root / "phase1" / case_id

    proposta_json_path = _pick_latest_json_in_dir(phase1_dir / "proposta_daycoval")
    holerite_json_path = _pick_latest_json_in_dir(phase1_dir / "holerite")
    extrato_json_path = _pick_latest_json_in_dir(phase1_dir / "extrato_bancario")

    proposta_doc, _ = _safe_read_json(proposta_json_path)
    holerite_doc, _ = _safe_read_json(holerite_json_path)
    extrato_doc, _ = _safe_read_json(extrato_json_path)

    proposta_data = _extract_data(proposta_doc)
    holerite_data = _extract_data(holerite_doc)
    extrato_data = _extract_data(extrato_doc)

    report: JsonDict
    if proposta_data is None:
        # Sem proposta não existe "declarado" para comparar; devolve report não-bloqueante e explicável.
        report = {
            "case_id": case_id,
            "validator": "income_declared_vs_proven",
            "created_at": None,
            "summary": {
                "status": "MISSING",
                "explain": "Sem proposta_daycoval no Phase 1 não há renda declarada para comparar.",
            },
            "inputs": {
                "proposta_daycoval": str(proposta_json_path) if proposta_json_path else None,
                "holerite": str(holerite_json_path) if holerite_json_path else None,
                "extrato_bancario": str(extrato_json_path) if extrato_json_path else None,
            },
        }
    else:
        report = build_income_declared_vs_proven_report(
            case_id=case_id,
            proposta_data=proposta_data,
            holerite_data=holerite_data,
            extrato_data=extrato_data,
        )

        # runner-level inputs (proveniência)
        report.setdefault("inputs", {})
        report["inputs"].update(
            {
                "proposta_daycoval": str(proposta_json_path) if proposta_json_path else None,
                "holerite": str(holerite_json_path) if holerite_json_path else None,
                "extrato_bancario": str(extrato_json_path) if extrato_json_path else None,
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
    storage_root: Path = Path("./storage"),
) -> Phase2MasterReportResult:
    """
    Integra o Master Report ao orquestrador.

    - Usa validators.phase2.master_report.build_master_report (entrypoint real do projeto)
    - Sempre persiste em: storage_root/phase2/<case_id>/report.json
    - É seguro com Phase 1 vazio (gera checks MISSING)
    """
    from validators.phase2.master_report import build_master_report

    phase1_root = str(storage_root / "phase1")
    phase2_root = str(storage_root / "phase2")

    build_master_report(case_id, phase1_root=phase1_root, phase2_root=phase2_root)

    report_path = storage_root / "phase2" / case_id / "report.json"
    return Phase2MasterReportResult(case_id=case_id, report_path=report_path)
