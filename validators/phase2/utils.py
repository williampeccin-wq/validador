# validators/phase2/utils.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_latest_phase1_json(phase1_case_root: Path, doc_type: str) -> Optional[Dict[str, Any]]:
    """Carrega o JSON mais recente de um doc_type no storage Phase 1.

    Contrato (Phase 1): arquivos *.json com shape {"data": {...}, ...}.

    - Retorna dict completo do JSON (não apenas "data").
    - Retorna None se doc_type não existir ou não houver JSON.

    Observação: este helper existe para evitar duplicação de lógica entre validators.
    """
    d = phase1_case_root / doc_type
    if not d.exists() or not d.is_dir():
        return None

    jsons = sorted(d.glob("*.json"))
    if not jsons:
        return None

    p = jsons[-1]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None
    return raw
