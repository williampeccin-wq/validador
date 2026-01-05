from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report


# =============================================================================
# Types
# =============================================================================

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class Phase2RunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
    report_path: Optional[Path]
    report: JsonDict


# =============================================================================
# Helpers
# =============================================================================

def _load_json(path: Path) -> JsonDict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)


def _pick_latest_json_in_dir(dir_path: Path) -> Optional[Path]:
    """
    Retorna o arquivo .json mais recente (por mtime) dentro do diretório.
    Se não existir, retorna None.
    """
    if not dir_path.exists() or not dir_path.is_dir():
        return None

    candidates = [p for p in dir_path.glob("*.json") if p.is_file()]
    if not candidates:
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _safe_read_json(path: Optional[Path]) -> Tuple[JsonDict, Optional[str]]:
    """
    Nunca levanta exceção para o caller.
    Retorna (data, error_str).
    """
    if path is None:
        return {}, "missing_input_path"

    try:
        return _load_json(path), None
    except Exception as e:
        return {}, f"read_error: {type(e).__name__}: {e}"


# =============================================================================
# Public API
# =============================================================================

def run_phase2_proposta_cnh(
    *,
    case_id: str,
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    """
    Fase 2 (início): validação Proposta ↔ CNH gerando somente relatório explicável.
    Regras:
      - NÃO bloqueia fluxo (não levanta por divergência ou ausência)
      - NÃO decide aprovado/reprovado
      - Usa SOMENTE JSONs persistidos na Fase 1
    """
    phase1_case_dir = storage_root / "phase1" / case_id

    proposta_dir = phase1_case_dir / "proposta_daycoval"
    cnh_dir = phase1_case_dir / "cnh"

    proposta_json_path = _pick_latest_json_in_dir(proposta_dir)
    cnh_json_path = _pick_latest_json_in_dir(cnh_dir)

    proposta_data, proposta_err = _safe_read_json(proposta_json_path)
    cnh_data, cnh_err = _safe_read_json(cnh_json_path)

    meta: JsonDict = {
        "inputs": {
            "phase1_case_dir": str(phase1_case_dir),
            "proposta_json_path": str(proposta_json_path) if proposta_json_path else None,
            "cnh_json_path": str(cnh_json_path) if cnh_json_path else None,
        },
        "input_errors": {
            "proposta": proposta_err,
            "cnh": cnh_err,
        },
    }

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta_data,
        cnh_data=cnh_data,
        meta=meta,
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


if __name__ == "__main__":
    # Execução manual (exemplo):
    #   python -m orchestrator.phase2_runner 08b5395b-6eb3-4e37-90db-19c310b1107e
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m orchestrator.phase2_runner <case_id>")
        raise SystemExit(2)

    cid = sys.argv[1].strip()
    result = run_phase2_proposta_cnh(case_id=cid, storage_root=Path("./storage"), write_report=True)

    print("case_id:", result.case_id)
    print("proposta_json_path:", result.proposta_json_path)
    print("cnh_json_path:", result.cnh_json_path)
    print("report_path:", result.report_path)
    print("summary:", result.report.get("summary"))
