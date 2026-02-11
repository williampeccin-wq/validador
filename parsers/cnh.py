from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from parsers.cnh_fields.nome import extract_nome
from parsers.cnh_fields.naturalidade import extract_naturalidade
from parsers.cnh_fields.categoria import extract_categoria

SCHEMA_VERSION = "cnh_fields_v2"


def analyze_cnh(raw_text: str, *, filename: str | None = None) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    CNH parser (fields v2) — contrato:
      (fields, dbg, parse_error)

    - Não bloqueia: se faltar campo v2, retorna parse_error (non-blocking) e lista em dbg["pending_fields"].
    - Determinístico e auditável: dbg["fields_v2"][campo] contém o debug de cada extrator.
    """
    fields: Dict[str, Any] = {}
    dbg: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "filename": filename,
        "fields_v2": {},
        "pending_fields": [],
    }

    missing: list[str] = []

    # --- NOME ---
    nome, nome_dbg = extract_nome(raw_text or "")
    fields["nome"] = nome
    dbg["fields_v2"]["nome"] = nome_dbg
    if not nome:
        missing.append("nome")

        # --- NATURALIDADE ---
    lines = (raw_text or "").splitlines()
    cidade, uf = extract_naturalidade(lines)
    nat = {"cidade": cidade, "uf": uf} if (cidade and uf) else None

    nat_dbg = {"field": "naturalidade", "method": "legacy_lines_v0.4.3", "cidade": cidade, "uf": uf}
    fields["naturalidade"] = nat
    dbg["fields_v2"]["naturalidade"] = nat_dbg

    if isinstance(nat, dict):
        fields["cidade_nascimento"] = nat.get("cidade")
        fields["uf_nascimento"] = nat.get("uf")
    else:
        fields["cidade_nascimento"] = None
        fields["uf_nascimento"] = None
        missing.append("naturalidade")


    # --- CATEGORIA ---
    categoria, cat_dbg = extract_categoria(raw_text or "")
    fields["categoria"] = categoria
    dbg["fields_v2"]["categoria"] = cat_dbg
    if not categoria:
        missing.append("categoria")

    dbg["pending_fields"] = missing[:]

    parse_error: Optional[Dict[str, Any]] = None
    if missing:
        parse_error = {
            "type": "ParserError",
            "code": "CNH_FIELDS_V2_MISSING",
            "message": "CNH fields v2 incomplete (non-blocking).",
            "missing": missing,
        }

    return fields, dbg, parse_error
