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
from typing import Any, Callable, Dict, Optional, Tuple


# ======================================================================================
# Storage / config
# ======================================================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_root() -> Path:
    """
    Mantém compatibilidade com a estrutura atual.
    Por padrão: storage/phase1
    Permite override por env var para testes: PHASE1_STORAGE_ROOT
    """
    return Path(os.getenv("PHASE1_STORAGE_ROOT", "storage/phase1"))


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
# Parser registry + adapters
# ======================================================================================

ParserFn = Callable[[str], Dict[str, Any]]


def _lazy_import_parser(module_name: str, fn_name: str) -> Optional[ParserFn]:
    """
    Importa parsers sob demanda para evitar custo/efeitos colaterais e
    para manter a Fase 1 resiliente (não bloquear fluxo).
    """
    try:
        mod = __import__(module_name, fromlist=[fn_name])
        fn = getattr(mod, fn_name)
        if not callable(fn):
            return None
        return fn  # type: ignore[return-value]
    except Exception:
        return None


def _parser_registry() -> Dict[DocumentType, Optional[ParserFn]]:
    """
    Mapeia tipos para suas funções de análise em parsers/.
    Se um parser não existir, o collect_document ainda persiste bruto e segue.
    """
    return {
        # Gate 1
        DocumentType.PROPOSTA_DAYCOVAL: _lazy_import_parser(
            "parsers.proposta_daycoval", "analyze_proposta_daycoval"
        ),
        DocumentType.CNH: _lazy_import_parser(
            "parsers.cnh", "analyze_cnh"  # se seu repo usa outro nome, ajuste aqui
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
        # fallback simples
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
        # Mantém a mesma ideia: persistir bruto + o que der para extrair.
        # Se falhar, não bloqueia: data fica None e o erro fica em debug.
        "data": parsed_data,
        "debug": {
            "parse_error": parse_error,
        },
    }


def _write_doc_json(case_id: str, document_type: DocumentType, doc_id: str, doc: Dict[str, Any]) -> Path:
    root = _storage_root()
    out_dir = root / case_id / document_type.value
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_id}.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ======================================================================================
# Public API (Fase 1)
# ======================================================================================

def start_case() -> str:
    """
    Cria um novo case_id.
    Mantém comportamento simples e determinístico: uuid4.
    """
    return str(uuid.uuid4())


def collect_document(case_id: str, file_path: str, document_type: str | DocumentType) -> Dict[str, Any]:
    """
    Coleta e persiste um documento na Fase 1.

    Regras atendidas:
    - Não bloquear fluxo: sempre persiste payload bruto; parser pode falhar sem exception.
    - Não conclui aprovado/reprovado.
    - Mantém compatibilidade do storage: storage/phase1/<case_id>/<document_type>/<doc_id>.json
    """
    dt = DocumentType(document_type) if not isinstance(document_type, DocumentType) else document_type
    doc_id = str(uuid.uuid4())

    raw = _read_file_as_raw_payload(file_path)

    parsers = _parser_registry()
    parser = parsers.get(dt)

    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[Dict[str, Any]] = None

    if parser is not None:
        try:
            parsed = parser(file_path)
        except Exception as e:
            parse_error = {
                "message": str(e),
                "type": e.__class__.__name__,
                "traceback": traceback.format_exc(),
            }
            parsed = None
    else:
        # Parser ausente: não é erro "fatal". Persistimos e seguimos.
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
    Gate 1 permanece INTACTO:
    exige apenas Proposta (Daycoval) + CNH coletados (existência de ao menos 1 JSON em cada pasta).
    """
    root = _storage_root() / case_id

    proposta_dir = root / DocumentType.PROPOSTA_DAYCOVAL.value
    cnh_dir = root / DocumentType.CNH.value

    def _has_any_json(d: Path) -> bool:
        return d.exists() and any(p.suffix.lower() == ".json" for p in d.iterdir() if p.is_file())

    return _has_any_json(proposta_dir) and _has_any_json(cnh_dir)


def list_collected_documents(case_id: str) -> Dict[str, Any]:
    """
    Utilitário: lista o que já foi coletado (por tipo) sem inferir/aprovar nada.
    """
    root = _storage_root() / case_id
    out: Dict[str, Any] = {"case_id": case_id, "types": {}}

    if not root.exists():
        return out

    for dt in DocumentType:
        d = root / dt.value
        if not d.exists():
            continue
        docs = sorted([p.name for p in d.glob("*.json") if p.is_file()])
        if docs:
            out["types"][dt.value] = docs

    out["gate1_ready"] = gate1_is_ready(case_id)
    return out
