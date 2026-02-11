from __future__ import annotations

import glob
import os
from typing import Any, Dict, Optional, Tuple


def _safe(s: Any) -> str:
    if s is None:
        return ""
    return str(s)


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else (s[: n - 1] + "…")


def _extract_fields_from_analyze(raw_text: str) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Usa o orquestrador atual (parsers/cnh.py) — contrato 3 retornos:
      (fields, dbg, parse_error)
    """
    from parsers.cnh import analyze_cnh

    fields, dbg, parse_error = analyze_cnh(raw_text)
    if not isinstance(fields, dict):
        raise TypeError(f"analyze_cnh fields esperado dict, veio: {type(fields)}")
    if not isinstance(dbg, dict):
        raise TypeError(f"analyze_cnh dbg esperado dict, veio: {type(dbg)}")
    if parse_error is not None and not isinstance(parse_error, dict):
        raise TypeError(f"analyze_cnh parse_error esperado dict|None, veio: {type(parse_error)}")
    return fields, dbg, parse_error


def main() -> int:
    pdfs = sorted(glob.glob("tests/fixtures/cnh/*.pdf"))
    if not pdfs:
        print("Sem PDFs em tests/fixtures/cnh/*.pdf")
        return 2

    from orchestrator.phase1 import start_case, collect_document

    rows = []
    for pdf in pdfs:
        case_id = start_case()
        doc = collect_document(case_id, pdf, document_type="cnh")
        raw_text = (doc or {}).get("raw_text") or ""

        fields, dbg, parse_error = _extract_fields_from_analyze(raw_text)

        nome = fields.get("nome")
        cat = fields.get("categoria")

        nat = fields.get("naturalidade") if isinstance(fields.get("naturalidade"), dict) else None
        cidade = nat.get("cidade") if isinstance(nat, dict) else fields.get("cidade_nascimento")
        uf = nat.get("uf") if isinstance(nat, dict) else fields.get("uf_nascimento")

        fv2 = dbg.get("fields_v2") if isinstance(dbg.get("fields_v2"), dict) else {}
        nome_dbg = (fv2.get("nome") if isinstance(fv2, dict) else None) or {}
        cat_dbg = (fv2.get("categoria") if isinstance(fv2, dict) else None) or {}
        nat_dbg = (fv2.get("naturalidade") if isinstance(fv2, dict) else None) or {}

        nome_method = nome_dbg.get("method")
        mrz_decision = (((nome_dbg.get("mrz") or {}).get("decision")) if isinstance(nome_dbg.get("mrz"), dict) else None)

        cat_method = cat_dbg.get("method")

        nat_method = nat_dbg.get("method")

        rows.append(
            {
                "file": os.path.basename(pdf),
                "nome": _safe(nome),
                "nome_method": _safe(nome_method),
                "mrz_decision": _safe(mrz_decision),
                "categoria": _safe(cat),
                "cat_method": _safe(cat_method),
                "cidade": _safe(cidade),
                "uf": _safe(uf),
                "nat_method": _safe(nat_method),
                "parse_missing": _safe((parse_error or {}).get("missing")) if isinstance(parse_error, dict) else "",
            }
        )

    headers = [
        "file",
        "nome",
        "nome_method",
        "mrz_decision",
        "categoria",
        "cat_method",
        "cidade",
        "uf",
        "nat_method",
        "parse_missing",
    ]
    colw = {h: len(h) for h in headers}

    for r in rows:
        colw["file"] = max(colw["file"], len(_safe(r["file"])))
        colw["nome"] = max(colw["nome"], len(_truncate(_safe(r["nome"]), 42)))
        colw["nome_method"] = max(colw["nome_method"], len(_safe(r["nome_method"])))
        colw["mrz_decision"] = max(colw["mrz_decision"], len(_truncate(_safe(r["mrz_decision"]), 18)))
        colw["categoria"] = max(colw["categoria"], len(_safe(r["categoria"])))
        colw["cat_method"] = max(colw["cat_method"], len(_truncate(_safe(r["cat_method"]), 22)))
        colw["cidade"] = max(colw["cidade"], len(_truncate(_safe(r["cidade"]), 26)))
        colw["uf"] = max(colw["uf"], len(_safe(r["uf"])))
        colw["nat_method"] = max(colw["nat_method"], len(_safe(r["nat_method"])))
        colw["parse_missing"] = max(colw["parse_missing"], len(_truncate(_safe(r["parse_missing"]), 24)))

    def fmt_row(rr: Dict[str, Any]) -> str:
        return (
            f"{_safe(rr['file']).ljust(colw['file'])} | "
            f"{_truncate(_safe(rr['nome']), 42).ljust(colw['nome'])} | "
            f"{_safe(rr['nome_method']).ljust(colw['nome_method'])} | "
            f"{_truncate(_safe(rr['mrz_decision']), 18).ljust(colw['mrz_decision'])} | "
            f"{_safe(rr['categoria']).ljust(colw['categoria'])} | "
            f"{_truncate(_safe(rr['cat_method']), 22).ljust(colw['cat_method'])} | "
            f"{_truncate(_safe(rr['cidade']), 26).ljust(colw['cidade'])} | "
            f"{_safe(rr['uf']).ljust(colw['uf'])} | "
            f"{_safe(rr['nat_method']).ljust(colw['nat_method'])} | "
            f"{_truncate(_safe(rr['parse_missing']), 24).ljust(colw['parse_missing'])}"
        )

    sep = "-+-".join("-" * colw[h] for h in headers)
    print(fmt_row({h: h for h in headers}))
    print(sep)
    for r in rows:
        print(fmt_row(r))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
