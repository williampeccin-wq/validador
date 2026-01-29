from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.phase1 import start_case, collect_document


FIXTURES_DIR = Path("tests/fixtures/cnh")
OUT_DIR = Path("reports")
OUT_MD = OUT_DIR / "cnh_audit.md"
OUT_JSON = OUT_DIR / "cnh_audit.json"


_ALLOWED_CAT = {"A", "B", "C", "D", "E", "AB", "AC", "AD", "AE"}


def _is_date(s: Optional[str]) -> bool:
    return bool(s and re.match(r"^\d{2}/\d{2}/\d{4}$", s))


def _year(d: str) -> int:
    return int(d.split("/")[-1])


def _warn(data: Dict[str, Any], dbg: Dict[str, Any]) -> List[str]:
    w: List[str] = []

    nome = data.get("nome")
    cpf = data.get("cpf")
    cat = data.get("categoria")
    dob = data.get("data_nascimento")
    val = data.get("validade")
    filiacao = data.get("filiacao") or []

    if not nome or len(str(nome).split()) < 2:
        w.append("NOME: vazio/curto")

    if not (cpf and len(cpf) == 11 and str(cpf).isdigit()):
        w.append("CPF: inválido")

    if cat not in _ALLOWED_CAT:
        w.append(f"CATEGORIA: inválida ({cat!r})")

    if not _is_date(dob):
        w.append(f"NASCIMENTO: inválido ({dob!r})")

    if not _is_date(val):
        w.append(f"VALIDADE: inválido ({val!r})")

    # DOB plausível: não pode ser perto da validade (anti “data de 1a habilitação”)
    if _is_date(dob) and _is_date(val):
        if _year(dob) >= _year(val) - 14:
            w.append(f"NASCIMENTO: suspeito (dob={dob} ~ validade={val})")

    # Filiação: pelo menos 1; ideal 2
    if len(filiacao) == 0:
        w.append("FILIAÇÃO: vazia")
    elif len(filiacao) == 1:
        w.append("FILIAÇÃO: só 1 linha (ideal 2)")

    # Linhas suspeitas na filiação
    vowel = re.compile(r"[AEIOUÁÉÍÓÚÀ-Ü]")
    for x in filiacao:
        toks = str(x).split()
        vt = sum(1 for t in toks if vowel.search(t))
        if len(toks) < 2 or vt < 2:
            w.append(f"FILIAÇÃO: linha suspeita ({x!r})")

    # Nome com sufixo típico lixo
    if nome and str(nome).split()[-1] in {"EM"}:
        w.append(f"NOME: sufixo lixo ({nome!r})")

    # low_signal do selector
    chosen = ((dbg.get("chosen") or {}) if isinstance(dbg, dict) else {})
    if chosen and chosen.get("text_len", 0) < 1200:
        w.append(f"OCR: text_len baixo (chosen.text_len={chosen.get('text_len')})")

    return w


def main() -> None:
    assert FIXTURES_DIR.exists(), f"Missing fixtures dir: {FIXTURES_DIR}"
    pdfs = sorted(FIXTURES_DIR.glob("*.pdf"))
    assert pdfs, f"No PDFs in {FIXTURES_DIR}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cid = start_case()

    rows: List[Dict[str, Any]] = []
    md: List[str] = []
    md.append("# CNH — Auditoria por PDF\n")

    for pdf in pdfs:
        doc = collect_document(cid, str(pdf), document_type="cnh")
        data = doc.get("data") or {}
        dbg = doc.get("extractor_debug") or {}

        warnings = _warn(data, (dbg.get("chosen") or {}) if isinstance(dbg, dict) else {})
        rows.append(
            {
                "filename": pdf.name,
                "data": data,
                "extractor_debug": dbg,
                "warnings": warnings,
            }
        )

        md.append(f"## {pdf.name}\n")
        md.append("### Campos extraídos\n")
        md.append("```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```\n")
        md.append("### Warnings\n")
        if warnings:
            for w in warnings:
                md.append(f"- {w}\n")
        else:
            md.append("- (nenhum)\n")
        md.append("\n### Selector (chosen)\n")
        chosen = (dbg.get("chosen") or {}) if isinstance(dbg, dict) else {}
        md.append("```json\n" + json.dumps(chosen, ensure_ascii=False, indent=2) + "\n```\n")

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text("".join(md), encoding="utf-8")

    print(f"Wrote: {OUT_MD}")
    print(f"Wrote: {OUT_JSON}")


if __name__ == "__main__":
    main()
