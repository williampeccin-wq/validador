# orchestrator/phase1.py
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List


# ======================================================================================
# Storage / config
# ======================================================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_root() -> Path:
    """
    Default: storage/phase1
    Pode ser sobrescrito por env var PHASE1_STORAGE_ROOT (útil para testes).
    """
    return Path(os.getenv("PHASE1_STORAGE_ROOT", "storage/phase1"))


def _set_storage_root(storage_root: str | Path) -> None:
    os.environ["PHASE1_STORAGE_ROOT"] = str(storage_root)


def _has_any_json(d: Path) -> bool:
    return d.exists() and any(p.suffix == ".json" for p in d.iterdir() if p.is_file())


# ======================================================================================
# Document types (Gate 1 exige apenas Proposta + CNH; demais são opcionais)
# ======================================================================================

class DocumentType(str, Enum):
    # Gate 1
    PROPOSTA_DAYCOVAL = "proposta_daycoval"
    CNH = "cnh"

    # Opcionais na Fase 1 (não alteram Gate 1)
    HOLERITE = "holerite"
    FOLHA_PAGAMENTO = "folha_pagamento"
    EXTRATO_BANCARIO = "extrato_bancario"


# ======================================================================================
# CaseStatus (contrato esperado pelos testes)
# ======================================================================================

@dataclass(frozen=True)
class CaseStatus:
    case_id: str

    # Gate 1 inventory
    has_proposta_daycoval: bool
    has_cnh: bool

    # Gate 1 control
    gate1_ready: bool
    is_complete: bool

    # Gate 1 missing (EXPLÍCITO NOS TESTES)
    missing: List[str]

    # Opcionais (informativo)
    has_holerite: bool
    has_folha_pagamento: bool
    has_extrato_bancario: bool

    # Inventário bruto
    types: Dict[str, List[str]]


# ======================================================================================
# Parser registry (não bloqueante)
# ======================================================================================

ParserFn = Callable[[str], Dict[str, Any]]


def _lazy_import_parser(module_name: str, fn_name: str) -> Optional[ParserFn]:
    try:
        mod = __import__(module_name, fromlist=[fn_name])
        fn = getattr(mod, fn_name)
        return fn if callable(fn) else None
    except Exception:
        return None


def _parser_registry() -> Dict[DocumentType, Optional[ParserFn]]:
    return {
        # Gate 1
        DocumentType.PROPOSTA_DAYCOVAL: _lazy_import_parser(
            "parsers.proposta_daycoval", "analyze_proposta_daycoval"
        ),
        DocumentType.CNH: _lazy_import_parser(
            "parsers.cnh", "analyze_cnh"  # ajuste se seu repo usa outro módulo/função
        ),
        # Opcionais
        DocumentType.HOLERITE: _lazy_import_parser(
            "parsers.holerite", "analyze_holerite"
        ),
        DocumentType.FOLHA_PAGAMENTO: _lazy_import_parser(
            "parsers.folha_pagamento", "analyze_folha_pagamento"
        ),
        DocumentType.EXTRATO_BANCARIO: _lazy_import_parser(
            "parsers.extrato_bancario", "analyze_extrato_bancario"
        ),
    }


# ======================================================================================
# Payload bruto + persistência
# ======================================================================================

@dataclass(frozen=True)
class RawPayload:
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    content_b64: str


def _read_file_as_raw_payload(file_path: str) -> RawPayload:
    p = Path(file_path)
    data = p.read_bytes()

    sha = hashlib.sha256(data).hexdigest()
    mime, _enc = mimetypes.guess_type(str(p))
    if not mime:
        mime = "application/octet-stream"

    return RawPayload(
        filename=p.name,
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha,
        content_b64=base64.b64encode(data).decode("ascii"),
    )


def _build_doc_record(
    *,
    case_id: str,
    doc_id: str,
    document_type: DocumentType,
    raw: RawPayload,
    parsed_data: Optional[Dict[str, Any]],
    parse_error: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema_version": "phase1.v1",
        "phase": 1,
        "case_id": case_id,
        "doc_id": doc_id,
        "document_type": document_type.value,
        "created_at": _utc_now_iso(),
        "raw": {
            "filename": raw.filename,
            "mime_type": raw.mime_type,
            "size_bytes": raw.size_bytes,
            "sha256": raw.sha256,
            "content_b64": raw.content_b64,
        },
        "data": parsed_data,
        "debug": {
            "parse_error": parse_error,
        },
    }


