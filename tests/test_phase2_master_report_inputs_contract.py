import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest


# Inputs we consider "known" / first-class in Phase 2 master report.
# The contract allows additional keys (future docs), but these are the baseline ones.
BASELINE_INPUT_KEYS = {
    "proposta_daycoval",
    "cnh",
    "holerite",
    "extrato_bancario",
}


# Contract: inputs must NOT leak extracted data / payload content. Only metadata is allowed.
# We enforce a strict allowlist for each input object.
ALLOWED_INPUT_FIELDS = {"path"}

# Contract: disallowed fields that often indicate leakage
DISALLOWED_INPUT_FIELDS = {
    "data",
    "payload",
    "content",
    "text",
    "raw_text",
    "native_text",
    "ocr_text",
    "fields",
    "parsed",
    "extracted",
    "document",
    "doc",
}


def _write_phase1_doc(
    phase1_root: Path, case_id: str, doc_type: str, filename: str, data: Dict[str, Any]
) -> Path:
    """
    Minimal Phase 1 fixture writer that matches the convention:
      storage/phase1/<case_id>/<doc_type>/<filename>.json
    Payload shape uses {"data": ...}.
    """
    out_dir = phase1_root / case_id / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / filename
    payload = {"data": data}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _load_report_json(phase2_root: Path, case_id: str) -> Dict[str, Any]:
    p = phase2_root / case_id / "report.json"
    assert p.exists(), f"Expected report.json at {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _assert_is_path_like(value: Any) -> None:
    """
    Contract: path can be a string path. We allow empty string (defensive),
    but prefer a non-empty string when an input exists.
    """
    assert isinstance(value, str), f"inputs.<key>.path must be str, got={type(value)}"


def _assert_input_obj_contract(key: str, obj: Any) -> None:
    """
    Contract:
      - inputs[key] is an object
      - contains only allowed fields (ALLOWED_INPUT_FIELDS)
      - MUST NOT contain content/data (DISALLOWED_INPUT_FIELDS)
      - when present, 'path' is a string
    """
    assert isinstance(obj, dict), f"inputs['{key}'] must be an object, got={type(obj)}"

    # No disallowed fields
    for bad in DISALLOWED_INPUT_FIELDS:
        assert bad not in obj, f"inputs['{key}'] must not contain '{bad}' (data leakage)"

    # Strict allowlist: only 'path' is permitted for now
    extra = set(obj.keys()) - ALLOWED_INPUT_FIELDS
    assert not extra, f"inputs['{key}'] contains unexpected keys: {sorted(extra)}; allowed={sorted(ALLOWED_INPUT_FIELDS)}"

    # If path exists, it must be a string (can be empty but should not be None)
    if "path" in obj:
        _assert_is_path_like(obj["path"])


