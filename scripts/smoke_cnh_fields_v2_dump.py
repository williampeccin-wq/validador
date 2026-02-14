from __future__ import annotations

import glob
import os
from typing import Any, Dict, Optional, Tuple

from orchestrator.phase1 import start_case, collect_document
from parsers.cnh import analyze_cnh


def _safe(s: Any) -> str:
    if s is None:
        return ""
    return str(s)


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else (s[: n - 1] + "…")


def _extract_fields_from_analyze(raw_text: str) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[str]]:
    fields, dbg, err = analyze_cnh(raw_text)
    return fields or {}, dbg or {}, err


def main() -> None:
    pdfs = sorted(glob.glob("tests/fixtures/cnh/*.pdf"))

    header = (
        f"{'file':35} | {'nome':28} | {'categoria':8} | {'cat_method':20} | "
        f"{'cidade':14} | {'uf':2} | {'nat_method':20} | {'nasc(MRZ)':10} | {'val(MRZ)':10}"
    )
    print(header)
    print("-" * len(header))

    for pdf in pdfs:
        cid = start_case()
        doc = collect_document(cid, pdf, document_type="cnh")
        raw = (doc or {}).get("raw_text") or ""

        fields, dbg, err = _extract_fields_from_analyze(raw)

        fv2 = (dbg.get("fields_v2") or {})
        cat_dbg = (fv2.get("categoria") or {})
        nat_dbg = (fv2.get("naturalidade") or {})
        dates_dbg = (fv2.get("datas_mrz") or {})

        nome = _truncate(_safe(fields.get("nome")), 28)
        categoria = _safe(fields.get("categoria"))
        cidade = _truncate(_safe(fields.get("cidade")), 14)
        uf = _safe(fields.get("uf"))
        nasc = _safe(fields.get("data_nascimento"))
        val = _safe(fields.get("validade"))

        print(
            f"{os.path.basename(pdf):35} | "
            f"{nome:28} | {categoria:8} | "
            f"{_truncate(_safe(cat_dbg.get('method')), 20):20} | "
            f"{cidade:14} | {uf:2} | "
            f"{_truncate(_safe(nat_dbg.get('method')), 20):20} | "
            f"{nasc:10} | {val:10}"
        )

        if err:
            print("   parse_error:", err)


if __name__ == "__main__":
    main()
