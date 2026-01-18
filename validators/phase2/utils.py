# validators/phase2/utils.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


def only_digits(value: Any) -> str:
    """Retorna apenas dígitos (0-9) de um valor arbitrário."""
    s = "" if value is None else str(value)
    return re.sub(r"\D+", "", s)


def normalize_doc_id(value: Any) -> str:
    """Normaliza CPF/CNPJ para comparação robusta.

    - Remove máscara e quaisquer caracteres não numéricos
    - Retorna somente se o tamanho for 11 (CPF) ou 14 (CNPJ)
    - Caso contrário, retorna string vazia ("")
    """
    d = only_digits(value)
    if len(d) in (11, 14):
        return d
    return ""


def load_latest_phase1_json(phase1_case_root: Path, doc_type: str) -> Optional[Dict[str, Any]]:
    """Carrega o JSON mais recente de um doc_type no storage Phase 1.

    Contrato (Phase 1): arquivos *.json com shape {"data": {...}, ...}.

    - Retorna dict completo do JSON (não apenas "data").
    - Retorna None se doc_type não existir ou não houver JSON.
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
