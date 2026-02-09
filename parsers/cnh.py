from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from parsers.cnh_fields.nome import extract_nome
from parsers.cnh_fields.naturalidade import extract_naturalidade as extract_naturalidade_lines

SCHEMA_VERSION = "cnh.fields.v2"


def analyze_cnh(
    raw_text: str,
    *,
    filename: Optional[str] = None,
    **_kwargs: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    CNH Parser — Fields v2 Orchestrator (gradual refactor).

    Contrato:
      - Retorna sempre 3 itens: (fields, dbg, parse_error)
      - Mantém chaves compatíveis no `fields` (mesmo que None enquanto módulos não existem)
      - Extração determinística por módulo

    Campos implementados:
      - nome: parsers/cnh_fields/nome.py  -> (nome, dbg)
      - naturalidade: parsers/cnh_fields/naturalidade.py (tag v0.4.3...) -> (cidade, uf) via lines[]
    """
    text = raw_text or ""
    lines = text.splitlines()

    # --- v2 extractions ---
    nome, nome_dbg = extract_nome(text)

    cidade, uf = extract_naturalidade_lines(lines)
    naturalidade = {"cidade": cidade, "uf": uf} if (cidade and uf) else None

    # --- fields (compat-first) ---
    fields: Dict[str, Any] = {
        # v2 canonical
        "nome": nome,
        "naturalidade": naturalidade,  # {"cidade": "...", "uf": "..."} ou None

        # legacy-compatible flat keys
        "cidade_nascimento": cidade if cidade else None,
        "uf_nascimento": uf if uf else None,

        # placeholders (módulos futuros)
        "cpf": None,
        "categoria": None,
        "data_nascimento": None,
        "validade": None,
        "filiacao": None,
    }

    # --- dbg (auditável) ---
    dbg: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "filename": filename,
        "fields_v2": {
            "nome": nome_dbg,
            "naturalidade": {
                "method": "legacy_lines_v0.4.3",
                "cidade": cidade,
                "uf": uf,
            },
        },
        "pending_fields": [
            "cpf",
            "categoria",
            "data_nascimento",
            "validade",
            "filiacao",
        ],
    }

    # --- non-blocking parse_error: só sinaliza o que já decidimos implementar ---
    missing: list[str] = []
    if not nome:
        missing.append("nome")
    if not (cidade and uf):
        missing.append("naturalidade")

    parse_error: Optional[Dict[str, Any]] = None
    if missing:
        parse_error = {
            "type": "ParserError",
            "code": "CNH_FIELDS_V2_MISSING",
            "message": "CNH fields v2 incomplete (non-blocking).",
            "missing": missing,
        }

    return fields, dbg, parse_error
