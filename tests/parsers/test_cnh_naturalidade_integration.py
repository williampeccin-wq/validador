from parsers.cnh import analyze_cnh

def test_analyze_cnh_includes_naturalidade_fields():
    raw = """
    3 DATA, LOCAL E UF DE NASCIMENTO
    18/10/2004, ITAJAI, SC
    """
    fields, dbg = analyze_cnh(raw_text=raw, filename="x.pdf")

    assert fields.get("cidade_nascimento") == "ITAJAI"
    assert fields.get("uf_nascimento") == "SC"
