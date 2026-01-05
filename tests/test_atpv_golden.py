# tests/test_atpv_golden.py
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parsers.atpv import analyze_atpv  # ajuste se seu import for diferente

GOLDENS_DIR = Path(__file__).parent / "goldens" / "atpv"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _assert_contract_invariants(out: dict) -> None:
    # Shape mínima
    assert isinstance(out, dict)

    # PASSO 5: mode explícito
    assert "mode" in out, "output deve conter a chave 'mode'"
    assert out["mode"] in ("native", "ocr"), "mode deve ser 'native' ou 'ocr'"

    # Debug deve existir e ser dict (contrato de inspeção)
    assert "debug" in out and isinstance(out["debug"], dict), "output deve conter 'debug' dict"

    dbg = out["debug"]

    # Soft-checks: sempre presentes para garantir sanidade do cross-check
    assert "checks" in dbg and isinstance(dbg["checks"], dict), "debug.checks deve existir e ser dict"
    assert "warnings" in dbg and isinstance(dbg["warnings"], list), "debug.warnings deve existir e ser list"
    assert all(isinstance(w, str) for w in dbg["warnings"]), "debug.warnings deve conter apenas strings"

    checks = dbg["checks"]

    # Campos que sofrem DV cross-check
    fields = ("vendedor_cpf_cnpj", "comprador_cpf_cnpj", "renavam")

    # Sanidade 1: se existe valor extraído, deve existir check correspondente coerente
    for f in fields:
        val = out.get(f)
        if val not in (None, ""):
            assert f in checks, f"debug.checks deve conter a entrada '{f}' quando '{f}' é extraído"
            c = checks[f]
            assert isinstance(c, dict), f"debug.checks.{f} deve ser dict"
            assert "normalized" in c, f"debug.checks.{f}.normalized obrigatório"
            assert "dv_ok" in c, f"debug.checks.{f}.dv_ok obrigatório"
            assert isinstance(c["dv_ok"], bool), f"debug.checks.{f}.dv_ok deve ser boolean"

            norm = c.get("normalized") or ""
            assert norm.isdigit(), f"debug.checks.{f}.normalized deve conter apenas dígitos (got={norm!r})"
            assert norm == _only_digits(val), (
                f"debug.checks.{f}.normalized deve bater com dígitos de out[{f}] "
                f"(out={val!r}, normalized={norm!r})"
            )

    # Sanidade 2 (a mais importante): DV inválido NÃO pode bloquear extração
    # Se dv_ok == False e existiu raw/valor, o campo extraído deve continuar preenchido
    for f in fields:
        c = checks.get(f)
        if isinstance(c, dict) and c.get("dv_ok") is False:
            # Só faz sentido exigir não-bloqueio se havia algum valor/normalized
            norm = (c.get("normalized") or "").strip()
            if norm:
                assert out.get(f) not in (None, ""), f"DV inválido não pode zerar '{f}'"

    # Opcional: warnings são diagnósticos; não podem conter tipos estranhos
    # (já checado acima)


@pytest.mark.golden
@pytest.mark.parametrize(
    "pdf_name",
    [
        "ATPV_EXEMPLO_01.pdf",
        "ATPV_EXEMPLO_02.pdf",
    ],
)
def test_atpv_golden(pdf_name: str) -> None:
    pdf_path = GOLDENS_DIR / pdf_name
    assert pdf_path.exists(), f"PDF não encontrado: {pdf_path}"

    out = analyze_atpv(str(pdf_path))

    _assert_contract_invariants(out)

    golden_path = GOLDENS_DIR / (Path(pdf_name).stem + ".json")

    if os.getenv("WRITE_GOLDEN") == "1":
        _write_json(golden_path, out)
        pytest.skip(f"Golden atualizado: {golden_path}")

    expected = _load_json(golden_path)

    # Igualdade total (contrato + regressão)
    assert out == expected
