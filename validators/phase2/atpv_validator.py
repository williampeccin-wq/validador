# validators/phase2/atpv_validator.py
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from validators.atpv import _is_valid_cpf as _is_valid_cpf  # type: ignore
from validators.atpv import _is_valid_cnpj as _is_valid_cnpj  # type: ignore
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.atpv import _normalize_renavam_to_11 as _normalize_renavam_to_11  # type: ignore


_PLATE_RE = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

_STATUS_ORDER = ["FAIL", "MISSING", "WARN", "OK"]
_STATUS_RANK = {s: i for i, s in enumerate(_STATUS_ORDER)}


def _safe_read_json(p: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _sanitize_str(s: Any) -> str:
    return str(s).strip()


def _mask_doc(doc: Optional[str]) -> str:
    if not doc:
        return ""
    d = _only_digits(str(doc))
    if len(d) <= 4:
        return d
    if len(d) == 11:
        return f"{d[:3]}***{d[-2:]}"
    if len(d) == 14:
        return f"{d[:4]}***{d[-2:]}"
    return f"{d[:3]}***{d[-2:]}"


def _normalize_name(s: str) -> str:
    s = s.strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Z ]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _name_matches(a: str, b: str) -> bool:
    na = _normalize_name(a)
    nb = _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 10 and na in nb:
        return True
    if len(nb) >= 10 and nb in na:
        return True
    return False


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


def _pick_first(data: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        if k in data and data.get(k) not in (None, ""):
            return data.get(k)
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


def _mk_check(*, check_id: str, status: str, message: str, evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": check_id, "status": status, "message": message, "evidence": evidence or {}}


def _vehicle_correlates_present(presence: Dict[str, Dict[str, Any]]) -> Optional[str]:
    for doc_type in (
        "documento_veiculo",
        "documento_veiculo_novo",
        "documento_veiculo_antigo",
        "crlv_e",
        "crlv",
        "crv",
    ):
        meta = presence.get(doc_type) or {}
        if bool(meta.get("present")):
            return doc_type
    return None


def build_atpv_checks(*, phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    atpv_meta = presence.get("atpv") or {}
    if not bool(atpv_meta.get("present")):
        return []

    checks: List[Dict[str, Any]] = []
    checks.append(_mk_check(check_id="vehicle.atpv.present", status="OK", message="ATPV presente (Phase 1)."))

    atpv, atpv_err = _read_phase1_latest_data(phase1_case_root, "atpv")
    if atpv_err:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.input.read_error",
                status="WARN",
                message="Falha ao ler JSON de ATPV (Phase 1).",
                evidence={"error": atpv_err},
            )
        )
        return checks

    atpv = atpv or {}

    # RENAVAM do ATPV
    ren_raw = atpv.get("renavam")
    ren11_atpv = _normalize_renavam_to_11(str(ren_raw)) if ren_raw else None
    ren11_atpv_valid = bool(ren11_atpv and _is_valid_renavam_11(ren11_atpv))

    # Documento de veículo correlato
    vehicle_doc_type = _vehicle_correlates_present(presence)

    # ============================
    # HARD RULE: RENAVAM obrigatório quando suportado
    # ============================
    if vehicle_doc_type:
        if not ren11_atpv_valid:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.required_if_supported",
                    status="FAIL",
                    message="RENAVAM ausente ou inválido no ATPV, obrigatório quando há documento de veículo.",
                    evidence={
                        "vehicle_doc_type": vehicle_doc_type,
                        "renavam_present": bool(ren_raw),
                    },
                )
            )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.required_if_supported",
                    status="OK",
                    message="RENAVAM presente e válido no ATPV (caso suportado).",
                )
            )

        # ============================
        # HARD CROSS-CHECK: ATPV ↔ veículo
        # ============================
        vehicle_data, _ = _read_phase1_latest_data(phase1_case_root, vehicle_doc_type)
        vehicle_ren_raw = (vehicle_data or {}).get("renavam")
        vehicle_ren11 = _normalize_renavam_to_11(str(vehicle_ren_raw)) if vehicle_ren_raw else None
        vehicle_ren_valid = bool(vehicle_ren11 and _is_valid_renavam_11(vehicle_ren11))

        if ren11_atpv_valid and vehicle_ren_valid:
            if ren11_atpv == vehicle_ren11:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                        status="OK",
                        message="RENAVAM do ATPV coincide com o documento do veículo.",
                    )
                )
            else:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                        status="FAIL",
                        message="RENAVAM do ATPV diverge do documento do veículo.",
                        evidence={
                            "atpv": _mask_doc(ren11_atpv),
                            "vehicle": _mask_doc(vehicle_ren11),
                        },
                    )
                )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                    status="OK",
                    message="RENAVAM não comparável (ausente ou inválido em um dos documentos).",
                )
            )

    return checks
