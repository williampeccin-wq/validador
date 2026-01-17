from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import json


@dataclass
class Phase2RunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
    report_path: Optional[Path]
    master_report_path: Optional[Path] = None


def _pick_latest_json_in_dir(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists():
        return None
    files = sorted(dir_path.glob("*.json"))
    return files[-1] if files else None


def _safe_read_json(path: Optional[Path]) -> Tuple[Optional[dict], Optional[str]]:
    if path is None:
        return None, "missing_file"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def run_phase2(
    case_id: str,
    *,
    phase1_root: str = "storage/phase1",
    phase2_root: str = "storage/phase2",
    write_report: bool = True,
) -> Phase2RunResult:
    """
    Phase 2 runner (canônico por contrato).

    Contrato:
      - Não deve bloquear (não levantar) por ausência de documentos.
      - Deve escrever: <phase2_root>/<case_id>/report.json
      - Report segue o schema/inputs/status/overall_status definidos no master_report.

    Observação:
      - O master_report atual salva automaticamente o report ao construir.
        Mantemos `write_report` por simetria de API, mas a implementação do master_report
        pode escrever mesmo quando `write_report=False`.
    """
    from validators.phase2.master_report import build_master_report_and_return_path

    # Para compatibilidade/telemetria: tentamos localizar os inputs "principais"
    # apenas para preencher Phase2RunResult (não é obrigatório para o contrato).
    phase1_case_dir = Path(phase1_root) / case_id
    proposta_json_path = _pick_latest_json_in_dir(phase1_case_dir / "proposta_daycoval")
    cnh_json_path = _pick_latest_json_in_dir(phase1_case_dir / "cnh")

    master_report_path: Optional[Path] = None
    if write_report:
        p = build_master_report_and_return_path(
            case_id,
            phase1_root=phase1_root,
            phase2_root=phase2_root,
        )
        master_report_path = Path(p)

    return Phase2RunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        cnh_json_path=cnh_json_path,
        report_path=master_report_path,
        master_report_path=master_report_path,
    )


def run_phase2_proposta_cnh(
    case_id: Optional[str] = None,
    *,
    storage_root: Path = Path("./storage"),
    phase1_root: Optional[str] = None,
    phase2_root: Optional[str] = None,
    write_report: bool = True,
) -> Phase2RunResult:
    """
    Runner legado específico (proposta vs CNH).

    Mantém compatibilidade:
      - Continua escrevendo o report específico em:
          <storage_root>/phase2/<case_id>/reports/proposta_vs_cnh.json

    E, adicionalmente (para satisfazer contratos recentes):
      - Executa o runner canônico `run_phase2(...)` para escrever:
          <phase2_root>/<case_id>/report.json
    """
    if not case_id:
        raise TypeError("run_phase2_proposta_cnh requires 'case_id' (positional or keyword).")

    # Normaliza roots:
    # - Se phase1_root/phase2_root não forem passados, derivamos de storage_root (comportamento atual).
    eff_phase1_root = phase1_root or str(storage_root / "phase1")
    eff_phase2_root = phase2_root or str(storage_root / "phase2")

    from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report

    phase1_dir = Path(eff_phase1_root) / case_id
    proposta_dir = phase1_dir / "proposta_daycoval"
    cnh_dir = phase1_dir / "cnh"

    proposta_json_path = _pick_latest_json_in_dir(proposta_dir)
    cnh_json_path = _pick_latest_json_in_dir(cnh_dir)

    proposta_doc, _ = _safe_read_json(proposta_json_path)
    cnh_doc, _ = _safe_read_json(cnh_json_path)

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta_doc,
        cnh_data=cnh_doc,
    )

    legacy_report_path: Optional[Path] = None
    if write_report:
        report_dir = Path(eff_phase2_root) / case_id / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        legacy_report_path = report_dir / "proposta_vs_cnh.json"
        legacy_report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # Runner canônico: escreve <phase2_root>/<case_id>/report.json (master report)
    canonical = run_phase2(
        case_id,
        phase1_root=eff_phase1_root,
        phase2_root=eff_phase2_root,
        write_report=write_report,
    )

    return Phase2RunResult(
        case_id=case_id,
        proposta_json_path=proposta_json_path,
        cnh_json_path=cnh_json_path,
        report_path=legacy_report_path,
        master_report_path=canonical.master_report_path,
    )
