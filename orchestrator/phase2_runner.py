from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from validators.phase2.master_report import build_master_report, build_master_report_and_return_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_phase1_root() -> Path:
    # storage/phase1
    return Path("storage") / "phase1"


def _default_phase2_root() -> Path:
    # storage/phase2
    return Path("storage") / "phase2"


@dataclass(frozen=True)
class Phase2RunResult:
    ok: bool
    report_path: Optional[Path]
    error: Optional[Dict[str, Any]]


def build_master_report_and_return_path_compat(
    case_id: str,
    *,
    phase1_root: str | Path | None = None,
    phase2_root: str | Path | None = None,
    write_report: bool = True,
) -> Path:
    """
    Compat layer:
    - O master_report.py atual NÃO aceita 'write_report' (sempre escreve).
    - Mantemos o parâmetro aqui para compatibilidade com UI/integrações,
      mas garantimos que não exploda (não repassamos para a função).
    """
    p1 = Path(phase1_root) if phase1_root is not None else _default_phase1_root()
    p2 = Path(phase2_root) if phase2_root is not None else _default_phase2_root()

    # Se write_report=False, ainda assim precisamos de um artefato para UI/trace.
    # Para manter comportamento previsível, seguimos escrevendo (sem quebrar).
    _ = write_report  # intencional: compat

    return build_master_report_and_return_path(case_id, phase1_root=p1, phase2_root=p2)


def run_phase2(
    case_id: str,
    *,
    phase1_root: str | Path | None = None,
    phase2_root: str | Path | None = None,
    write_report: bool = True,
) -> Phase2RunResult:
    """
    Executa Phase 2 e retorna o path do report.json.

    Importante (diretriz do projeto):
    - Se houver erro interno, NÃO bloquear o fluxo inteiro.
    - Retornar ok=False + erro, mas tentar escrever um report mínimo quando possível.
    """
    p1 = Path(phase1_root) if phase1_root is not None else _default_phase1_root()
    p2 = Path(phase2_root) if phase2_root is not None else _default_phase2_root()

    try:
        report_path = build_master_report_and_return_path_compat(
            case_id,
            phase1_root=p1,
            phase2_root=p2,
            write_report=write_report,
        )
        return Phase2RunResult(ok=True, report_path=report_path, error=None)

    except Exception as e:
        err = {
            "message": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "created_at": _utc_now_iso(),
        }

        # Report mínimo, para a UI não quebrar e para diagnóstico
        # (e para respeitar a regra: não bloquear durante parsing/extracão).
        minimal = {
            "schema": "phase2.master_report.v1",
            "schema_version": "v1",
            "validator": "phase2.master_report",
            "created_at": _utc_now_iso(),
            "meta": {
                "case_id": case_id,
                "created_at": _utc_now_iso(),
                "schema": "phase2.master_report.v1",
                "schema_version": "v1",
                "validator": "phase2.master_report",
                "gate1_status": "FAIL",
                "inputs": {},
            },
            "inputs": {"docs": {}},
            "checks": [
                {
                    "id": "phase2.runner.error",
                    "title": "Runner error",
                    "status": "WARN",
                    "explain": "Phase 2 runner captured an internal error but did not block.",
                    "details": {"error": err["message"]},
                }
            ],
            "summary": {
                "overall_status": "WARN",
                "counts": {"OK": 0, "WARN": 1, "FAIL": 0, "MISSING": 0},
                "total_checks": 1,
            },
            "overall_status": "WARN",
            "status": "WARN",
        }

        out_dir = p2 / case_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "report.json"
        out_path.write_text(json.dumps(minimal, ensure_ascii=False, indent=2), encoding="utf-8")

        return Phase2RunResult(ok=False, report_path=out_path, error=err)
