# tests/test_atpv_golden.py
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from parsers.atpv import analyze_atpv  # type: ignore


HERE = Path(__file__).resolve().parent
GOLDEN_DIR = HERE / "goldens" / "atpv"
WRITE_GOLDEN = os.getenv("WRITE_GOLDEN", "").strip() in {"1", "true", "TRUE", "yes", "YES"}

UF_BR_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

FIXTURE_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".webp")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _collect_pairs() -> list[Tuple[Path, Path]]:
    """
    Retorna pares (fixture_path, golden_json_path) para todos os goldens existentes.

    Convenção:
      tests/goldens/atpv/<BASE>.json

    E o fixture correspondente pode existir em (na primeira ocorrência encontrada):
      - tests/fixtures/atpv/<BASE>.<ext>  (preferencial)
      - ou tests/atpv/<BASE>.<ext>
      - ou tests/data/atpv/<BASE>.<ext>
      - ou ao lado do golden: tests/goldens/atpv/<BASE>.<ext>

    Onde <ext> ∈ { .pdf, .png, .jpg, .jpeg, .webp }.
    """
    candidates_roots = [
        HERE / "fixtures" / "atpv",
        HERE / "atpv",
        HERE / "data" / "atpv",
        GOLDEN_DIR,
    ]

    pairs: list[Tuple[Path, Path]] = []
    for golden_path in sorted(GOLDEN_DIR.glob("*.json")):
        base = golden_path.stem
        fixture_path: Path | None = None

        for root in candidates_roots:
            for ext in FIXTURE_EXTS:
                cand = root / f"{base}{ext}"
                if cand.exists():
                    fixture_path = cand
                    break
            if fixture_path is not None:
                break

        if fixture_path is None:
            continue

        pairs.append((fixture_path, golden_path))

    return pairs


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _has_double_space(s: str) -> bool:
    return "  " in s


def _is_jpeg_like(fixture_path: Path, out: Dict[str, Any]) -> bool:
    """
    Heurística para identificar casos "JPEG-like" (imagem/scan), onde faz sentido
    endurecer asserts de identidade (vendedor vs comprador etc).

    Critérios (qualquer um verdadeiro):
      - extensão do arquivo é de imagem (jpg/jpeg/png/webp)
      - out["mode"] ou out["debug"]["mode"] sugere OCR/image
      - debug sugere texto nativo inexistente e OCR presente
    """
    ext = fixture_path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return True

    mode = (out.get("mode") or "").strip().lower()
    debug = out.get("debug") if isinstance(out.get("debug"), dict) else {}
    debug_mode = (debug.get("mode") or "").strip().lower()

    if mode in {"ocr", "image", "jpeg", "img"}:
        return True
    if debug_mode in {"ocr", "image", "jpeg", "img"}:
        return True

    native_len = _as_int(debug.get("native_text_len"), 0)
    ocr_len = _as_int(debug.get("ocr_text_len"), 0)
    if native_len == 0 and ocr_len > 0:
        return True

    native_len2 = _as_int(debug.get("native_len"), 0)
    ocr_len2 = _as_int(debug.get("ocr_len"), 0)
    if native_len2 == 0 and ocr_len2 > 0:
        return True

    return False


