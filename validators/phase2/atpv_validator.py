# validators/phase2/atpv_validator.py
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reusa DV e normalização RENAVAM do validador "duro" existente.
from validators.atpv import _is_valid_cpf as _is_valid_cpf  # type: ignore
from validators.atpv import _is_valid_cnpj as _is_valid_cnpj  # type: ignore
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.atpv import _normalize_renavam_to_11 as _normalize_renavam_to_11  # type: ignore


_PLATE_RE = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")  # Mercosul/antiga compat
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # VIN 17 chars, exclui I,O,Q


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


def _mask_renavam(ren11: Optional[str]) -> str:
    if not ren11:
        return ""
    d = _only_digits(str(ren11))
    if len(d) < 4:
        return d
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
    """
    Retorna o doc_type correlato de veículo quando presente (caso suportado),
    ou None quando não há doc correlato.
    """
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
    """
    Phase 2 ATPV checks.

    Mantém contrato anterior (Policy A + checks essenciais) e adiciona endurecimento:
      - vehicle.atpv.renavam.required_if_supported: FAIL quando suportado e RENAVAM ausente/inválido
      - vehicle.atpv.renavam.matches_vehicle_doc: FAIL quando suportado e ambos válidos e divergentes
    """
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
                message="Falha ao ler JSON de ATPV (Phase 1); validações podem estar incompletas.",
                evidence={"error": atpv_err},
            )
        )
        checks.extend(_followup_checks())
        return checks

    atpv = atpv or {}

    # ----------------------------
    # Checks essenciais já existentes
    # ----------------------------
    required = ["placa", "chassi", "valor_venda", "comprador_cpf_cnpj", "comprador_nome"]
    missing = [k for k in required if atpv.get(k) in (None, "")]
    if missing:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.parse.required_fields",
                status="WARN",
                message=f"ATPV sem campos essenciais: {', '.join(missing)}.",
                evidence={"missing": missing},
            )
        )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.parse.required_fields",
                status="OK",
                message="ATPV contém campos essenciais (placa, chassi, valor_venda, comprador_doc, comprador_nome).",
            )
        )

    # Placa
    placa = _sanitize_str(atpv.get("placa")).upper()
    placa_norm = re.sub(r"[^A-Z0-9]", "", placa)
    if placa_norm:
        if _PLATE_RE.match(placa_norm):
            checks.append(_mk_check(check_id="vehicle.atpv.placa.format", status="OK", message="Placa com formato válido."))
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.placa.format",
                    status="WARN",
                    message="Placa com formato inválido.",
                    evidence={"placa": placa_norm},
                )
            )

    # Chassi/VIN
    chassi = _sanitize_str(atpv.get("chassi")).upper()
    chassi_norm = re.sub(r"[^A-Z0-9]", "", chassi)
    if chassi_norm:
        if _VIN_RE.match(chassi_norm):
            checks.append(_mk_check(check_id="vehicle.atpv.chassi.format", status="OK", message="Chassi (VIN) com formato válido."))
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.chassi.format",
                    status="WARN",
                    message="Chassi (VIN) com formato inválido.",
                    evidence={"chassi": chassi_norm},
                )
            )

    # Valor venda
    v = _parse_money_any(atpv.get("valor_venda"))
    if v is None:
        checks.append(_mk_check(check_id="vehicle.atpv.valor_venda.positive", status="WARN", message="Valor de venda não pôde ser interpretado."))
    else:
        if v > 0:
            checks.append(_mk_check(check_id="vehicle.atpv.valor_venda.positive", status="OK", message="Valor de venda positivo."))
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.valor_venda.positive",
                    status="WARN",
                    message="Valor de venda não é positivo.",
                    evidence={"valor_venda": v},
                )
            )

    # Documento comprador (DV)
    comprador_doc_raw = atpv.get("comprador_cpf_cnpj")
    comprador_doc = _only_digits(str(comprador_doc_raw or ""))
    if comprador_doc:
        dv_ok = False
        if len(comprador_doc) == 11:
            dv_ok = bool(_is_valid_cpf(comprador_doc))
        elif len(comprador_doc) == 14:
            dv_ok = bool(_is_valid_cnpj(comprador_doc))
        else:
            dv_ok = False

        if dv_ok:
            checks.append(_mk_check(check_id="vehicle.atpv.comprador_doc.dv", status="OK", message="Documento do comprador (CPF/CNPJ) com DV válido."))
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.comprador_doc.dv",
                    status="WARN",
                    message="Documento do comprador (CPF/CNPJ) inválido ou tamanho inesperado.",
                    evidence={"comprador_doc": _mask_doc(comprador_doc), "len": len(comprador_doc)},
                )
            )

    # RENAVAM condicional (legado)
    ren_raw = atpv.get("renavam")
    ren11_atpv = _normalize_renavam_to_11(str(ren_raw)) if ren_raw not in (None, "") else ""
    ren11_atpv_valid = bool(ren11_atpv and _is_valid_renavam_11(ren11_atpv))

    if ren_raw in (None, ""):
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.renavam.conditional",
                status="OK",
                message="RENAVAM não extraído; regra condicional (revisar extração/obrigatoriedade depois).",
                evidence={"present": False},
            )
        )
    else:
        if not ren11_atpv:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.conditional",
                    status="WARN",
                    message="RENAVAM presente mas com tamanho inválido.",
                    evidence={"present": True},
                )
            )
        else:
            if ren11_atpv_valid:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.renavam.conditional",
                        status="OK",
                        message="RENAVAM presente e com DV válido.",
                        evidence={"present": True},
                    )
                )
            else:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.renavam.conditional",
                        status="WARN",
                        message="RENAVAM presente mas DV inválido.",
                        evidence={"present": True},
                    )
                )

    # ----------------------------
    # Política A (comprador ↔ proposta) — REQUIRED pelos seus testes
    # ----------------------------
    proposta, proposta_err = _read_phase1_latest_data(phase1_case_root, "proposta_daycoval")
    if proposta_err:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.comprador.matches_proposta",
                status="WARN",
                message="Não foi possível ler proposta_daycoval para cruzamento com ATPV.",
                evidence={"error": proposta_err},
            )
        )
    else:
        proposta = proposta or {}
        proposta_doc_raw = _pick_first(
            proposta,
            ["cpf", "cpf_financiado", "cpf_cliente", "cpf_titular", "cpf_cnpj", "documento", "documento_numero"],
        )
        proposta_nome_raw = _pick_first(
            proposta,
            ["nome_financiado", "nome", "nome_cliente", "cliente_nome", "nome_titular"],
        )

        proposta_doc = _only_digits(str(proposta_doc_raw or ""))
        proposta_nome = _sanitize_str(proposta_nome_raw or "")
        comprador_nome = _sanitize_str(atpv.get("comprador_nome") or "")

        # Contrato: se ambos docs existem, mismatch => WARN (não salva com nome)
        if comprador_doc and proposta_doc:
            if comprador_doc == proposta_doc:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.comprador.matches_proposta",
                        status="OK",
                        message="Comprador do ATPV coincide com o documento do comprador na proposta.",
                        evidence={"atpv": _mask_doc(comprador_doc), "proposta": _mask_doc(proposta_doc)},
                    )
                )
            else:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.comprador.matches_proposta",
                        status="WARN",
                        message="Comprador do ATPV NÃO coincide com o documento do comprador na proposta (Política A).",
                        evidence={"atpv": _mask_doc(comprador_doc), "proposta": _mask_doc(proposta_doc)},
                    )
                )
        else:
            # docs insuficientes -> fallback por nome
            if comprador_nome and proposta_nome and _name_matches(comprador_nome, proposta_nome):
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.comprador.matches_proposta",
                        status="OK",
                        message="Comprador do ATPV coincide com a proposta (match por nome; docs ausentes/incompletos).",
                    )
                )
            else:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.comprador.matches_proposta",
                        status="WARN",
                        message="Comprador do ATPV NÃO coincide com a proposta (docs ausentes/incompletos e nome não confirmou).",
                        evidence={"atpv_doc": _mask_doc(comprador_doc), "proposta_doc": _mask_doc(proposta_doc)},
                    )
                )

    # Vendedor informativo (legado)
    vendor_name = _sanitize_str(atpv.get("vendedor_nome") or "")
    checks.append(
        _mk_check(
            check_id="vehicle.atpv.vendedor.informativo",
            status="OK",
            message="Vendedor do ATPV tratado como informativo (pode ser PJ).",
            evidence={"vendedor_nome": vendor_name[:60] if vendor_name else ""},
        )
    )

    # ----------------------------
    # ENDURECIMENTO: RENAVAM obrigatório quando suportado + cross-check
    # ----------------------------
    vehicle_doc_type = _vehicle_correlates_present(presence)
    if vehicle_doc_type:
        # HARD: obrigatório se suportado
        if not ren11_atpv_valid:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.required_if_supported",
                    status="FAIL",
                    message="RENAVAM ausente ou inválido no ATPV, obrigatório quando há documento correlato de veículo.",
                    evidence={"vehicle_doc_type": vehicle_doc_type, "renavam_present": bool(ren_raw not in (None, ""))},
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

        # Cross-check apenas se ambos válidos (do contrário: OK não-comparável)
        vehicle_data, vehicle_err = _read_phase1_latest_data(phase1_case_root, vehicle_doc_type)
        if vehicle_err:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                    status="WARN",
                    message="Falha ao ler documento correlato de veículo para cross-check de RENAVAM.",
                    evidence={"vehicle_doc_type": vehicle_doc_type, "error": vehicle_err},
                )
            )
        else:
            vehicle_ren_raw = (vehicle_data or {}).get("renavam")
            vehicle_ren11 = _normalize_renavam_to_11(str(vehicle_ren_raw)) if vehicle_ren_raw not in (None, "") else ""
            vehicle_ren_valid = bool(vehicle_ren11 and _is_valid_renavam_11(vehicle_ren11))

            if ren11_atpv_valid and vehicle_ren_valid:
                if ren11_atpv == vehicle_ren11:
                    checks.append(
                        _mk_check(
                            check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                            status="OK",
                            message="RENAVAM do ATPV coincide com o RENAVAM do documento do veículo.",
                        )
                    )
                else:
                    checks.append(
                        _mk_check(
                            check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                            status="FAIL",
                            message="RENAVAM do ATPV diverge do RENAVAM do documento do veículo.",
                            evidence={"atpv": _mask_renavam(ren11_atpv), "vehicle": _mask_renavam(vehicle_ren11)},
                        )
                    )
            else:
                checks.append(
                    _mk_check(
                        check_id="vehicle.atpv.renavam.matches_vehicle_doc",
                        status="OK",
                        message="RENAVAM não comparável (ausente ou inválido em um dos documentos).",
                        evidence={
                            "atpv_valid": bool(ren11_atpv_valid),
                            "vehicle_valid": bool(vehicle_ren_valid),
                            "vehicle_doc_type": vehicle_doc_type,
                        },
                    )
                )

    # Followups (legado)
    checks.extend(_followup_checks())

    return checks


def _followup_checks() -> List[Dict[str, Any]]:
    return [
        _mk_check(
            check_id="followup.atpv.renavam",
            status="OK",
            message="FOLLOWUP: RENAVAM foi endurecido quando suportado; revisar cobertura de parsers de docs correlatos.",
        ),
        _mk_check(
            check_id="followup.atpv.vendedor",
            status="OK",
            message="FOLLOWUP: Vendedor está informativo; revisar regra vinculante condicional quando houver docs correlatos.",
        ),
    ]