def _write_doc_json(case_id: str, document_type: DocumentType, doc_id: str, doc: Dict[str, Any]) -> Path:
    out_dir = _storage_root() / case_id / document_type.value
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_id}.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ======================================================================================
# Public API (Fase 1)
# ======================================================================================

def start_case(*, storage_root: str | Path | None = None) -> str:
    """
    Compat com testes: aceita storage_root (ex.: .../storage/phase1).
    """
    if storage_root is not None:
        _set_storage_root(storage_root)
    return str(uuid.uuid4())


def collect_document(
    case_id: str,
    file_path: str,
    *,
    document_type: str | DocumentType,
    storage_root: str | Path | None = None,
) -> Dict[str, Any]:
    """
    Coleta e persiste um documento na Fase 1.

    Regras:
    - Não bloquear fluxo (parser pode falhar; ainda assim persiste bruto).
    - Não aprovar/reprovar.
    - Estrutura: storage/phase1/<case_id>/<document_type>/<doc_id>.json

    Compat:
    - aceita storage_root para testes/Phase 2 chamarem sem depender de env var.
    """
    if storage_root is not None:
        _set_storage_root(storage_root)

    dt = DocumentType(document_type) if not isinstance(document_type, DocumentType) else document_type
    doc_id = str(uuid.uuid4())

    raw = _read_file_as_raw_payload(file_path)

    parser = _parser_registry().get(dt)
    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[Dict[str, Any]] = None

    if parser is not None:
        try:
            # Mantemos assinatura simples: parser(file_path)
            parsed = parser(file_path)
        except Exception as e:
            parse_error = {
                "message": str(e),
                "type": e.__class__.__name__,
                "traceback": traceback.format_exc(),
            }
            parsed = None
    else:
        parse_error = {
            "message": "Parser not available for this document_type",
            "type": "ParserNotAvailable",
            "traceback": None,
        }

    doc = _build_doc_record(
        case_id=case_id,
        doc_id=doc_id,
        document_type=dt,
        raw=raw,
        parsed_data=parsed,
        parse_error=parse_error,
    )

    _write_doc_json(case_id, dt, doc_id, doc)
    return doc


def gate1_is_ready(case_id: str) -> bool:
    """
    Gate 1 INTACTO: apenas Proposta Daycoval + CNH.
    """
    root = _storage_root() / case_id
    return _has_any_json(root / DocumentType.PROPOSTA_DAYCOVAL.value) and _has_any_json(root / DocumentType.CNH.value)


def case_status(case_id: str) -> CaseStatus:
    """
    Contrato esperado pelos testes:
    - st.is_complete
    - st.missing contém tipos faltantes do Gate 1
    """
    root = _storage_root() / case_id

    proposta_dir = root / DocumentType.PROPOSTA_DAYCOVAL.value
    cnh_dir = root / DocumentType.CNH.value

    has_proposta = _has_any_json(proposta_dir)
    has_cnh = _has_any_json(cnh_dir)

    missing: List[str] = []
    if not has_proposta:
        missing.append(DocumentType.PROPOSTA_DAYCOVAL.value)
    if not has_cnh:
        missing.append(DocumentType.CNH.value)

    gate1_ready = has_proposta and has_cnh

    has_holerite = _has_any_json(root / DocumentType.HOLERITE.value)
    has_folha = _has_any_json(root / DocumentType.FOLHA_PAGAMENTO.value)
    has_extrato = _has_any_json(root / DocumentType.EXTRATO_BANCARIO.value)

    types: Dict[str, List[str]] = {}
    if root.exists():
        for dt in DocumentType:
            d = root / dt.value
            if d.exists():
                files = sorted(p.name for p in d.glob("*.json"))
                if files:
                    types[dt.value] = files

    return CaseStatus(
        case_id=case_id,
        has_proposta_daycoval=has_proposta,
        has_cnh=has_cnh,
        gate1_ready=gate1_ready,
        is_complete=gate1_ready,
        missing=missing,
        has_holerite=has_holerite,
        has_folha_pagamento=has_folha,
        has_extrato_bancario=has_extrato,
        types=types,
    )
