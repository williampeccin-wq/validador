from parsers.cnh import _extract_naturalidade, _strip_noise_lines


def _lines(s: str) -> list[str]:
    return _strip_noise_lines(s.splitlines())


def test_extract_naturalidade_from_data_local_uf_line():
    raw = """
    DATA, LOCAL E UF DE NASCIMENTO
    18/10/2004, ITAJAI, SC
    """
    cidade, uf = _extract_naturalidade(_lines(raw))
    assert cidade == "ITAJAI"
    assert uf == "SC"


def test_extract_naturalidade_from_naturalidade_inline():
    raw = """
    NATURALIDADE: FLORIANOPOLIS SC
    """
    cidade, uf = _extract_naturalidade(_lines(raw))
    assert cidade == "FLORIANOPOLIS"
    assert uf == "SC"


def test_extract_naturalidade_returns_none_when_absent():
    raw = """
    NOME: FULANO DE TAL
    CPF: 000.000.000-00
    """
    cidade, uf = _extract_naturalidade(_lines(raw))
    assert cidade is None
    assert uf is None
