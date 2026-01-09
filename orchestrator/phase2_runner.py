from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import json


@dataclass
class Phase2RunResult:
    case_id: str
    proposta_json_path: Optional[Path]
    cnh_json_path: Optional[Path]
    report_path: Optional[Path]


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


def run_phase2_proposta_cnh(
    *,
    case_id: str,
    storage_root: Path = Path("./storage"),
    write_report: bool = True,
) -> Phase2RunResult:
    from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report

    phase1_dir = storage_root / "phase1" / case_id
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

    report_path = None
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
