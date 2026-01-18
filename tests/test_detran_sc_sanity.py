# tests/test_detran_sc_sanity.py
from parsers.detran_sc import analyze_detran_sc


def test_detran_sc_aberta_ofuscado():
    out = analyze_detran_sc(
        "tests/fixtures/detranaberta.pdf",
        consulta="aberta",
    )

    assert out["proprietario_nome"] is not None
    assert out["proprietario_nome_ofuscado"] is True

    # iniciais extraídas quando houver padrão J*** S*** etc.
    if out["proprietario_iniciais"] is not None:
        assert len(out["proprietario_iniciais"]) >= 2
        assert isinstance(out["proprietario_iniciais_tokens"], list)
        assert len(out["proprietario_iniciais_tokens"]) >= 2

    assert isinstance(out["situacao_texto"], str)

    # best-effort extras (não podem quebrar)
    assert out["alienacao_fiduciaria_status"] in {None, "ativa", "inativa", "ausente", "desconhecida"}
    assert isinstance(out["debitos_total_cents"], int)


def test_detran_sc_despachante_completo():
    out = analyze_detran_sc(
        "tests/fixtures/detrandespachante.pdf",
        consulta="despachante",
    )

    assert out["proprietario_nome"] is not None
    assert out["proprietario_nome_ofuscado"] is False

    # despachante não precisa iniciais
    assert out["proprietario_iniciais"] in {None, ""}

    assert out["debitos_texto"] is not None

    # despachante costuma trazer "sem gravame" (ausente)
    assert out["alienacao_fiduciaria_status"] in {None, "ausente", "inativa", "desconhecida", "ativa"}
