from parsers.cnh_fields.naturalidade import extract_naturalidade


def test_extract_naturalidade_prefers_date_line_over_recurring_florianopolis_code_line():
    raw = """
    09/08/1993, TERESINA, PI É = 7 da E _
    a FLORIANOPOLIS, SC SC182096297
    """
    cidade, uf, dbg = extract_naturalidade(raw)
    assert (cidade, uf) == ("TERESINA", "PI")
    assert dbg.get("method") == "naturalidade_v2_city_uf_date_line"


def test_extract_naturalidade_rejects_city_too_short_like_ala_es_even_with_date():
    raw = """
    CAROLINE GREGORIO SILVA 09/05/2014 1 ALA, ES nn Rm!
    29/01/1994, PRESIDENTE PRUDENTE, SP Ea tr = von mL
    """
    cidade, uf, dbg = extract_naturalidade(raw)
    assert (cidade, uf) == ("PRESIDENTE PRUDENTE", "SP")
    assert dbg.get("method") == "naturalidade_v2_city_uf_date_line"


def test_extract_naturalidade_returns_none_if_only_florianopolis_like_lines_exist():
    raw = """
    N FLORIANOPOLIS, SC SC203516044
    = FLORIANOPOLIS, SC $C212667963
    """
    cidade, uf, dbg = extract_naturalidade(raw)
    assert cidade is None
    assert uf is None
    assert dbg.get("method") in ("none", "none_low_confidence")


def test_extract_naturalidade_rejects_city_tokens_too_short_like_pst_tes_pa():
    raw = """
    9 10 ” 12 9 10 u 2 . = PST tes, Pa . na
    18/10/2004, ITAJAI, SC E Sm Ea
    """
    cidade, uf, dbg = extract_naturalidade(raw)
    assert (cidade, uf) == ("ITAJAI", "SC")
    assert dbg.get("method") == "naturalidade_v2_city_uf_date_line"
