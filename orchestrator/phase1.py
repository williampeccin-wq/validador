# orchestrator/phase1.py
from __future__ import annotations

import base64
import io
import json
import os
import re
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_STORAGE_ROOT = Path("storage")


def _set_storage_root(root: str | Path) -> None:
    global _STORAGE_ROOT
    _STORAGE_ROOT = Path(root)


def _env_truthy(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _default_ocr_config() -> Dict[str, Any]:
    return {
        "tesseract_cmd": os.getenv("TESSERACT_CMD", ""),
        "poppler_path": os.getenv("POPPLER_PATH", ""),
        "min_text_len_threshold": int(os.getenv("OCR_MIN_TEXT_LEN_THRESHOLD", "120")),
        "ocr_dpi": int(os.getenv("OCR_DPI", "300")),
    }


@dataclass
class RawPayload:
    filename: str
    mime_type: str
    content_b64: str


def _guess_mime_type(filename: str) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".pdf"):
        return "application/pdf"
    if fn.endswith(".png"):
        return "image/png"
    if fn.endswith(".jpg") or fn.endswith(".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def _read_file_as_raw_payload(file_path: str) -> RawPayload:
    p = Path(file_path)
    b = p.read_bytes()
    return RawPayload(
        filename=p.name,
        mime_type=_guess_mime_type(p.name),
        content_b64=base64.b64encode(b).decode("ascii"),
    )


def _phase1_case_dir(case_id: str) -> Path:
    return _STORAGE_ROOT / "phase1" / case_id


def _phase1_doc_dir(case_id: str, dt: "DocumentType") -> Path:
    return _phase1_case_dir(case_id) / dt.value


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def start_case(storage_root: str | Path | None = None) -> str:
    if storage_root is not None:
        _set_storage_root(storage_root)
    case_id = str(uuid.uuid4())
    _ensure_dir(_phase1_case_dir(case_id))
    return case_id


# ======================================================================================
# Document types
# ======================================================================================
class DocumentType(str, Enum):
    PROPOSTA_DAYCOVAL = "proposta_daycoval"
    CNH = "cnh"

    # Mantido por compat, mas na etapa CNH você já decidiu ignorar “validação”
    CNH_SENATRAN = "cnh_senatran"

    HOLERITE = "holerite"
    FOLHA = "folha"
    EXTRATO_BANCARIO = "extrato_bancario"


OPTIONAL_DOCS = {DocumentType.HOLERITE, DocumentType.FOLHA, DocumentType.EXTRATO_BANCARIO}


def _load_parser_for(dt: DocumentType):
    if dt == DocumentType.PROPOSTA_DAYCOVAL:
        from parsers.proposta_daycoval import analyze_proposta_daycoval

        return analyze_proposta_daycoval
    if dt in (DocumentType.CNH, DocumentType.CNH_SENATRAN):
        from parsers.cnh import analyze_cnh

        return analyze_cnh
    if dt == DocumentType.HOLERITE:
        from parsers.holerite import analyze_holerite

        return analyze_holerite
    if dt == DocumentType.FOLHA:
        from parsers.folha import analyze_folha

        return analyze_folha
    if dt == DocumentType.EXTRATO_BANCARIO:
        from parsers.extrato_bancario import analyze_extrato_bancario

        return analyze_extrato_bancario
    return None


def _invoke_parser(parser_fn, *, raw_text: str, filename: str) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None, Dict[str, Any] | None]:
    try:
        try:
            fields, p_dbg = parser_fn(raw_text=raw_text, filename=filename)
        except TypeError:
            fields = parser_fn(raw_text)
            p_dbg = {}
        return (fields or {}), (p_dbg or {}), None
    except Exception as e:
        err = {
            "type": "ParserError",
            "message": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }
        return None, {"error": err["message"], "traceback": err["traceback"]}, err


# ======================================================================================
# Text extraction
# ======================================================================================
def _extract_text_phase1(file_path: str, raw: RawPayload, *, force_ocr: bool = False) -> Tuple[str, Dict[str, Any]]:
    """
    Best-effort:
    - tenta nativo (PDF)
    - OCR só se PHASE1_ENABLE_OCR=1 ou force_ocr=True
    """
    native_text = ""
    native_dbg: Dict[str, Any] = {"ok": False}

    try:
        from core.pdf_text import extract_pdf_text_native

        if raw.mime_type == "application/pdf":
            pdf_bytes = base64.b64decode(raw.content_b64)
            native_text = (extract_pdf_text_native(pdf_bytes) or "").strip()
            if not force_ocr:
                min_len = int(os.getenv("PHASE1_MIN_NATIVE_TEXT_LEN", "200"))
                if len(native_text) >= min_len:
                    return native_text, {"extractor": {"mode": "pdf_native"}, "native_text_len": len(native_text), "force_ocr": bool(force_ocr)}
            native_dbg = {"ok": True, "native_text_len": len(native_text)}
    except Exception as e:
        native_dbg = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}

    enable_ocr = _env_truthy("PHASE1_ENABLE_OCR", default="0") or force_ocr
    if enable_ocr:
        ocr_cfg = _default_ocr_config()
        try:
            from core.ocr import extract_text_any

            text, dbg = extract_text_any(
                file_bytes=base64.b64decode(raw.content_b64),
                filename=raw.filename,
                tesseract_cmd=str(ocr_cfg.get("tesseract_cmd") or ""),
                poppler_path=str(ocr_cfg.get("poppler_path") or ""),
                min_text_len_threshold=int(ocr_cfg.get("min_text_len_threshold") or 120),
                ocr_dpi=int(ocr_cfg.get("ocr_dpi") or 300),
            )
            return (text or ""), {"extractor": {"mode": "ocr"}, "native": native_dbg, "ocr": dbg, "force_ocr": bool(force_ocr)}
        except Exception as e:
            return "", {"extractor": {"mode": "ocr"}, "native": native_dbg, "ocr": {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}, "force_ocr": bool(force_ocr)}

    return native_text or "", {"extractor": {"mode": "native_only"}, "native": native_dbg, "ocr": None, "force_ocr": bool(force_ocr)}


