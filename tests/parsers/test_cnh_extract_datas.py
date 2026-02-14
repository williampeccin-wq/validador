from __future__ import annotations

import glob
import os

from orchestrator.phase1 import collect_document, start_case
from parsers.cnh_fields.datas import extract_datas_mrz


def test_extract_datas_mrz_unit_cases():
    raw = "9308097M3212183BRA<<<<<<<<<<<4\n"
    out = extract_datas_mrz(raw)
    assert out.data_nascimento == "09/08/1993"
    assert out.validade == "18/12/2032"
    assert out.dbg.get("method") == "mrz_line"

    raw2 = "8007131M3510203BRA<<<<<<<<<<<0\n"
    out2 = extract_datas_mrz(raw2)
    assert out2.data_nascimento == "13/07/1980"
    assert out2.validade == "20/10/2035"

    raw3 = "nada a ver aqui\n"
    out3 = extract_datas_mrz(raw3)
    assert out3.data_nascimento is None
    assert out3.validade is None
    assert out3.dbg.get("method") == "none"


def test_extract_datas_mrz_smoke_fixtures_has_both_dates():
    pdfs = sorted(glob.glob("tests/fixtures/cnh/*.pdf"))
    assert pdfs, "Sem PDFs em tests/fixtures/cnh/*.pdf"

    for pdf in pdfs:
        cid = start_case()
        doc = collect_document(cid, pdf, document_type="cnh")
        raw = (doc or {}).get("raw_text") or ""
        out = extract_datas_mrz(raw)
        assert out.data_nascimento, f"Sem data_nascimento MRZ em {os.path.basename(pdf)}"
        assert out.validade, f"Sem validade MRZ em {os.path.basename(pdf)}"
