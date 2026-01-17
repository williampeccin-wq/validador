# validators/phase2/master_report.py

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# MUST match tests/test_phase2_master_report_meta_contract.py::SCHEMA_VERSION
SCHEMA_VERSION = "phase2.master_report@1"

# Gate1 contract (Phase 1 required docs)
GATE1_REQUIRED = ["proposta_daycoval", "cnh"]


def _utc_now_rfc3339() -> str:
    # timezone-aware UTC timestamp (avoid datetime.utcnow())
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_read_json(p: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def _sanitize_path_for_meta(p: Path) -> str:
    """
    Contract requirement: do not leak absolute paths in meta.
    Tests enforce: must NOT start with "/".
    """
    s = p.as_posix()
    while s.startswith("/"):
        s = s[1:]
    return s


def _list_phase1_presence(phase1_case_root: Path) -> Dict[str, Dict[str, Any]]:
    """
    Returns: presence[doc_type] = {present: bool, count: int, path: str}
    Metadata-only. No payload.
    """
    presence: Dict[str, Dict[str, Any]] = {}

    if not phase1_case_root.exists():
        return presence

    for doc_type_dir in sorted([p for p in phase1_case_root.iterdir() if p.is_dir()]):
        jsons = sorted(doc_type_dir.glob("*.json"))
        presence[doc_type_dir.name] = {
            "present": bool(jsons),
            "count": int(len(jsons)),
            "path": str(doc_type_dir),
        }

    return presence


def _gate1_status(presence: Dict[str, Dict[str, Any]]) -> str:
    for req in GATE1_REQUIRED:
        meta = presence.get(req) or {}
        if not bool(meta.get("present")):
            return "FAIL"
    return "PASS"


def _build_privacy_meta() -> Dict[str, Any]:
    """
    Contract: explicit privacy statement for the meta section.
    Keep it strictly structural (no free-text) to avoid forbidden substrings.
    """
    return {
        "contains_pii": False,
    }


def _build_meta(
    *,
    case_id: str,
    phase1_root: Path,
    phase2_root: Path,
    presence: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Contract: meta must be stable, UTC timezone-aware, metadata-only,
    and must not leak absolute paths.
    """
    inputs_docs: Dict[str, Dict[str, Any]] = {}
    for doc_type, meta in presence.items():
        inputs_docs[doc_type] = {
            "present": bool(meta.get("present")),
            "count": int(meta.get("count", 0)),
        }

    meta: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "phase2",
        "case_id": case_id,
        "generated_at": _utc_now_rfc3339(),
        "inputs": {
            "phase1": {
                "gate1": {
                    "required": list(GATE1_REQUIRED),
                    "status": _gate1_status(presence),
                },
                "docs": inputs_docs,
            }
        },
        "source_layout": {
            "phase1_root": _sanitize_path_for_meta(phase1_root),
            "phase2_root": _sanitize_path_for_meta(phase2_root),
        },
        "privacy": _build_privacy_meta(),
    }

    return meta


def build_master_report(*, case_id: str, phase1_root: Path, phase2_root: Path) -> Dict[str, Any]:
    """
    Returns canonical Phase2 report payload (dict).
    Must not block if Phase1 is empty/incomplete.

    IMPORTANT CONTRACT (aligned with tests):
      - phase1_root and phase2_root are *case roots*, not "root-of-cases".
      - i.e. caller passes: storage/phase1/<case_id> and storage/phase2/<case_id>
    """
    presence = _list_phase1_presence(phase1_root)

    payload: Dict[str, Any] = {
        "checks": [],
        "inputs": {},
        "summary": {},
        "overall_status": "OK",
        "status": "OK",
        "meta": _build_meta(
            case_id=case_id,
            phase1_root=phase1_root,
            phase2_root=phase2_root,
            presence=presence,
        ),
    }

    return payload
