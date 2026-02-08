from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

from parsers.cnh_fields.nome import extract_nome


@pytest.mark.parametrize(
    "raw_text, expected, method",
    [
        (
            # MRZ típico: SOBRENOME<<PRENOMES (retornamos PRENOMES SOBRENOME)
            "I<BRA<<<<<<<<<<<<<<<<<<<<\nSANTOSDEBARROS<<ANDERSON<<<<<<<<<<<<<<<<<\n1234567890BRA\n",
            "ANDERSON SANTOSDEBARROS",
            "mrz",
        ),
        (
            # MRZ com '<' internos separando múltiplos prenomes
            "P<BRA<<<<<<<<<<<<<<<<<<<<\nSILVA<<JOAO<MARCELO<<<<<<<<<<<<<<<<<<<<\n",
            "JOAO SILVA",
            "mrz",
        ),
        (
            # Label inline
            "NOME / NAME: ANDERSON SANTOS DE BARROS\nCPF 123.456.789-00\n",
            "ANDERSON SANTOS DE BARROS",
            "label",
        ),
        (
            # Label na linha e valor na próxima
            "NOME / NAME\nANDERSON SANTOS DE BARROS\nFILIAÇÃO\nMAE FULANA\n",
            "ANDERSON SANTOS DE BARROS",
            "label",
        ),
        (
            # Evitar header como nome
            "REPUBLICA FEDERATIVA DO BRASIL\nCARTEIRA NACIONAL DE HABILITACAO\nNOME / NAME\nANDERSON SANTOS DE BARROS\n",
            "ANDERSON SANTOS DE BARROS",
            "label",
        ),
        (
            # Se só houver header e nada de nome válido
            "REPUBLICA FEDERATIVA DO BRASIL\nCARTEIRA NACIONAL DE HABILITACAO\n",
            None,
            "none",
        ),
    ],
)
def test_extract_nome_unit_cases(raw_text: str, expected: str | None, method: str):
    nome, dbg = extract_nome(raw_text)
    assert nome == expected
    assert dbg["method"] == method


@pytest.mark.slow
def test_extract_nome_smoke_pdfs_has_no_header_leak():
    """
    Smoke determinístico com PDFs reais: garante que:
      - não retorna None (quando possível)
      - não retorna headers/campos
    Não valida o nome exato (isso depende do dataset/fixtures), apenas sanidade.
    """
    pdfs = sorted(glob.glob("tests/fixtures/cnh/*.pdf"))
    if not pdfs:
        pytest.skip("Sem PDFs em tests/fixtures/cnh/*.pdf")

    # Import local para evitar custo se skipar
    from orchestrator.phase1 import start_case, collect_document

    bad = []
    for pdf in pdfs:
        case_id = start_case()
        doc = collect_document(case_id, pdf, document_type="cnh")
        raw_text = (doc or {}).get("raw_text") or ""
        nome, dbg = extract_nome(raw_text)

        if not nome:
            bad.append((os.path.basename(pdf), "none", dbg))
            continue

        up = nome.upper()
        if "REPUBLICA" in up or "CARTEIRA" in up or "HABILITAC" in up or "FILIA" in up:
            bad.append((os.path.basename(pdf), "leaked_header_or_field", dbg))

        # sanity: pelo menos 2 tokens e tamanho mínimo
        if len(nome.split()) < 2 or len(nome) < 8:
            bad.append((os.path.basename(pdf), "too_short", dbg))

    assert not bad, f"Falhas em {len(bad)} PDFs: {bad[:3]}"
