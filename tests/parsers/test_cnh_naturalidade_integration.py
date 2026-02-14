from parsers.cnh import analyze_cnh


def test_analyze_cnh_includes_naturalidade_fields():
    raw = """
    3 DATA, LOCAL E UF DE NASCIMENTO
    18/10/2004, ITAJAI, SC
    """
    fields, dbg, err = analyze_cnh(raw_text=raw)
    assert err is None
    assert fields.get("cidade") == "ITAJAI"
    assert fields.get("uf") == "SC"
    assert dbg.get("fields_v2", {}).get("naturalidade", {}).get("method") == "naturalidade_v2_city_uf_date_line"
