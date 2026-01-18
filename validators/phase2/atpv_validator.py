# validators/phase2/atpv_validator.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from validators.atpv import _is_valid_cnpj as _is_valid_cnpj  # type: ignore
from validators.atpv import _is_valid_cpf as _is_valid_cpf  # type: ignore
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.atpv import _normalize_renavam_to_11 as _normalize_renavam_to_11  # type: ignore
from validators.phase2.utils import load_latest_phase1_json, normalize_doc_id


def _only_digits(s: str) -> str:
    import re
    return re.sub(r"\D+", "", s or "")


def _sanitize_str(s: str) -> str:
    return " ".join((s or "").strip().split()).upper()


def _mask_doc(doc: str) -> str:
    d = _only_digits(doc)
    if not d:
        return ""
    if len(d) == 11:
        return f"{d[:3]}.***.***-{d[-2:]}"
    if len(d) == 14:
        return f"{d[:2]}.***.***/****-{d[-2:]}"
    return f"***{d[-4:]}"


def _mask_renavam(ren11: str) -> str:
    d = _only_digits(ren11)
    if len(d) != 11:
        return ""
    return f"{d[:3]}*****{d[-3:]}"


def _pick_first(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d and d.get(k) not in (None, ""):
            return d.get(k)
    return None


def _name_matches(a: str, b: str) -> bool:
    a = _sanitize_str(a)
    b = _sanitize_str(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # match conservador por tokens
    ta = set(a.split())
    tb = set(b.split())
    return len(ta & tb) >= 2


@dataclass
class CheckResult:
    id: str
    status: str
    message: str
    evidence: Dict[str, Any]


def _mk_check(*, check_id: str, status: str, message: str, evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return asdict(CheckResult(id=check_id, status=status, message=message, evidence=evidence or {}))


def _read_phase1_latest_data(phase1_case_root: Path, doc_type: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        js = load_latest_phase1_json(phase1_case_root, doc_type)
    except Exception as e:
        return None, str(e)
    if not js:
        return None, None
    data = js.get("data") if isinstance(js, dict) else None
    if data is None:
        return None, None
    if isinstance(data, dict):
        return data, None
    return None, None


def _vehicle_correlates_present(presence: Dict[str, Dict[str, Any]]) -> Optional[str]:
    # Ordem preferencial: crlv_e (tende a ter RENAVAM), depois layouts alternativos
    for dt in ("crlv_e", "documento_veiculo_novo", "documento_veiculo_antigo", "documento_veiculo"):
        meta = presence.get(dt) or {}
        if bool(meta.get("present")):
            return dt
    return None


def _extract_vehicle_owner_doc(vehicle_data: Dict[str, Any]) -> str:
    """Extrai (best-effort) o documento do proprietário a partir do payload do doc de veículo.

    Agora aplica normalize_doc_id (remove máscara + exige 11/14 dígitos).
    """
    if not isinstance(vehicle_data, dict):
        return ""

    candidates = [
        vehicle_data.get("proprietario_doc"),
        vehicle_data.get("proprietario_documento"),
        vehicle_data.get("cpf_proprietario"),
        vehicle_data.get("cnpj_proprietario"),
        vehicle_data.get("cpf"),
        vehicle_data.get("cnpj"),
    ]

    for v in candidates:
        d = normalize_doc_id(v)
        if d:
            return d

    return ""


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
                message="Campos essenciais de ATPV presentes.",
            )
        )

    # NORMALIZACAO: comprador_doc (CPF/CNPJ) sempre em formato dígitos (11/14) para comparar e validar
    comprador_doc_raw = atpv.get("comprador_cpf_cnpj")
    comprador_doc = normalize_doc_id(comprador_doc_raw)

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

        # NORMALIZACAO: proposta_doc para comparação robusta
        proposta_doc = normalize_doc_id(proposta_doc_raw)

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
    # ENDURECIMENTO (A): "supported" = doc correlato com RENAVAM VÁLIDO extraído
    # ----------------------------
    vehicle_doc_type = _vehicle_correlates_present(presence)
    vehicle_data: Dict[str, Any] = {}
    vehicle_err: Optional[str] = None
    vehicle_ren11 = ""
    vehicle_ren_valid = False

    if vehicle_doc_type:
        vehicle_data_raw, vehicle_err = _read_phase1_latest_data(phase1_case_root, vehicle_doc_type)
        vehicle_data = vehicle_data_raw or {}

        vehicle_ren_raw = vehicle_data.get("renavam")
        vehicle_ren11 = _normalize_renavam_to_11(str(vehicle_ren_raw)) if vehicle_ren_raw not in (None, "") else ""
        vehicle_ren_valid = bool(vehicle_ren11 and _is_valid_renavam_11(vehicle_ren11))

    supported = bool(vehicle_doc_type and vehicle_ren_valid)

    # required_if_supported
    if supported:
        if not ren11_atpv_valid:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.required_if_supported",
                    status="FAIL",
                    message="RENAVAM ausente ou inválido no ATPV; obrigatório quando doc correlato tem RENAVAM válido.",
                    evidence={
                        "vehicle_doc_type": vehicle_doc_type,
                        "vehicle": _mask_renavam(vehicle_ren11),
                        "atpv_present": bool(ren_raw not in (None, "")),
                    },
                )
            )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.required_if_supported",
                    status="OK",
                    message="RENAVAM presente e válido no ATPV (caso suportado por doc correlato com RENAVAM válido).",
                    evidence={"vehicle_doc_type": vehicle_doc_type},
                )
            )
    elif vehicle_doc_type:
        # Há doc correlato, mas sem RENAVAM válido => não exigir (evita FAIL factory)
        msg = "Documento correlato presente, mas sem RENAVAM válido extraído; não exigindo RENAVAM do ATPV (ainda)."
        if vehicle_err:
            msg = "Falha ao ler documento correlato; não exigindo RENAVAM do ATPV (ainda)."
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.renavam.required_if_supported",
                status="WARN",
                message=msg,
                evidence={"vehicle_doc_type": vehicle_doc_type, "vehicle_err": vehicle_err or "", "vehicle_renavam": _mask_renavam(vehicle_ren11)},
            )
        )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.renavam.required_if_supported",
                status="OK",
                message="Sem documento correlato com RENAVAM válido; RENAVAM do ATPV não exigido.",
            )
        )

    # matches_vehicle_doc: só faz sentido se supported e ATPV tem RENAVAM válido
    if supported and ren11_atpv_valid:
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
                message="RENAVAM não comparável (caso não suportado ou RENAVAM ausente/inválido em um dos documentos).",
                evidence={
                    "supported": bool(supported),
                    "atpv_valid": bool(ren11_atpv_valid),
                    "vehicle_valid": bool(vehicle_ren_valid),
                    "vehicle_doc_type": vehicle_doc_type or "",
                },
            )
        )

    # ----------------------------
    # ENDURECIMENTO (C): vendedor vinculante condicional (WARN por enquanto)
    # ----------------------------
    # NORMALIZACAO: vendedor_doc comparável independente de máscara
    vendor_doc_raw = atpv.get("vendedor_cpf_cnpj")
    vendor_doc = normalize_doc_id(vendor_doc_raw)

    vendor_doc_valid = bool(
        (len(vendor_doc) == 11 and _is_valid_cpf(vendor_doc))
        or (len(vendor_doc) == 14 and _is_valid_cnpj(vendor_doc))
    )

    owner_doc = _extract_vehicle_owner_doc(vehicle_data)
    owner_doc_valid = bool(
        (len(owner_doc) == 11 and _is_valid_cpf(owner_doc))
        or (len(owner_doc) == 14 and _is_valid_cnpj(owner_doc))
    )

    if owner_doc_valid and vendor_doc_valid:
        if owner_doc == vendor_doc:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.vendedor.matches_vehicle_owner",
                    status="OK",
                    message="Documento do vendedor no ATPV coincide com o documento do proprietário no doc do veículo.",
                    evidence={"vendedor": _mask_doc(vendor_doc), "proprietario": _mask_doc(owner_doc), "vehicle_doc_type": vehicle_doc_type or ""},
                )
            )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.vendedor.matches_vehicle_owner",
                    status="WARN",
                    message="Vendedor do ATPV difere do proprietário no doc do veículo (vinculante condicional; WARN por enquanto).",
                    evidence={"vendedor": _mask_doc(vendor_doc), "proprietario": _mask_doc(owner_doc), "vehicle_doc_type": vehicle_doc_type or ""},
                )
            )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.vendedor.matches_vehicle_owner",
                status="OK",
                message="Vendedor ↔ proprietário não comparável (documentos ausentes/inválidos).",
                evidence={
                    "vendor_valid": bool(vendor_doc_valid),
                    "owner_valid": bool(owner_doc_valid),
                    "vehicle_doc_type": vehicle_doc_type or "",
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
            message="FOLLOWUP: RENAVAM hard somente quando doc correlato traz RENAVAM válido (evita FAIL factory). Revisar parsers de docs correlatos para aumentar cobertura.",
        ),
        _mk_check(
            check_id="followup.atpv.vendedor",
            status="OK",
            message="FOLLOWUP: Vendedor agora tem cross-check condicional com proprietário do doc do veículo (WARN). Evoluir para FAIL quando política for aprovada.",
        ),
    ]