def _extract_text_cnh_best(file_path: str, raw: RawPayload, *, analyze_cnh_fn=None) -> Tuple[str, Dict[str, Any]]:
    """
    CNH: sempre OCR (multipass + fallback).
    Mesmo que parser esteja indisponível, ainda retorna o melhor por heurística (len/tokens).
    """
    ocr_cfg = _default_ocr_config()

    try:
        env_dpi = int(ocr_cfg.get("ocr_dpi") or 0)
    except Exception:
        env_dpi = 0
    dpi = max(350, env_dpi) if env_dpi else 350

    pdf_bytes = base64.b64decode(raw.content_b64)
    candidates: List[Dict[str, Any]] = []

    # 1) multipass
    try:
        from core.ocr import _ocr_pdf_bytes_multipass

        t_mp, variant = _ocr_pdf_bytes_multipass(
            pdf_bytes,
            poppler_path=str(ocr_cfg.get("poppler_path") or ""),
            dpi=dpi,
        )
        candidates.append({"text": t_mp or "", "source": "multipass", "variant": variant, "dpi": dpi})
    except Exception as e:
        candidates.append({"text": "", "source": "multipass", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc(), "dpi": dpi})

    # 2) generic OCR
    try:
        from core.ocr import extract_text_any

        t_any, dbg_any = extract_text_any(
            file_bytes=pdf_bytes,
            filename=raw.filename,
            tesseract_cmd=str(ocr_cfg.get("tesseract_cmd") or ""),
            poppler_path=str(ocr_cfg.get("poppler_path") or ""),
            min_text_len_threshold=int(ocr_cfg.get("min_text_len_threshold") or 120),
            ocr_dpi=dpi,
        )
        candidates.append({"text": t_any or "", "source": "generic", "dbg": dbg_any or {}, "dpi": dpi})
    except Exception as e:
        candidates.append({"text": "", "source": "generic", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc(), "dpi": dpi})

    # score
    def _score(txt: str) -> Tuple[int, Dict[str, Any]]:
        txt = txt or ""
        rs: Dict[str, Any] = {"text_len": len(txt)}
        s = 0

        # heurística mínima (mesmo sem parser)
        up = txt.upper()
        if "SENATRAN" in up or "SECRETARIA NACIONAL" in up:
            s += 2
        if re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", txt):
            s += 8
            rs["cpf_like"] = True
        if re.search(r"\b\d{2}/\d{2}/\d{4}\b", txt):
            s += 3
            rs["dates_like"] = True

        if analyze_cnh_fn is not None:
            try:
                fields, dbg = analyze_cnh_fn(raw_text=txt, filename=raw.filename)
                if fields.get("cpf"):
                    s += 10
                    rs["cpf"] = True
                if fields.get("validade"):
                    s += 6
                    rs["validade"] = True
                if fields.get("data_nascimento"):
                    s += 4
                    rs["data_nascimento"] = True
                if fields.get("cidade_nascimento") and fields.get("uf_nascimento"):
                    s += 4
                    rs["naturalidade"] = True
                if fields.get("nome"):
                    s += 6
                    rs["nome"] = True
                rs["mode"] = (dbg or {}).get("mode")
                rs["nome_detectado"] = (dbg or {}).get("nome_detectado")
                rs["found_dates"] = (dbg or {}).get("found_dates")
            except Exception as e:
                rs["analyze_error"] = f"{type(e).__name__}: {e}"

        if len(txt) < 300:
            s -= 5
            rs["penalidade_texto_curto"] = len(txt)

        return s, rs

    scored: List[Dict[str, Any]] = []
    for c in candidates:
        sc, rs = _score(c.get("text") or "")
        scored.append({**c, "score": sc, "reasons": rs})

    scored_sorted = sorted(scored, key=lambda x: (x.get("score", 0), len(x.get("text") or "")), reverse=True)
    best_text = (scored_sorted[0].get("text") or "").strip() if scored_sorted else ""
    if not best_text:
        best_text = "\n".join([(x.get("text") or "").strip() for x in scored_sorted if (x.get("text") or "").strip()]).strip()

    dbg = {
        "mode": "cnh_best_selector",
        "dpi": dpi,
        "chosen": {
            "source": scored_sorted[0].get("source") if scored_sorted else None,
            "variant": scored_sorted[0].get("variant") if scored_sorted else None,
            "score": scored_sorted[0].get("score") if scored_sorted else None,
            "text_len": len(best_text),
        },
        "candidates": [
            {
                "source": x.get("source"),
                "variant": x.get("variant"),
                "score": x.get("score"),
                "text_len": len(x.get("text") or ""),
                "has_error": bool(x.get("error")),
                "reasons": x.get("reasons"),
            }
            for x in scored_sorted
        ],
    }

    # se ainda vazio, adiciona diagnóstico do OCR (sem bloquear)
    if not best_text:
        try:
            from core.ocr import diagnose_environment

            dbg["diagnose_environment"] = diagnose_environment(
                tesseract_cmd=str(ocr_cfg.get("tesseract_cmd") or ""),
                poppler_path=str(ocr_cfg.get("poppler_path") or ""),
            )
        except Exception as e:
            dbg["diagnose_environment_error"] = f"{type(e).__name__}: {e}"

    return best_text or "", dbg


