# tests/test_phase2_master_report_meta_contract.py

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

from validators.phase2.master_report import build_master_report


SCHEMA_VERSION = "phase2.master_report@1"
GATE1_REQUIRED = ["proposta_daycoval", "cnh"]

FORBIDDEN_KEYS = {
    "cpf",
    "cnpj",
    "rg",
    "nome",
    "address",
    "endereco",
    "pix",
    "transactions",
    "transacoes",
    "ocr",
    "payload",
}


def _mk_case_id() -> str:
    return str(uuid.uuid4())


def _write_phase1_doc(
    phase1_root: Path,
    doc_type: str,
    filename: str,
    data: Dict[str, Any],
) -> None:
    out_dir = phase1_root / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _parse_utc(dt: str) -> None:
    if dt.endswith("Z"):
        dt = dt[:-1] + "+00:00"
    parsed = datetime.fromisoformat(dt)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def _assert_no_payload(meta: Dict[str, Any]) -> None:
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in FORBIDDEN_KEYS
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str):
            low = obj.lower()
            for bad in FORBIDDEN_KEYS:
                assert bad not in low

    walk(meta)


@pytest.mark.parametrize(
    "scenario,docs,gate1_status",
    [
        ("empty_phase1", [], "FAIL"),
        ("gate1_minimal", ["proposta_daycoval", "cnh"], "PASS"),
        ("income_only", ["comprovante_renda"], "FAIL"),
    ],
)
def test_phase2_master_report_meta_contract(
    tmp_path: Path,
    scenario: str,
    docs: list[str],
    gate1_status: str,
) -> None:
    case_id = _mk_case_id()

    phase1_root = tmp_path / "storage" / "phase1" / case_id
    phase2_root = tmp_path / "storage" / "phase2" / case_id

    for i, doc in enumerate(docs):
        _write_phase1_doc(
            phase1_root,
            doc,
            f"{i:03d}.json",
            {"document_type": doc, "data": {}},
        )

    report = build_master_report(
        case_id=case_id,
        phase1_root=phase1_root,
        phase2_root=phase2_root,
    )

    assert "meta" in report
    meta = report["meta"]

    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["phase"] == "phase2"

    uuid.UUID(meta["case_id"])
    _parse_utc(meta["generated_at"])

    assert meta["inputs"]["phase1"]["gate1"]["required"] == GATE1_REQUIRED
    assert meta["inputs"]["phase1"]["gate1"]["status"] == gate1_status

    for path_key in ("phase1_root", "phase2_root"):
        p = meta["source_layout"][path_key]
        assert not p.startswith("/")
        assert "Users" not in p

    assert meta["privacy"]["contains_pii"] is False

    _assert_no_payload(meta)
