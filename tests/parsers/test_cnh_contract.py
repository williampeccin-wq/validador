# tests/parsers/test_cnh_contract.py
from parsers.cnh import analyze_cnh


def test_analyze_cnh_returns_2_tuple_contract():
    res = analyze_cnh(raw_text="X", filename="x")
    assert isinstance(res, tuple)
    assert len(res) == 2
    fields, dbg = res
    assert isinstance(fields, dict)
    assert isinstance(dbg, dict)