@pytest.mark.parametrize("fixture_path,golden_path", _collect_pairs(), ids=lambda p: getattr(p, "name", str(p)))
def test_atpv_golden(fixture_path: Path, golden_path: Path) -> None:
    """
    Golden test do parser de ATPV.

    Regras:
      - Se WRITE_GOLDEN=1: regrava o golden e SKIP (não falha por diferença).
      - Caso contrário: compara output com golden e aplica asserts "endurecidos".
    """
    out: Dict[str, Any] = analyze_atpv(str(fixture_path))

    if WRITE_GOLDEN:
        _write_json(golden_path, out)
        pytest.skip(f"Golden atualizado: {golden_path}")

    expected = _read_json(golden_path)
    assert out == expected

    # ============================================================
    # Passo 4 — invariantes de contrato (shape + sanidade mínima)
    # ============================================================

    REQUIRED_KEYS = {
        "chassi",
        "comprador_cpf_cnpj",
        "comprador_nome",
        "data_venda",
        "debug",
        "municipio",
        "placa",
        "renavam",
        "uf",
        "valor_venda",
        "vendedor_cpf_cnpj",
        "vendedor_nome",
    }
    assert set(out.keys()) == REQUIRED_KEYS, f"Contrato mudou. Keys: {sorted(out.keys())}"

    # Tipos (permitimos None/"" em campos textuais; debug deve ser dict)
    assert isinstance(out["debug"], dict), "debug deve ser dict"

    for k in REQUIRED_KEYS - {"debug"}:
        assert (out[k] is None) or isinstance(out[k], str), f"{k} deve ser str ou None (veio {type(out[k]).__name__})"

    # Campos com strip implícito (se houver valor)
    for k in REQUIRED_KEYS - {"debug"}:
        v = out.get(k)
        if isinstance(v, str) and v != "":
            assert v == v.strip(), f"{k} não deve ter espaços nas bordas: {v!r}"

    # Nomes/município: evitar duplo espaço (indicador de pós-processamento ruim)
    for k in ("vendedor_nome", "comprador_nome", "municipio"):
        v = out.get(k)
        if isinstance(v, str) and v.strip():
            assert not _has_double_space(v), f"{k} não deve conter duplo espaço: {v!r}"

    # CPF/CNPJ: se presente, apenas dígitos e tamanho 11/14
    for k in ("vendedor_cpf_cnpj", "comprador_cpf_cnpj"):
        v = out.get(k)
        if isinstance(v, str) and v.strip():
            digits = _only_digits(v)
            assert digits == v, f"{k} deve conter apenas dígitos (sem pontuação): {v!r}"
            assert len(digits) in (11, 14), f"{k} deve ter 11 (CPF) ou 14 (CNPJ) dígitos: {v!r}"

    # UF: sempre válida
    uf = (out.get("uf") or "").strip().upper()
    assert uf, "uf não pode ser nula/vazia"
    assert uf in UF_BR_VALIDAS, f"uf inválida: {uf!r}"

    # Município saneado (não começar com 'UR ')
    municipio = (out.get("municipio") or "").strip()
    assert municipio, "municipio não pode ser nulo/vazio"
    assert not municipio.upper().startswith("UR "), f"municipio parece não-saneado (prefixo 'UR '): {municipio!r}"

    # data_venda: formato minimamente coerente, se presente
    data_venda = out.get("data_venda")
    if isinstance(data_venda, str) and data_venda.strip():
        # aceitamos dd/mm/aaaa ou aaaa-mm-dd
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", data_venda.strip()), (
            f"data_venda em formato inesperado: {data_venda!r}"
        )

    # placa: se presente, 7 chars alfanum e sem espaços
    placa = out.get("placa")
    if isinstance(placa, str) and placa.strip():
        p = placa.strip().upper().replace("-", "")
        assert re.fullmatch(r"[A-Z0-9]{7}", p), f"placa em formato inesperado: {placa!r}"

    # renavam: se presente, só dígitos e tamanho típico 9-11
    renavam = out.get("renavam")
    if isinstance(renavam, str) and renavam.strip():
        r = _only_digits(renavam.strip())
        assert r == renavam.strip(), f"renavam deve conter apenas dígitos: {renavam!r}"
        assert 9 <= len(r) <= 11, f"renavam tamanho inesperado (9-11): {renavam!r}"

    # chassi: se presente, 17 alfanum (sem espaços) (bem permissivo)
    chassi = out.get("chassi")
    if isinstance(chassi, str) and chassi.strip():
        c = chassi.strip().upper()
        assert re.fullmatch(r"[A-Z0-9]{17}", c), f"chassi em formato inesperado (esperado 17 alfanum): {chassi!r}"

    # valor_venda: não forçar formato monetário; apenas evitar lixo óbvio (se presente)
    valor_venda = out.get("valor_venda")
    if isinstance(valor_venda, str) and valor_venda.strip():
        vv = valor_venda.strip()
        # aceita dígitos com separadores comuns (.,, e espaços). Não aceita letras.
        assert re.fullmatch(r"[0-9\.\,\s]+", vv), f"valor_venda contém caracteres inesperados: {valor_venda!r}"

    # ============================================================
    # Passo 2 — asserts de negócio (vendedor vs comprador, JPEG etc)
    # ============================================================

    vendedor_nome = (out.get("vendedor_nome") or "").strip()
    comprador_nome = (out.get("comprador_nome") or "").strip()
    vendedor_doc = (out.get("vendedor_cpf_cnpj") or "").strip()
    comprador_doc = (out.get("comprador_cpf_cnpj") or "").strip()

    jpeg_like = _is_jpeg_like(fixture_path, out)

    if jpeg_like:
        assert vendedor_nome, "vendedor_nome deve existir e não ser vazio (caso JPEG/image)"
        assert comprador_nome, "comprador_nome deve existir e não ser vazio (caso JPEG/image)"
        assert vendedor_nome != comprador_nome, "vendedor_nome não pode ser igual a comprador_nome (JPEG/image)"

        assert vendedor_doc, "vendedor_cpf_cnpj deve existir e não ser vazio (caso JPEG/image)"
        assert comprador_doc, "comprador_cpf_cnpj deve existir e não ser vazio (caso JPEG/image)"
        assert vendedor_doc != comprador_doc, "vendedor_cpf_cnpj não pode ser igual a comprador_cpf_cnpj (JPEG/image)"
    else:
        if vendedor_nome and comprador_nome:
            assert vendedor_nome != comprador_nome, "vendedor_nome não pode ser igual a comprador_nome"
        if vendedor_doc and comprador_doc:
            assert vendedor_doc != comprador_doc, "vendedor_cpf_cnpj não pode ser igual a comprador_cpf_cnpj"