def _doc_payload(
    *,
    dt: DocumentType,
    doc_id: str,
    raw: RawPayload,
    raw_text: str,
    parsed: Dict[str, Any] | None,
    parse_error: Dict[str, Any] | None,
    extractor_debug: Dict[str, Any] | None,
    parser_debug: Dict[str, Any] | None,
) -> Dict[str, Any]:
    return {
        "meta": {
            "doc_id": doc_id,
            "document_type": dt.value,
            "filename": raw.filename,
            "mime_type": raw.mime_type,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "raw_b64_len": len(raw.content_b64 or ""),
        },
        "raw": {
            "filename": raw.filename,
            "mime_type": raw.mime_type,
            "content_b64": raw.content_b64,
        },
        "raw_text": raw_text,
        "text": raw_text,
        "text_len": len(raw_text or ""),
        "data": parsed or {},
        "parse_error": parse_error,
        "extractor_debug": extractor_debug,
        "parser_debug": parser_debug,
    }


def collect_document(
    case_id: str,
    file_path: str,
    *,
    document_type: str | DocumentType,
    storage_root: str | Path | None = None,
) -> Dict[str, Any]:
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
    should_parse = not (dt in OPTIONAL_DOCS and not parse_optional)

    raw_text = ""

    # 1) SEMPRE extrair texto para CNH (mesmo se parser falhar/indisponível)
    if dt in (DocumentType.CNH, DocumentType.CNH_SENATRAN):
        analyze_cnh_fn = None
        try:
            analyze_cnh_fn = _load_parser_for(dt)  # pode falhar/import
        except Exception as e:
            parser_debug = {"error": f"load_parser_error: {type(e).__name__}: {e}", "traceback": traceback.format_exc()}
            analyze_cnh_fn = None

        try:
            raw_text, extractor_debug = _extract_text_cnh_best(file_path, raw, analyze_cnh_fn=analyze_cnh_fn)
        except Exception as e:
            raw_text = ""
            extractor_debug = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}

        # se veio vazio, registra erro de extração (sem bloquear)
        if not (raw_text or "").strip():
            parse_error = {
                "type": "ExtractorError",
                "message": "CNH raw_text ficou vazio (OCR falhou ou não executou). Veja extractor_debug.",
            }

        # parse só se should_parse e se temos parser (CNH usa analyze_cnh)
        if should_parse and analyze_cnh_fn is not None and (raw_text or "").strip():
            parsed, parser_debug, parse_error2 = _invoke_parser(analyze_cnh_fn, raw_text=raw_text, filename=raw.filename)
            if parse_error is None:
                parse_error = parse_error2

    else:
        # fluxo normal (outros docs)
        if should_parse:
            parser = None
            try:
                parser = _load_parser_for(dt)
            except Exception as e:
                parser = None
                parser_debug = {"error": f"load_parser_error: {type(e).__name__}: {e}", "traceback": traceback.format_exc()}

            try:
                raw_text, extractor_debug = _extract_text_phase1(
                    file_path,
                    raw,
                    force_ocr=False,
                )
            except Exception as e:
                raw_text = ""
                extractor_debug = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}

            if parser is not None and (raw_text or "").strip():
                parsed, parser_debug, parse_error = _invoke_parser(parser, raw_text=raw_text, filename=raw.filename)

    # persist
    out_dir = _phase1_doc_dir(case_id, dt)
    _ensure_dir(out_dir)
    out_path = out_dir / f"{doc_id}.json"

    doc = _doc_payload(
        dt=dt,
        doc_id=doc_id,
        raw=raw,
        raw_text=raw_text or "",
        parsed=parsed,
        parse_error=parse_error,
        extractor_debug=extractor_debug,
        parser_debug=parser_debug,
    )

    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc
