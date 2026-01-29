from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from orchestrator.phase1 import start_case, collect_document


FIXTURES_DIR = Path("tests/fixtures/cnh")
CONTRACTS_DIR = Path("tests/contracts/cnh")


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _is_plausible_name(s: str) -> bool:
    if not s:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    toks = s.split()
    return len(toks) >= 2


def _is_plausible_filiacao_line(s: str) -> bool:
    if not s:
        return False
    toks = s.split()
    if len(toks) < 2:
        return False
    # anti-lixo: precisa ter pelo menos 2 tokens com vogal
    vowel = re.compile(r"[AEIOUÁÉÍÓÚÀ-Ü]")
    vt = sum(1 for t in toks if vowel.search(t))
    return vt >= 2


@pytest.mark.smoke
def test_cnh_contracts_all_fixtures_end_to_end():
    assert FIXTURES_DIR.exists(), f"Missing fixtures dir: {FIXTURES_DIR}"
    assert CONTRACTS_DIR.exists(), f"Missing contracts dir: {CONTRACTS_DIR}"

    pdfs = sorted(FIXTURES_DIR.glob("*.pdf"))
    assert pdfs, f"No PDFs found in {FIXTURES_DIR}"

    cid = start_case()

    failures = []

    for pdf in pdfs:
        contract_path = CONTRACTS_DIR / (pdf.stem + ".json")
        if not contract_path.exists():
            failures.append(f"[{pdf.name}] missing contract: {contract_path}")
            continue

        contract = _load_json(contract_path)

        doc = collect_document(cid, str(pdf), document_type="cnh")
        data = doc.get("data") or {}
        dbg = doc.get("extractor_debug") or {}

        # Base invariants (não negocia)
        if not _is_plausible_name(data.get("nome") or ""):
            failures.append(f"[{pdf.name}] nome inválido: {data.get('nome')!r}")

        if not (data.get("cpf") and len(data.get("cpf")) == 11 and data.get("cpf").isdigit()):
            failures.append(f"[{pdf.name}] cpf inválido: {data.get('cpf')!r}")

        if not (data.get("validade") and re.match(r"^\d{2}/\d{2}/\d{4}$", data.get("validade"))):
            failures.append(f"[{pdf.name}] validade inválida: {data.get('validade')!r}")

        if not (data.get("data_nascimento") and re.match(r"^\d{2}/\d{2}/\d{4}$", data.get("data_nascimento"))):
            failures.append(f"[{pdf.name}] data_nascimento inválida: {data.get('data_nascimento')!r}")

        if not (data.get("categoria") and data.get("categoria") in {"A", "B", "C", "D", "E", "AB", "AC", "AD", "AE"}):
            failures.append(f"[{pdf.name}] categoria inválida: {data.get('categoria')!r}")

        filiacao = data.get("filiacao") or []
        if any(not _is_plausible_filiacao_line(x) for x in filiacao):
            failures.append(f"[{pdf.name}] filiacao com linha suspeita: {filiacao!r}")

        # Contract: expect (igualdade)
        for k, v in (contract.get("expect") or {}).items():
            if data.get(k) != v:
                failures.append(f"[{pdf.name}] expect.{k}: got={data.get(k)!r} want={v!r}")

        # Contract: forbid
        forbid = contract.get("forbid") or {}
        suffix = forbid.get("nome_suffix_tokens") or []
        if suffix:
            toks = (data.get("nome") or "").split()
            for bad in suffix:
                if toks and toks[-1] == bad:
                    failures.append(f"[{pdf.name}] forbid.nome_suffix_tokens: got nome={data.get('nome')!r}")

        # Contract: contains
        contains = contract.get("contains") or {}
        nome_all = contains.get("nome_all") or []
        for tok in nome_all:
            if tok not in (data.get("nome") or ""):
                failures.append(f"[{pdf.name}] contains.nome_all missing token={tok!r} nome={data.get('nome')!r}")

        filiacao_any = contains.get("filiacao_any") or []
        for tok in filiacao_any:
            if not any(tok in x for x in filiacao):
                failures.append(f"[{pdf.name}] contains.filiacao_any missing token={tok!r} filiacao={filiacao!r}")

        # Contract: min
        minc = contract.get("min") or {}
        min_fil = minc.get("filiacao_len_at_least")
        if isinstance(min_fil, int):
            if len(filiacao) < min_fil:
                failures.append(f"[{pdf.name}] min.filiacao_len_at_least: got={len(filiacao)} want>={min_fil}")

        # Extra: log útil (se falhar)
        if failures and dbg:
            # não explode output; só deixa rastro quando falhar.
            pass

    assert not failures, "CNH contracts failed:\n" + "\n".join(failures)
