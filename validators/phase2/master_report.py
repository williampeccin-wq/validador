# validators/phase2/master_report.py
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from validators.phase2.proposta_cnh_senatran_validator import build_proposta_cnh_senatran_checks
from validators.phase2.atpv_validator import build_atpv_checks
from validators.phase2.detran_validator import build_detran_checks

# MUST match tests/test_phase2_master_report_meta_contract.py::SCHEMA_VERSION
SCHEMA_VERSION = "phase2.master_report@1"

# Gate1 contract (Phase 1 required docs)
GATE1_REQUIRED = ["proposta_daycoval", "cnh"]

# Status precedence: worst -> best
_STATUS_ORDER = ["FAIL", "MISSING", "WARN", "OK"]
_STATUS_RANK = {s: i for i, s in enumerate(_STATUS_ORDER)}


def _utc_now_rfc3339() -> str:
    # timezone-aware UTC timestamp (avoid datetime.utcnow())
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_read_json(p: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def _coerce_path(p: Union[str, Path]) -> Path:
    return p if isinstance(p, Path) else Path(p)


def _sanitize_path_for_meta(p: Path) -> str:
    """
    Contract: meta must not leak absolute paths.
    - remove leading '/' if absolute
    - drop obvious user-home segments
    """
    s = str(p).replace("\\", "/")
    s = s.lstrip("/")
    s = re.sub(r"(^|/)Users/[^/]+/", r"\1", s)
    return s


def _looks_like_phase1_case_root(p: Path) -> bool:
    """
    Heuristic: a Phase1 "case root" typically contains doc_type directories.
    We keep this conservative to avoid mis-detecting.
    """
    if not p.exists() or not p.is_dir():
        return False
    # Common Phase1 doc_type dirs:
    for d in (
        "proposta_daycoval",
        "cnh",
        "cnh_senatran",
        "holerite",
        "extrato_bancario",
        "comprovante_renda",
    ):
        if (p / d).exists():
            return True
    return False


def _resolve_phase1_case_root(phase1_root: Path, case_id: str) -> Path:
    """
    Accepts either:
      - phase1_root = <...>/phase1           (root)  -> returns <...>/phase1/<case_id>
      - phase1_root = <...>/phase1/<case_id> (case) -> returns itself
    """
    if phase1_root.name == case_id:
        return phase1_root
    if _looks_like_phase1_case_root(phase1_root):
        return phase1_root
    return phase1_root / case_id


def _resolve_phase2_case_root(phase2_root: Path, case_id: str) -> Path:
    """
    Accepts either:
      - phase2_root = <...>/phase2           (root)  -> returns <...>/phase2/<case_id>
      - phase2_root = <...>/phase2/<case_id> (case) -> returns itself
    """
    if phase2_root.name == case_id:
        return phase2_root
    return phase2_root / case_id


def _list_phase1_presence(phase1_case_root: Path) -> Dict[str, Dict[str, Any]]:
    """
    Returns: presence[doc_type] = {present: bool, count: int, path: str, latest_json: Optional[str]}
    Metadata-only. No payload.
    """
    presence: Dict[str, Dict[str, Any]] = {}

    if not phase1_case_root.exists():
        return presence

    for doc_type_dir in sorted([p for p in phase1_case_root.iterdir() if p.is_dir()]):
        jsons = sorted(doc_type_dir.glob("*.json"))
        presence[doc_type_dir.name] = {
            "present": bool(jsons),
            "count": int(len(jsons)),
            "path": str(doc_type_dir),
            "latest_json": str(jsons[-1]) if jsons else None,
        }

    return presence


def _gate1_status(presence: Dict[str, Dict[str, Any]]) -> str:
    for req in GATE1_REQUIRED:
        meta = presence.get(req) or {}
        if not bool(meta.get("present")):
            return "FAIL"
    return "PASS"


def _parse_money_any(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)

    s = str(v).strip()
    if not s:
        return None

    s = s.replace("R$", "").replace(" ", "")

    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")

    s = re.sub(r"[^0-9.\-]", "", s)
    if not s or s in ("-", ".", "-."):
        return None

    try:
        return float(s)
    except Exception:
        return None


def _read_phase1_latest_data(phase1_case_root: Path, doc_type: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    d = phase1_case_root / doc_type
    if not d.exists() or not d.is_dir():
        return None, None
    jsons = sorted(d.glob("*.json"))
    if not jsons:
        return None, None

    raw, err = _safe_read_json(jsons[-1])
    if err or not isinstance(raw, dict):
        return None, err or "invalid_json"
    data = raw.get("data")
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "data_not_dict"
    return data, None


def _compute_overall_status(checks: List[Dict[str, Any]]) -> str:
    if not checks:
        return "MISSING"

    worst = "OK"
    for c in checks:
        st = str(c.get("status") or "OK")
        if st not in _STATUS_RANK:
            st = "WARN"
        if _STATUS_RANK[st] < _STATUS_RANK[worst]:
            worst = st
    return worst


def _mk_check(*, check_id: str, status: str, message: str, evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": check_id, "status": status, "message": message, "evidence": evidence or {}}


def _build_inputs_root_metadata_only(*, phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """
    Root-level 'inputs' contract (metadata-only):
      inputs[doc_type] = {"path": "<sanitized path>"}
    """
    out: Dict[str, Dict[str, str]] = {}

    for doc_type, meta in presence.items():
        latest_json = meta.get("latest_json")
        if latest_json:
            out[doc_type] = {"path": _sanitize_path_for_meta(Path(latest_json))}
        else:
            out[doc_type] = {"path": _sanitize_path_for_meta(phase1_case_root / doc_type)}

    return out


def _build_meta(*, case_id: str, phase1_root: Path, phase2_root: Path, presence: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    inputs_docs: Dict[str, Dict[str, Any]] = {}
    for doc_type, meta in presence.items():
        inputs_docs[doc_type] = {"present": bool(meta.get("present")), "count": int(meta.get("count", 0))}

    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "phase2",
        "case_id": case_id,
        "generated_at": _utc_now_rfc3339(),
        "inputs": {
            "phase1": {
                "gate1": {"required": list(GATE1_REQUIRED), "status": _gate1_status(presence)},
                "docs": inputs_docs,
            }
        },
        "source_layout": {
            "phase1_root": _sanitize_path_for_meta(phase1_root),
            "phase2_root": _sanitize_path_for_meta(phase2_root),
        },
        "privacy": {
            "contains_pii": False,
            # IMPORTANT: tests ban forbidden substrings like "payload"
            "notes": "meta contains only structural and operational metadata; no extracted personal fields",
        },
    }


def _build_identity_check(phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    has_proposta = bool((presence.get("proposta_daycoval") or {}).get("present"))
    has_cnh = bool((presence.get("cnh") or {}).get("present"))

    if not has_proposta and not has_cnh:
        return _mk_check(
            check_id="identity.proposta_vs_cnh",
            status="MISSING",
            message="Missing proposta_daycoval and cnh",
            evidence={"required": ["proposta_daycoval", "cnh"]},
        )

    if not has_proposta or not has_cnh:
        missing = []
        if not has_proposta:
            missing.append("proposta_daycoval")
        if not has_cnh:
            missing.append("cnh")
        return _mk_check(
            check_id="identity.proposta_vs_cnh",
            status="MISSING",
            message=f"Missing required docs: {', '.join(missing)}",
            evidence={"required": ["proposta_daycoval", "cnh"], "missing": missing},
        )

    proposta, _ = _read_phase1_latest_data(phase1_case_root, "proposta_daycoval")
    cnh, _ = _read_phase1_latest_data(phase1_case_root, "cnh")
    proposta = proposta or {}
    cnh = cnh or {}

    def norm(x: Any) -> Optional[str]:
        if x is None:
            return None
        s = str(x).strip()
        return s.upper() if s else None

    proposta_nome = norm(proposta.get("nome_financiado") or proposta.get("nome"))
    cnh_nome = norm(cnh.get("nome"))
    proposta_dn = norm(proposta.get("data_nascimento"))
    cnh_dn = norm(cnh.get("data_nascimento"))

    # IMPORTANT: não marcar OK se não houver campos mínimos comparáveis.
    # Caso clássico: CNH coletada mas parsing falhou (campos None).
    required_fields = ["nome", "data_nascimento"]
    present = {
        "proposta_daycoval": {
            "nome": bool(proposta_nome),
            "data_nascimento": bool(proposta_dn),
        },
        "cnh": {
            "nome": bool(cnh_nome),
            "data_nascimento": bool(cnh_dn),
        },
    }

    missing_fields: List[str] = []
    if not proposta_nome:
        missing_fields.append("proposta_daycoval.nome")
    if not proposta_dn:
        missing_fields.append("proposta_daycoval.data_nascimento")
    if not cnh_nome:
        missing_fields.append("cnh.nome")
    if not cnh_dn:
        missing_fields.append("cnh.data_nascimento")

    if missing_fields:
        return _mk_check(
            check_id="identity.proposta_vs_cnh",
            status="MISSING",
            message="Missing required identity fields",
            evidence={
                "fields_compared": required_fields,
                "missing_fields": missing_fields,
                "present": present,
            },
        )

    diffs: Dict[str, Any] = {}

    if proposta_nome != cnh_nome:
        diffs["nome"] = True

    if proposta_dn != cnh_dn:
        diffs["data_nascimento"] = True

    if not diffs:
        return _mk_check(
            check_id="identity.proposta_vs_cnh",
            status="OK",
            message="OK",
            evidence={"fields_compared": ["nome", "data_nascimento"], "diffs": {}},
        )

    return _mk_check(
        check_id="identity.proposta_vs_cnh",
        status="WARN",
        message="Divergences found",
        evidence={"fields_compared": ["nome", "data_nascimento"], "diffs": diffs},
    )


def _extract_declared_income_from_proposta(phase1_case_root: Path) -> Optional[float]:
    proposta, _ = _read_phase1_latest_data(phase1_case_root, "proposta_daycoval")
    if not proposta:
        return None
    salario = _parse_money_any(proposta.get("salario"))
    outras = _parse_money_any(proposta.get("outras_rendas"))
    if salario is None and outras is None:
        return None
    return float((salario or 0.0) + (outras or 0.0))


def _extract_proven_income_from_docs(phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> Tuple[List[str], Optional[float]]:
    proof_docs: List[str] = []
    proven: Optional[float] = None

    if bool((presence.get("holerite") or {}).get("present")):
        proof_docs.append("holerite")
        holerite, _ = _read_phase1_latest_data(phase1_case_root, "holerite")
        if holerite:
            proven = _parse_money_any(holerite.get("total_vencimentos") or holerite.get("salario_liquido"))

    if bool((presence.get("extrato_bancario") or {}).get("present")):
        proof_docs.append("extrato_bancario")
        extrato, _ = _read_phase1_latest_data(phase1_case_root, "extrato_bancario")
        if extrato and proven is None:
            for k in ("renda_apurada", "renda_recorrente", "creditos_validos_total", "creditos_recorrentes_total"):
                v = _parse_money_any(extrato.get(k))
                if v is not None:
                    proven = v
                    break

    return proof_docs, proven


def _build_income_checks(phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    declared = _extract_declared_income_from_proposta(phase1_case_root)
    proof_docs, proven = _extract_proven_income_from_docs(phase1_case_root, presence)

    # proof
    if not proof_docs:
        proof_status, proof_msg = "MISSING", "No proof documents present"
    else:
        if proven is None:
            proof_status, proof_msg = "WARN", "Proof documents present but value not extractable"
        else:
            proof_status, proof_msg = "OK", "Proof value extracted"

    proof_chk = _mk_check(
        check_id="income.declared_vs_proven.proof",
        status=proof_status,
        message=proof_msg,
        evidence={"proof_docs": list(proof_docs), "proven": proven},
    )

    # minimum
    if not proof_docs:
        min_status, min_msg = "MISSING", "Missing proof documents"
    else:
        if proven is None:
            min_status, min_msg = "WARN", "Cannot evaluate minimum without proven value"
        else:
            if declared is None:
                min_status, min_msg = "OK", "No declared income available"
            else:
                min_status = "OK" if proven > 0 else "WARN"
                min_msg = "Minimum evidence available" if proven > 0 else "Proven value not positive"

    min_chk = _mk_check(
        check_id="income.declared_vs_proven.minimum",
        status=min_status,
        message=min_msg,
        evidence={"declared": declared, "proof_docs": list(proof_docs), "proven": proven},
    )

    # total
    if declared is None:
        total_status, total_msg = "MISSING", "Declared income missing"
    else:
        if not proof_docs:
            total_status, total_msg = "MISSING", "Proof documents missing"
        else:
            if proven is None:
                total_status, total_msg = "WARN", "Proof documents present but value not extractable"
            else:
                total_status = "OK" if proven >= (declared * 0.95) else "WARN"
                total_msg = "Declared income is supported by proven income" if total_status == "OK" else "Declared income not supported by proven income"

    total_chk = _mk_check(
        check_id="income.declared_vs_proven.total",
        status=total_status,
        message=total_msg,
        evidence={"declared": declared, "proven": proven, "proof_docs": list(proof_docs)},
    )

    return [min_chk, proof_chk, total_chk]


def _build_cnh_senatran_checks_if_present(phase1_case_root: Path, presence: Dict[str, Dict[str, Any]], *, case_id: str) -> List[Dict[str, Any]]:
    """
    Importante (não-regressão):
      - Só gera checks novos se cnh_senatran estiver PRESENTE no Phase1.
      - Não altera Gate1.
    """
    has_senatran = bool((presence.get("cnh_senatran") or {}).get("present"))
    if not has_senatran:
        return []

    proposta, _ = _read_phase1_latest_data(phase1_case_root, "proposta_daycoval")
    cnh_senatran, _ = _read_phase1_latest_data(phase1_case_root, "cnh_senatran")

    return build_proposta_cnh_senatran_checks(
        case_id=case_id,
        proposta_data=proposta or {},
        cnh_senatran_data=cnh_senatran or {},
    )


def _ensure_unique_check_ids(checks: List[Dict[str, Any]]) -> None:
    seen = set()
    for c in checks:
        cid = c.get("id")
        if cid in seen:
            raise ValueError(f"duplicate_check_id: {cid}")
        seen.add(cid)


def _write_report_json(*, phase2_case_root: Path, payload: Dict[str, Any]) -> Path:
    phase2_case_root.mkdir(parents=True, exist_ok=True)
    p = phase2_case_root / "report.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def build_master_report(case_id: str, *, phase1_root: Union[str, Path], phase2_root: Union[str, Path]) -> Dict[str, Any]:
    """
    Canonical Phase2 master report builder.
    Accepts both styles:
      - phase1_root=<...>/phase1           OR phase1_root=<...>/phase1/<case_id>
      - phase2_root=<...>/phase2           OR phase2_root=<...>/phase2/<case_id>

    Must:
      - not block if Phase1 is empty/incomplete
      - write <phase2_root>/<case_id>/report.json (or inside provided case-root)
      - return the payload dict
    """
    p1_root = _coerce_path(phase1_root)
    p2_root = _coerce_path(phase2_root)

    phase1_case_root = _resolve_phase1_case_root(p1_root, case_id)
    phase2_case_root = _resolve_phase2_case_root(p2_root, case_id)

    presence = _list_phase1_presence(phase1_case_root)

    checks: List[Dict[str, Any]] = []
    checks.append(_build_identity_check(phase1_case_root, presence))
    checks.extend(_build_income_checks(phase1_case_root, presence))

    # NEW (non-regression): only when cnh_senatran exists
    checks.extend(_build_cnh_senatran_checks_if_present(phase1_case_root, presence, case_id=case_id))

    # NEW (non-regression): only when ATPV exists (validator itself returns [] if not present)
    checks.extend(build_atpv_checks(phase1_case_root=phase1_case_root, presence=presence))

    # NEW (non-regression): only when DETRAN exists (validator itself returns [] if not present)
    checks.extend(build_detran_checks(phase1_case_root=phase1_case_root, presence=presence))

    _ensure_unique_check_ids(checks)

    overall = _compute_overall_status(checks)

    payload: Dict[str, Any] = {
        "case_id": case_id,
        "checks": checks,
        "inputs": _build_inputs_root_metadata_only(phase1_case_root=phase1_case_root, presence=presence),
        "summary": {"overall_status": overall},
        "overall_status": overall,
        "status": overall,
        "meta": _build_meta(case_id=case_id, phase1_root=p1_root, phase2_root=p2_root, presence=presence),
    }

    _write_report_json(phase2_case_root=phase2_case_root, payload=payload)
    return payload


def build_master_report_and_return_path(
    case_id: str,
    *,
    phase1_root: Union[str, Path],
    phase2_root: Union[str, Path],
) -> str:
    """
    Backward-compatible shim for orchestrator.phase2_runner.
    Returns the path to the written report.json.
    """
    p1_root = _coerce_path(phase1_root)
    p2_root = _coerce_path(phase2_root)

    # Build (also writes report)
    _ = build_master_report(case_id, phase1_root=p1_root, phase2_root=p2_root)

    # Resolve the actual written location
    phase2_case_root = _resolve_phase2_case_root(p2_root, case_id)
    return str(phase2_case_root / "report.json")
