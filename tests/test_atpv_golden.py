# tests/test_atpv_golden.py
from __future__ import annotations

import json
import os
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

    # ===========================
    # Passo 2 — asserts adicionais
    # ===========================

    vendedor_nome = (out.get("vendedor_nome") or "").strip()
    comprador_nome = (out.get("comprador_nome") or "").strip()
    vendedor_doc = (out.get("vendedor_cpf_cnpj") or "").strip()
    comprador_doc = (out.get("comprador_cpf_cnpj") or "").strip()

    uf = (out.get("uf") or "").strip().upper()
    municipio = (out.get("municipio") or "").strip()

    jpeg_like = _is_jpeg_like(fixture_path, out)

    # (JPEG) — endurecer apenas quando o input é imagem/scan
    if jpeg_like:
        assert vendedor_nome, "vendedor_nome deve existir e não ser vazio (caso JPEG/image)"
        assert comprador_nome, "comprador_nome deve existir e não ser vazio (caso JPEG/image)"
        assert vendedor_nome != comprador_nome, "vendedor_nome não pode ser igual a comprador_nome (JPEG/image)"

        assert vendedor_doc, "vendedor_cpf_cnpj deve existir e não ser vazio (caso JPEG/image)"
        assert comprador_doc, "comprador_cpf_cnpj deve existir e não ser vazio (caso JPEG/image)"
        assert vendedor_doc != comprador_doc, "vendedor_cpf_cnpj não pode ser igual a comprador_cpf_cnpj (JPEG/image)"
    else:
        # Para PDF com texto nativo, não exigimos presença; mas se ambos existirem, não podem ser iguais.
        if vendedor_nome and comprador_nome:
            assert vendedor_nome != comprador_nome, "vendedor_nome não pode ser igual a comprador_nome"
        if vendedor_doc and comprador_doc:
            assert vendedor_doc != comprador_doc, "vendedor_cpf_cnpj não pode ser igual a comprador_cpf_cnpj"

    # UF válida e não nula (sempre)
    assert uf, "uf não pode ser nula/vazia"
    assert uf in UF_BR_VALIDAS, f"uf inválida: {uf!r}"

    # Município saneado (não começar com 'UR ') (sempre)
    assert municipio, "municipio não pode ser nulo/vazio"
    assert not municipio.upper().startswith("UR "), f"municipio parece não-saneado (prefixo 'UR '): {municipio!r}"
