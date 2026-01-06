# orchestrator/phase2_runner.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report
from validators.phase2.income_declared_vs_proven_validator import (
    build_income_declared_vs_proven_report,
)


# =============================================================================
# Types
# =============================================================================

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class Phase2RunResult:
    """
    Resultado estável do runner Proposta↔CNH (não altere o contrato sem atualizar testes).
    """
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
    report_path: Optional[Path]
    report: JsonDict


@dataclass(frozen=True)
class Phase2IncomeRunResult:
    """
    Resultado do runner de renda declarada vs comprovada.
    """
    case_id: str
    proposta_json_path: Optional[Path]
    holerite_json_path: Optional[Path]
    folha_json_path: Optional[Path]
    extrato_json_path: Optional[Path]
    report_path: Optional[Path]
    report: JsonDict


# =============================================================================
# Helpers
# =============================================================================

def _load_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_latest_json_in_dir(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return None
    files = sorted(dir_path.glob("*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _safe_read_json(path: Optional[Path]) -> Tuple[JsonDict, Optional[str]]:
    if path is None:
        return {}, "missing_file"
    try:
        return _load_json(path), None
    except Exception as e:
        return {}, f"read_error: {type(e).__name__}: {e}"


def _get_data_dict(doc_json: JsonDict) -> JsonDict:
    data = doc_json.get("data", {})
    return data if isinstance(data, dict) else {}


# =============================================================================
# Public API
# =============================================================================

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

    proposta_data = _get_data_dict(proposta_doc)
    cnh_data = cnh_doc.get("data", {})  # CNH pode ser dict ou list dependendo do estágio

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_payload=proposta_doc,
        cnh_payload=cnh_doc,
        proposta_read_error=proposta_err,
        cnh_read_error=cnh_err,
    )

    report_path: Optional[Path] = None
    if write_report:
        report_path = storage_root / "phase2" / case_id / "reports" / "proposta_vs_cnh.json"
        _write_json(report_path, report)

    return Phase2RunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        cnh_json_path=cnh_json_path,
        report_path=report_path,
        report=report,
    )


def run_phase2_income_declared_vs_proven(
    *,
    case_id: str,
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2IncomeRunResult:
    """
    Lê SOMENTE dados persistidos na Phase 1 e gera relatório explicável.
    - Não bloqueia
    - Não aprova/reprova
    """
    phase1_dir = storage_root / "phase1" / case_id

    proposta_json_path = _pick_latest_json_in_dir(phase1_dir / "proposta_daycoval")
    holerite_json_path = _pick_latest_json_in_dir(phase1_dir / "holerite")
    folha_json_path = _pick_latest_json_in_dir(phase1_dir / "folha_pagamento")
    extrato_json_path = _pick_latest_json_in_dir(phase1_dir / "extrato_bancario")

    proposta_doc, _ = _safe_read_json(proposta_json_path)
    holerite_doc, _ = _safe_read_json(holerite_json_path)
    folha_doc, _ = _safe_read_json(folha_json_path)
    extrato_doc, _ = _safe_read_json(extrato_json_path)

    proposta_data = _get_data_dict(proposta_doc)
    holerite_data = _get_data_dict(holerite_doc) if holerite_json_path else None
    folha_data = _get_data_dict(folha_doc) if folha_json_path else None
    extrato_data = _get_data_dict(extrato_doc) if extrato_json_path else None

    report = build_income_declared_vs_proven_report(
        case_id=case_id,
        proposta_data=proposta_data,
        holerite_data=holerite_data,
        folha_data=folha_data,
        extrato_data=extrato_data,
    )

    # anexa meta de caminhos (útil para auditoria)
    report.setdefault("meta", {})
    report["meta"]["inputs"] = {
        "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
        "holerite_json_path": str(holerite_json_path) if holerite_json_path else None,
        "folha_json_path": str(folha_json_path) if folha_json_path else None,
        "extrato_json_path": str(extrato_json_path) if extrato_json_path else None,
    }

    report_path: Optional[Path] = None
    if write_report:
        report_path = storage_root / "phase2" / case_id / "reports" / "income_declared_vs_proven.json"
        _write_json(report_path, report)

    return Phase2IncomeRunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        holerite_json_path=holerite_json_path,
        folha_json_path=folha_json_path,
        extrato_json_path=extrato_json_path,
        report_path=report_path,
        report=report,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m orchestrator.phase2_runner <case_id> [proposta_cnh|income]")
        raise SystemExit(2)

    cid = sys.argv[1].strip()
    mode = sys.argv[2].strip() if len(sys.argv) >= 3 else "proposta_cnh"

    if mode == "income":
        result = run_phase2_income_declared_vs_proven(case_id=cid, storage_root=Path("./storage"), write_report=True)
        print("case_id:", result.case_id)
        print("proposta_json_path:", result.proposta_json_path)
        print("holerite_json_path:", result.holerite_json_path)
        print("folha_json_path:", result.folha_json_path)
        print("extrato_json_path:", result.extrato_json_path)
        print("report_path:", result.report_path)
        print("summary:", result.report.get("summary"))
    else:
        result = run_phase2_proposta_cnh(case_id=cid, storage_root=Path("./storage"), write_report=True)
        print("case_id:", result.case_id)
        print("proposta_json_path:", result.proposta_json_path)
        print("cnh_json_path:", result.cnh_json_path)
        print("report_path:", result.report_path)
        print("summary:", result.report.get("summary"))
