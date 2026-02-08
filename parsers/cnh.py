from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from parsers.cnh_fields.naturalidade import extract_naturalidade
from parsers.cnh_fields.nome import extract_nome

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
      - Extração determinística por módulo (sem heurística “mágica” aqui)

    Campos implementados (v2):
      - nome (parsers/cnh_fields/nome.py)
      - naturalidade (parsers/cnh_fields/naturalidade.py)

    Campos legados mantidos como placeholders:
      - cpf, categoria, data_nascimento, validade, filiacao
    """
    text = raw_text or ""

    # --- v2 extractions ---
    nome, nome_dbg = extract_nome(text)
    naturalidade, nat_dbg = extract_naturalidade(text)

    cidade_nascimento = None
    uf_nascimento = None
    if isinstance(naturalidade, dict):
        cidade_nascimento = naturalidade.get("cidade")
        uf_nascimento = naturalidade.get("uf")

    # --- fields (compat-first) ---
    fields: Dict[str, Any] = {
        # v2 canonical
        "nome": nome,
        "naturalidade": naturalidade,  # {"cidade": "...", "uf": "..."} ou None

        # legacy-compatible flat keys (mantém consumidores antigos vivos)
        "cidade_nascimento": cidade_nascimento,
        "uf_nascimento": uf_nascimento,

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
            "naturalidade": nat_dbg,
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
    if not cidade_nascimento or not uf_nascimento:
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
