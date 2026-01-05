from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Dict, Any

from parsers.cnh import analyze_cnh
from parsers.residencia import analyze_residencia
from parsers.holerite import analyze_holerite
from parsers.extrato_bancario import analyze_extrato_bancario
from parsers.crlv_e import analyze_crlv_e
from parsers.atpv import analyze_atpv
from parsers.detran_sc import analyze_detran_sc


PARSERS = {
    "cnh": analyze_cnh,
    "residencia": analyze_residencia,
    "holerite": analyze_holerite,
    "extrato": analyze_extrato_bancario,
    "crlv_e": analyze_crlv_e,
    "atpv": analyze_atpv,
    "detran_sc": analyze_detran_sc,
}


def collect_document(
    file_path: str,
    *,
    document_type: str,
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if document_type not in PARSERS:
        raise ValueError(f"Tipo de documento não suportado: {document_type}")

    parser = PARSERS[document_type]
    context = context or {}

    # Execução do parser
    parsed = parser(file_path, **context)

    document_id = str(uuid.uuid4())
    parser_version = getattr(parser, "__version__", "unknown")

    output = {
        "document_id": document_id,
        "document_type": document_type,
        "parser_version": parser_version,
        "file_hash": _hash_file(file_path),
        "data": parsed,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    _persist_raw_output(output)
    return output


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _persist_raw_output(payload: Dict[str, Any]) -> None:
    """
    Persistência bruta Fase 1.
    Pode ser arquivo, banco ou storage depois.
    """
    out_dir = "storage/phase1"
    out_path = f"{out_dir}/{payload['document_id']}.json"

    import os
    os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
