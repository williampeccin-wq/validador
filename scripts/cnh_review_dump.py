# scripts/cnh_review_dump.py
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from orchestrator.phase1 import start_case, collect_document


ROOT = Path(__file__).resolve().parents[1]
FIX_DIR = ROOT / "tests" / "fixtures" / "cnh"
OUT_DIR = ROOT / "artifacts" / "cnh_review"


@dataclass
class CnhReviewItem:
    filename: str
    pdf_path: str
    raw_len: int
    parse_error: Any
    extractor_debug: Any
    data: dict


def _safe(obj: Any) -> Any:
    # garante JSON serializável
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return repr(obj)


def main() -> int:
    if not FIX_DIR.exists():
        raise SystemExit(f"Fixtures dir não existe: {FIX_DIR}")

    pdfs = sorted(FIX_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"Nenhum PDF em: {FIX_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cid = start_case()
    items: list[CnhReviewItem] = []

    for pdf in pdfs:
        doc = collect_document(cid, str(pdf), document_type="cnh")
        raw_text = doc.get("raw_text") or ""
        data = doc.get("data") or {}

        item = CnhReviewItem(
            filename=pdf.name,
            pdf_path=str(pdf),
            raw_len=len(raw_text),
            parse_error=_safe(doc.get("parse_error")),
            extractor_debug=_safe(doc.get("extractor_debug")),
            data={
                # foca nos campos que você quer inspecionar
                "nome": data.get("nome"),
                "cpf": data.get("cpf"),
                "categoria": data.get("categoria"),
                "data_nascimento": data.get("data_nascimento"),
                "validade": data.get("validade"),
                "cidade_nascimento": data.get("cidade_nascimento"),
                "uf_nascimento": data.get("uf_nascimento"),
                "filiacao": data.get("filiacao"),
                # se tiver mais campos no futuro, mantém aqui
            },
        )
        items.append(item)

        # dump por-PDF
        per_pdf_out = OUT_DIR / f"{pdf.stem}.json"
        per_pdf_out.write_text(
            json.dumps(asdict(item), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # snippet do OCR (pra “sanity check” visual)
        snippet_len = int(os.getenv("CNH_SNIPPET_LEN", "1200"))
        snippet = raw_text[:snippet_len]
        (OUT_DIR / f"{pdf.stem}.raw_snippet.txt").write_text(
            snippet, encoding="utf-8"
        )

        print(
            f"{pdf.name:40} raw_len={item.raw_len:5d} "
            f"nome={bool(item.data.get('nome'))} cpf={bool(item.data.get('cpf'))} "
            f"cat={bool(item.data.get('categoria'))} nasc={bool(item.data.get('data_nascimento'))} "
            f"val={bool(item.data.get('validade'))} filiacao_len={len(item.data.get('filiacao') or [])}"
        )

    # índice consolidado
    index_out = OUT_DIR / "index.json"
    index_out.write_text(
        json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\ncase_id:", cid)
    print("wrote:", OUT_DIR)
    print("index:", index_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
