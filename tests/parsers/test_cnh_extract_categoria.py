import pytest

from parsers.cnh_fields.categoria import extract_categoria


@pytest.mark.parametrize(
    "raw_text, expected, method_prefix",
    [
        (
            # CAT.HAB header + linha do registro (AB)
            "4d CPF 5 Nº REGISTRO 9 CAT.HAB\n053.856.513-62 05724582704 AB\n",
            "AB",
            "anchor_cat_hab_record_line",
        ),
        (
            # CAT.HAB header + linha do registro (B) com ruído 'E E'
            "4d CPF 5 Nº REGISTRO 9 CAT.HAB = = =\n"
            "053.856.513-62 05724582704 B | Cm E E LT\n",
            "B",
            "anchor_cat_hab_record_line",
        ),
        (
            # CAT.HAB com valor puro na próxima linha
            "9 CAT.HAB\nAE\n",
            "AE",
            "anchor_cat_hab_next_line",
        ),
        (
            # CATEGORIA / CATEGORY fallback
            "CATEGORIA\nB\n",
            "B",
            "anchor_categoria",
        ),
        (
            # evitar pegar header como categoria
            "REPUBLICA FEDERATIVA DO BRASIL\nCARTEIRA NACIONAL DE HABILITACAO\n",
            None,
            "none",
        ),
        (
            # ruído com letras soltas não pode virar categoria
            "DATA EMISSAO 22/12/2022\nVALIDADE 18/12/2032\n",
            None,
            "none",
        ),
        (
            # Regressão: 'CAT.HAB' no header com um monte de 'A' solto não pode virar 'A'
            "4d CPF 5 Nº REGISTRO 9 CAT.HAB = a A | ia | A\n"
            "053.856.513-62 05724582704 B\n",
            "B",
            "anchor_cat_hab_record_line",
        ),
        (
            # CASO MARCOS: anchor + linha seguinte só ruído + linha do registro com AB
            "x x 5 Nº REGISTRO 9 CAT HAB bl on ae\n"
            "= a\n"
            "037.387.379-44 08187887701 ( AB Ly =r a TE ==\n",
            "AB",
            "anchor_cat_hab_record_line",
        ),
    ],
)
def test_extract_categoria_unit_cases(raw_text: str, expected: str | None, method_prefix: str):
    cat, dbg = extract_categoria(raw_text)
    assert cat == expected
    if expected is None:
        assert dbg.get("method") in ("none",) or dbg.get("method") is None
    else:
        assert str(dbg.get("method") or "").startswith(method_prefix)