def _assert_inputs_contract(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Root contract:
      - inputs must exist
      - inputs is an object/dict
      - each inputs[k] respects _assert_input_obj_contract
    """
    assert "inputs" in payload, "report root must include 'inputs'"
    assert isinstance(payload["inputs"], dict), f"inputs must be an object, got={type(payload['inputs'])}"

    inputs = payload["inputs"]
    for k, v in inputs.items():
        assert isinstance(k, str) and k.strip(), f"inputs keys must be non-empty str; got={k!r}"
        _assert_input_obj_contract(k, v)

    return inputs


@pytest.mark.parametrize(
    "case_name, phase1_docs",
    [
        # No Phase 1 docs: still must emit report.json with inputs present (likely empty dict).
        ("empty_phase1", []),
        # Proposta only: inputs must include proposta_daycoval with path-like value.
        ("proposta_only", [("proposta_daycoval", "p1.json", {"nome_financiado": "JOAO", "salario": "R$ 2500,00"})]),
        # Proposta + CNH: both should be present in inputs with path fields only.
        (
            "proposta_cnh",
            [
                ("proposta_daycoval", "p1.json", {"nome_financiado": "JOAO DA SILVA", "data_nascimento": "01/01/1990"}),
                ("cnh", "c1.json", {"nome": "JOAO SILVA", "data_nascimento": "01/01/1990"}),
            ],
        ),
        # Holerite alias behavior depends on implementation; we still enforce NO data leakage if it appears.
        ("holerite_only", [("holerite", "h1.json", {"total_vencimentos": "R$ 3200,00"})]),
        ("extrato_only", [("extrato_bancario", "e1.json", {"renda_apurada": "R$ 4100,00"})]),
    ],
)
def test_phase2_master_report_inputs_contract(tmp_path: Path, case_name: str, phase1_docs: List[Tuple[str, str, Dict[str, Any]]]) -> None:
    """
    Contract for master_report.inputs:
      - present at root
      - dictionary mapping doc_type -> { path: str }
      - strictly metadata only (no extracted data)
    """
    phase1_root = tmp_path / "storage" / "phase1"
    phase2_root = tmp_path / "storage" / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = f"case_inputs_{case_name}"

    # Arrange Phase 1 fixtures
    for doc_type, filename, data in phase1_docs:
        _write_phase1_doc(phase1_root, case_id, doc_type, filename, data)

    # Act: build report
    from validators.phase2.master_report import build_master_report  # local import

    build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    payload = _load_report_json(phase2_root, case_id)

    inputs = _assert_inputs_contract(payload)

    # Additional expectations (soft): if baseline docs exist, inputs should reference them by key.
    phase1_doc_types = {t for (t, _, _) in phase1_docs}

    if "proposta_daycoval" in phase1_doc_types:
        assert "proposta_daycoval" in inputs, "inputs should include proposta_daycoval when phase1 has it"
        assert "path" in inputs["proposta_daycoval"], "inputs.proposta_daycoval must contain 'path'"

    if "cnh" in phase1_doc_types:
        assert "cnh" in inputs, "inputs should include cnh when phase1 has it"
        assert "path" in inputs["cnh"], "inputs.cnh must contain 'path'"

    if "extrato_bancario" in phase1_doc_types:
        assert "extrato_bancario" in inputs, "inputs should include extrato_bancario when phase1 has it"
        assert "path" in inputs["extrato_bancario"], "inputs.extrato_bancario must contain 'path'"

    # Holerite can be stored under aliases; we do not force exact key presence here.
    # If it appears, it must comply with the strict metadata-only contract (already checked).


def test_phase2_master_report_inputs_allow_future_keys_but_keep_metadata_only(tmp_path: Path) -> None:
    """
    Contract: inputs may grow to include future documents, but every entry must remain metadata-only.
    This test creates a scenario where Phase 1 has an unknown doc_type and asserts that if Phase 2
    includes it, it still must obey the allowlist contract.
    """
    phase1_root = tmp_path / "storage" / "phase1"
    phase2_root = tmp_path / "storage" / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = "case_inputs_future_keys"

    # Unknown doc type
    _write_phase1_doc(phase1_root, case_id, "novo_documento_x", "x1.json", {"segredo": "NAO_VAZAR"})

    from validators.phase2.master_report import build_master_report  # local import

    build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    payload = _load_report_json(phase2_root, case_id)

    inputs = _assert_inputs_contract(payload)

    # We do NOT require the unknown key to appear — that's implementation-specific.
    # If it does appear, it must be metadata-only (already enforced).
    if "novo_documento_x" in inputs:
        _assert_input_obj_contract("novo_documento_x", inputs["novo_documento_x"])


def test_phase2_master_report_inputs_baseline_keys_are_not_required_when_absent(tmp_path: Path) -> None:
    """
    Contract: baseline keys are NOT required to exist when Phase 1 doesn't have those documents.
    However, 'inputs' object itself must exist.
    """
    phase1_root = tmp_path / "storage" / "phase1"
    phase2_root = tmp_path / "storage" / "phase2"
    phase1_root.mkdir(parents=True, exist_ok=True)
    phase2_root.mkdir(parents=True, exist_ok=True)

    case_id = "case_inputs_baseline_absent"

    from validators.phase2.master_report import build_master_report  # local import

    build_master_report(case_id, phase1_root=str(phase1_root), phase2_root=str(phase2_root))
    payload = _load_report_json(phase2_root, case_id)

    inputs = _assert_inputs_contract(payload)

    # Explicitly allow empty inputs
    assert isinstance(inputs, dict)
    # Not asserting baseline key presence here by contract.
