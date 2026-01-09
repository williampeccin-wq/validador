from parsers.detran_sc import analyze_detran_sc


def test_detran_sc_aberta_ofuscado():
    out = analyze_detran_sc(
        "tests/fixtures/detranaberta.pdf",
        consulta="aberta",
    )

    assert out["proprietario_nome"] is not None
    assert out["proprietario_nome_ofuscado"] is True
    assert isinstance(out["situacao_texto"], str)


def test_detran_sc_despachante_completo():
    out = analyze_detran_sc(
        "tests/fixtures/detrandespachante.pdf",
        consulta="despachante",
    )

    assert out["proprietario_nome"] is not None
    assert out["proprietario_nome_ofuscado"] is False
    assert out["debitos_texto"] is not None
