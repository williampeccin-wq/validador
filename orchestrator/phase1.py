# orchestrator/phase1.py
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, Literal, Optional, Set, Tuple

# Parsers reais do projeto
from parsers.proposta_daycoval import analyze_proposta_daycoval
from parsers.cnh import analyze_cnh

# OCR / extração de texto (PDF/imagem)
from core.ocr import extract_text_any


DocumentType = Literal[
    "proposta_daycoval",
    "cnh",
]

# Pacote mínimo — Gate 1
PACKAGES: Dict[str, Set[str]] = {
    "gate1_proposta_cnh": {"proposta_daycoval", "cnh"},
}


@dataclass(frozen=True)
class CaseStatus:
    case_id: str
    package: str
    present: Set[str]
    missing: Set[str]
    is_complete: bool


# =========================
# CONFIG EXTRAÇÃO DE TEXTO
# =========================

def _text_extract_config(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Config consolidada (context > env > default).
    """
    return {
        "tesseract_cmd": context.get("tesseract_cmd") or os.getenv("TESSERACT_CMD") or "tesseract",
        "poppler_path": context.get("poppler_path") or os.getenv("POPPLER_PATH") or "",
        "min_text_len_threshold": int(context.get("min_text_len_threshold") or os.getenv("MIN_TEXT_LEN_THRESHOLD") or 800),
        "ocr_dpi": int(context.get("ocr_dpi") or os.getenv("OCR_DPI") or 350),
    }


def _read_file_bytes(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


def _extract_text_best_effort(file_path: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Extrai texto de PDF/imagem com fallback para OCR quando texto nativo é insuficiente.
    Não bloqueia: em caso de erro, retorna texto vazio e debug com erro.
    """
    cfg = _text_extract_config(context)
    dbg: Dict[str, Any] = {
        "file_path": file_path,
        "filename": os.path.basename(file_path),
        "config": {
            "min_text_len_threshold": cfg["min_text_len_threshold"],
            "ocr_dpi": cfg["ocr_dpi"],
            "poppler_path": cfg["poppler_path"],
            "tesseract_cmd": cfg["tesseract_cmd"],
        },
        "error": None,
        "text_len_final": 0,
    }

    try:
        file_bytes = _read_file_bytes(file_path)
        text, dbg_ocr = extract_text_any(
            file_bytes=file_bytes,
            filename=os.path.basename(file_path),
            tesseract_cmd=cfg["tesseract_cmd"],
            poppler_path=cfg["poppler_path"],
            min_text_len_threshold=cfg["min_text_len_threshold"],
            ocr_dpi=cfg["ocr_dpi"],
        )
        dbg["extract"] = dbg_ocr
        dbg["text_len_final"] = len(text or "")
        return (text or ""), dbg
    except Exception as e:
        dbg["error"] = f"{type(e).__name__}: {e}"
        return "", dbg


# =========================
# ADAPTERS DE PARSER (Fase 1)
# =========================

def _parse_proposta_daycoval(file_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapter Fase 1:
    - Extrai texto (native -> OCR se necessário)
    - Passa raw_text para o parser (API real: analyze_proposta_daycoval(raw_text=...))
    - Não bloqueia
    """
    raw_text, dbg_text = _extract_text_best_effort(file_path, context)

    try:
        fields = analyze_proposta_daycoval(
            raw_text=raw_text,
            filename=os.path.basename(file_path),
            return_debug=False,
        )
    except Exception as e:
        fields = {"debug": {"parser_error": f"{type(e).__name__}: {e}"}}

    if isinstance(fields, dict):
        fields.setdefault("debug", {})
        if isinstance(fields["debug"], dict):
            fields["debug"]["text_extract"] = dbg_text
        else:
            fields["debug"] = {"text_extract": dbg_text}
        return fields

    return {"debug": {"text_extract": dbg_text}}


def _parse_cnh(file_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapter Fase 1:
    - Extrai texto (native -> OCR se necessário)
    - CNH: analyze_cnh retorna (fields, dbg) SEMPRE
    - Persistimos fields em data e colocamos debug agregado em data.debug
    - Não bloqueia
    """
    raw_text, dbg_text = _extract_text_best_effort(file_path, context)

    try:
        fields, dbg_parser = analyze_cnh(raw_text=raw_text, filename=os.path.basename(file_path), use_gemini=True)
    except Exception as e:
        fields, dbg_parser = ({}, {"parser_error": f"{type(e).__name__}: {e}"})

    if not isinstance(fields, dict):
        # fallback defensivo
        fields = {}

    fields.setdefault("debug", {})
    if not isinstance(fields["debug"], dict):
        fields["debug"] = {}

    fields["debug"]["text_extract"] = dbg_text
    fields["debug"]["parser_debug"] = dbg_parser if isinstance(dbg_parser, dict) else {"raw": str(dbg_parser)}

    return fields


PARSERS = {
    "proposta_daycoval": _parse_proposta_daycoval,
    "cnh": _parse_cnh,
}


# =========================
# ORQUESTRADOR — FASE 1
# =========================

def start_case(*, storage_root: str = "storage/phase1") -> str:
    case_id = str(uuid.uuid4())
    os.makedirs(os.path.join(storage_root, case_id), exist_ok=True)

    meta = {
        "case_id": case_id,
        "phase": 1,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _write_json(os.path.join(storage_root, case_id, "_case.json"), meta)
    return case_id


def collect_document(
    case_id: str,
    file_path: str,
    *,
    document_type: DocumentType,
    context: Optional[Dict[str, Any]] = None,
    storage_root: str = "storage/phase1",
) -> Dict[str, Any]:
    """
    Não-bloqueante:
    - Se file_path não existir ou der erro de leitura, ainda persiste payload com debug de erro.
    """
    if document_type not in PARSERS:
        raise ValueError(f"Tipo de documento não suportado: {document_type}")

    context = context or {}
    document_id = str(uuid.uuid4())

    file_hash: Optional[str] = None
    collect_error: Optional[str] = None

    # hash (best-effort)
    try:
        file_hash = _hash_file(file_path)
    except Exception as e:
        collect_error = f"{type(e).__name__}: {e}"
        file_hash = None

    # parse (best-effort)
    parser = PARSERS[document_type]
    try:
        parsed = parser(file_path, context)
    except Exception as e:
        parsed = {"debug": {"parser_error": f"{type(e).__name__}: {e}"}}

    # injeta erro de coleta no debug do data (se houver)
    if collect_error:
        if isinstance(parsed, dict):
            parsed.setdefault("debug", {})
            if isinstance(parsed["debug"], dict):
                parsed["debug"]["collect_error"] = collect_error
            else:
                parsed["debug"] = {"collect_error": collect_error}
        else:
            parsed = {"debug": {"collect_error": collect_error, "raw": str(parsed)}}

    payload = {
        "case_id": case_id,
        "document_id": document_id,
        "document_type": document_type,
        "file_path": file_path,
        "file_hash": file_hash,
        "data": parsed,
        "created_at": datetime.now(UTC).isoformat(),
    }

    out_dir = os.path.join(storage_root, case_id, document_type)
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"{document_id}.json")
    _write_json(out_path, payload)

    return payload


def case_status(
    case_id: str,
    *,
    package: str = "gate1_proposta_cnh",
    storage_root: str = "storage/phase1",
) -> CaseStatus:
    required = PACKAGES[package]
    present = _present_document_types(case_id, storage_root)

    missing = set(required) - present
    return CaseStatus(
        case_id=case_id,
        package=package,
        present=present,
        missing=missing,
        is_complete=len(missing) == 0,
    )


# =========================
# AUXILIARES
# =========================

def _present_document_types(case_id: str, storage_root: str) -> Set[str]:
    base = os.path.join(storage_root, case_id)
    if not os.path.isdir(base):
        return set()

    found: Set[str] = set()
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if os.path.isdir(p) and any(f.endswith(".json") for f in os.listdir(p)):
            found.add(name)
    return found


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
