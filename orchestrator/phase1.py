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
from typing import Any, Dict, Optional, List, Tuple, Callable, Union


# ======================================================================================
# Phase 1 text extraction (NON-BLOCKING)
#
# Objetivo (Opção A): estabilizar a captura.
# - Sempre persistir o bruto.
# - Tentar extrair texto e parsear quando possível.
# - Em qualquer falha de extração/parse, registrar debug e seguir.
#
# Nota importante (portabilidade): em ambientes sem Poppler/Tesseract
# (ex.: CI), OCR pode não estar disponível. Por padrão, a Fase 1 não
# força OCR; ela usa texto nativo de PDF quando disponível.
# OCR pode ser habilitado via PHASE1_ENABLE_OCR=1.
# ======================================================================================


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


def _env_truthy(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _default_ocr_config() -> Dict[str, Any]:
    """Defaults compatíveis com o app.py (mas sem depender de Streamlit)."""
    return {
        "tesseract_cmd": os.getenv("TESSERACT_CMD", "/opt/homebrew/bin/tesseract"),
        "poppler_path": os.getenv("POPPLER_PATH", "/opt/homebrew/bin"),
        "min_text_len_threshold": int(os.getenv("PHASE1_MIN_TEXT_LEN_THRESHOLD", "800")),
        "ocr_dpi": int(os.getenv("PHASE1_OCR_DPI", "350")),
    }


def _extract_text_native_pdf(pdf_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    """Extrai texto nativo de PDF via pdfplumber (sem OCR)."""
    dbg: Dict[str, Any] = {"mode": "native", "pages": None, "native_text_len": 0}
    try:
        import io
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            dbg["pages"] = len(pdf.pages)
            out: List[str] = []
            for p in pdf.pages:
                out.append(p.extract_text() or "")
            text = "\n".join(out).strip()
            dbg["native_text_len"] = len(text)
            return text, dbg
    except Exception as e:
        dbg["error"] = f"{type(e).__name__}: {e}"
        return "", dbg


def _extract_text_phase1(file_path: str, raw: "RawPayload") -> Tuple[str, Dict[str, Any]]:
    """
    Extrai texto de forma não-bloqueante.

    Regra: por padrão, usa somente texto nativo de PDF.
    OCR só roda se PHASE1_ENABLE_OCR=1.
    """
    enable_ocr = _env_truthy("PHASE1_ENABLE_OCR", default="0")

    # PDF: texto nativo primeiro (portável)
    if (raw.mime_type or "").lower() == "application/pdf" or raw.filename.lower().endswith(".pdf"):
        native_text, dbg_native = _extract_text_native_pdf(base64.b64decode(raw.content_b64))
        if native_text or not enable_ocr:
            return native_text, {"extractor": dbg_native, "ocr": None}

        # OCR opcional
        ocr_cfg = _default_ocr_config()
        try:
            from core.ocr import extract_text_any

            text, dbg = extract_text_any(
                file_bytes=base64.b64decode(raw.content_b64),
                filename=raw.filename,
                tesseract_cmd=ocr_cfg["tesseract_cmd"],
                poppler_path=ocr_cfg["poppler_path"],
                min_text_len_threshold=int(ocr_cfg["min_text_len_threshold"]),
                ocr_dpi=int(ocr_cfg["ocr_dpi"]),
            )
            return (text or ""), {"extractor": dbg_native, "ocr": dbg}
        except Exception as e:
            return native_text, {
                "extractor": dbg_native,
                "ocr": {"error": f"{type(e).__name__}: {e}", "enabled": True},
            }

    # Imagem: OCR somente se habilitado
    if enable_ocr:
        ocr_cfg = _default_ocr_config()
        try:
            from core.ocr import extract_text_any

            text, dbg = extract_text_any(
                file_bytes=base64.b64decode(raw.content_b64),
                filename=raw.filename,
                tesseract_cmd=ocr_cfg["tesseract_cmd"],
                poppler_path=ocr_cfg["poppler_path"],
                min_text_len_threshold=int(ocr_cfg["min_text_len_threshold"]),
                ocr_dpi=int(ocr_cfg["ocr_dpi"]),
            )
            return (text or ""), {"extractor": {"mode": "image_ocr"}, "ocr": dbg}
        except Exception as e:
            return "", {"extractor": {"mode": "image_ocr"}, "ocr": {"error": f"{type(e).__name__}: {e}"}}

    return "", {"extractor": {"mode": "none", "reason": "ocr_disabled"}, "ocr": None}


# ======================================================================================
# Document types
# ======================================================================================

class DocumentType(str, Enum):
    # Gate 1
    PROPOSTA_DAYCOVAL = "proposta_daycoval"
    CNH = "cnh"

    # CNH SENATRAN (layout fixo, documento imutável)
    CNH_SENATRAN = "cnh_senatran"

    # Opcionais na Fase 1 (não alteram Gate 1)
    HOLERITE = "holerite"
    FOLHA_PAGAMENTO = "folha_pagamento"
    EXTRATO_BANCARIO = "extrato_bancario"


OPTIONAL_DOCS: set[DocumentType] = {
    DocumentType.HOLERITE,
    DocumentType.FOLHA_PAGAMENTO,
    DocumentType.EXTRATO_BANCARIO,
}


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
# Parser loading (não bloqueante e SEM importar tudo)
# ======================================================================================

ParserFn = Callable[..., Any]


def _parser_specs() -> Dict[DocumentType, Tuple[str, str]]:
    """
    Mapeia document_type -> (module, function)
    Importamos somente o parser do tipo solicitado, para evitar travamentos.
    """
    return {
        DocumentType.PROPOSTA_DAYCOVAL: ("parsers.proposta_daycoval", "analyze_proposta_daycoval"),
        DocumentType.CNH: ("parsers.cnh", "analyze_cnh"),
        DocumentType.CNH_SENATRAN: ("parsers.cnh_senatran", "analyze_cnh_senatran"),
        DocumentType.HOLERITE: ("parsers.holerite", "analyze_holerite"),
        DocumentType.FOLHA_PAGAMENTO: ("parsers.folha_pagamento", "analyze_folha_pagamento"),
        DocumentType.EXTRATO_BANCARIO: ("parsers.extrato_bancario", "analyze_extrato_bancario"),
    }


def _load_parser_for(dt: DocumentType) -> Optional[ParserFn]:
    spec = _parser_specs().get(dt)
    if not spec:
        return None
    module_name, fn_name = spec
    try:
        mod = __import__(module_name, fromlist=[fn_name])
        fn = getattr(mod, fn_name)
        return fn if callable(fn) else None
    except Exception:
        return None


def _invoke_parser(
    parser: ParserFn,
    *,
    file_path: str,
    raw_text: str,
    filename: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Invoca o parser de forma tolerante a variações de assinatura.

    Contratos encontrados no projeto:
    - analyze_proposta_daycoval(raw_text: str, ...) -> dict
    - analyze_cnh(raw_text=..., ...) -> (dict, dbg)
    - parsers antigos podem aceitar (file_path: str) -> dict

    Retorna: (fields, parser_debug)
    """
    try:
        import inspect

        sig = inspect.signature(parser)
        params = sig.parameters

        # Caso 1: aceita raw_text (keyword ou positional)
        if "raw_text" in params:
            out = parser(raw_text=raw_text or "", filename=filename)
        else:
            # Caso 2: assume API antiga por caminho
            out = parser(file_path)

        # Normaliza retorno
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], dict) and isinstance(out[1], dict):
            return out[0], out[1]
        if isinstance(out, dict):
            return out, None

        return None, {"warning": "unexpected_return_type", "type": type(out).__name__}
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}


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
    extractor_debug: Optional[Dict[str, Any]] = None,
    parser_debug: Optional[Dict[str, Any]] = None,
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
            "extractor": extractor_debug,
            "parser": parser_debug,
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
    - Não bloquear fluxo (sempre persiste bruto; parser pode falhar / pode ser pulado).
    - Não aprovar/reprovar.
    - Estrutura: storage/phase1/<case_id>/<document_type>/<doc_id>.json

    Importante:
    - Por padrão, NÃO fazemos parsing dos docs opcionais (holerite/folha/extrato) na Fase 1,
      para evitar travamentos e porque as inferências/validações rodam depois.
    - Se você quiser forçar parsing dos opcionais: export PHASE1_PARSE_OPTIONAL_DOCS=1
    """
    if storage_root is not None:
        _set_storage_root(storage_root)

    dt = DocumentType(document_type) if not isinstance(document_type, DocumentType) else document_type
    doc_id = str(uuid.uuid4())

    raw = _read_file_as_raw_payload(file_path)

    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[Dict[str, Any]] = None
    extractor_debug: Optional[Dict[str, Any]] = None
    parser_debug: Optional[Dict[str, Any]] = None

    parse_optional = _env_truthy("PHASE1_PARSE_OPTIONAL_DOCS", default="0")

    should_parse = True
    if dt in OPTIONAL_DOCS and not parse_optional:
        should_parse = False

    if should_parse:
        parser = _load_parser_for(dt)
        if parser is not None:
            # 1) extrair texto (não-bloqueante)
            try:
                raw_text, extractor_debug = _extract_text_phase1(file_path, raw)
            except Exception as e:
                raw_text = ""
                extractor_debug = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}

            # 2) invocar parser (tolerante a assinatura)
            parsed, parser_debug = _invoke_parser(
                parser,
                file_path=file_path,
                raw_text=raw_text or "",
                filename=raw.filename,
            )

            # 3) se parser retornou warning/error, promover para parse_error (sem quebrar)
            if parser_debug and ("error" in parser_debug):
                parse_error = {
                    "message": parser_debug.get("error"),
                    "type": "ParserError",
                    "traceback": parser_debug.get("traceback"),
                }
        else:
            parse_error = {
                "message": "Parser not available for this document_type",
                "type": "ParserNotAvailable",
                "traceback": None,
            }
    else:
        parse_error = {
            "message": "Parsing skipped for optional document in Phase 1",
            "type": "ParsingSkippedOptional",
            "traceback": None,
        }

    doc = _build_doc_record(
        case_id=case_id,
        doc_id=doc_id,
        document_type=dt,
        raw=raw,
        parsed_data=parsed,
        parse_error=parse_error,
        extractor_debug=extractor_debug,
        parser_debug=parser_debug,
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
