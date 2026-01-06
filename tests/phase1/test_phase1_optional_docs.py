# tests/phase1/test_phase1_optional_docs.py
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orchestrator.phase1 import (
    DocumentType,
    collect_document,
    gate1_is_ready,
    start_case,
)


@pytest.fixture()
def temp_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Isola storage para os testes sem mudar a estrutura lógica:
    storage/phase1/<case_id>/<document_type>/<doc_id>.json
    """
    root = tmp_path / "storage" / "phase1"
    monkeypatch.setenv("PHASE1_STORAGE_ROOT", str(root))
    return root


def _write_dummy_file(tmp_path: Path, name: str, content: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_gate1_intacto_sem_opcionais(temp_storage_root: Path, tmp_path: Path) -> None:
    """
    Garantia mínima: coletar documentos opcionais NÃO habilita Gate 1.
    """
    case_id = start_case()

    holerite = _write_dummy_file(tmp_path, "holerite.pdf", b"%PDF-1.4\nDUMMY HOLERITE\n")
    folha = _write_dummy_file(tmp_path, "folha.pdf", b"%PDF-1.4\nDUMMY FOLHA\n")
    extrato = _write_dummy_file(tmp_path, "extrato.pdf", b"%PDF-1.4\nDUMMY EXTRATO\n")

    collect_document(case_id, holerite, document_type=DocumentType.HOLERITE)
    collect_document(case_id, folha, document_type=DocumentType.FOLHA_PAGAMENTO)
    collect_document(case_id, extrato, document_type=DocumentType.EXTRATO_BANCARIO)

    assert gate1_is_ready(case_id) is False


def test_persistencia_jsons_opcionais_na_estrutura(temp_storage_root: Path, tmp_path: Path) -> None:
    """
    Garante que:
    - não quebra fluxo (sem exception)
    - persiste em storage/phase1/<case_id>/<document_type>/<doc_id>.json
    - JSON contém raw.sha256 e raw.content_b64
    """
    case_id = start_case()

    holerite = _write_dummy_file(tmp_path, "holerite.pdf", b"%PDF-1.4\nDUMMY HOLERITE\n")

    doc = collect_document(case_id, holerite, document_type="holerite")
    doc_id = doc["doc_id"]

    out_path = temp_storage_root / case_id / "holerite" / f"{doc_id}.json"
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["case_id"] == case_id
    assert payload["document_type"] == "holerite"
    assert payload["raw"]["filename"] == "holerite.pdf"
    assert isinstance(payload["raw"]["sha256"], str) and len(payload["raw"]["sha256"]) == 64
    assert isinstance(payload["raw"]["content_b64"], str) and len(payload["raw"]["content_b64"]) > 0


def test_gate1_ok_com_proposta_e_cnh_e_opcionais_nao_atrapalham(
    temp_storage_root: Path, tmp_path: Path
) -> None:
    """
    Garante que adicionar opcionais não quebra Gate 1 e que Gate 1 continua
    dependendo apenas de Proposta+CNH.
    """
    case_id = start_case()

    # 1) antes: não está pronto
    assert gate1_is_ready(case_id) is False

    # 2) coleta opcionais
    extrato = _write_dummy_file(tmp_path, "extrato.pdf", b"%PDF-1.4\nDUMMY EXTRATO\n")
    collect_document(case_id, extrato, document_type=DocumentType.EXTRATO_BANCARIO)
    assert gate1_is_ready(case_id) is False

    # 3) coleta Gate 1 (arquivos dummy; parser pode falhar, mas persistência existe e Gate 1 é por presença)
    proposta = _write_dummy_file(tmp_path, "proposta.pdf", b"%PDF-1.4\nDUMMY PROPOSTA\n")
    cnh = _write_dummy_file(tmp_path, "cnh.pdf", b"%PDF-1.4\nDUMMY CNH\n")

    collect_document(case_id, proposta, document_type=DocumentType.PROPOSTA_DAYCOVAL)
    assert gate1_is_ready(case_id) is False

    collect_document(case_id, cnh, document_type=DocumentType.CNH)
    assert gate1_is_ready(case_id) is True

    # Sanity: arquivos existem na estrutura esperada
    assert (temp_storage_root / case_id / "proposta_daycoval").exists()
    assert (temp_storage_root / case_id / "cnh").exists()
    assert (temp_storage_root / case_id / "extrato_bancario").exists()
