# validators/phase2/atpv_validator.py
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reusa DV públicos já existentes no validador "duro" de ATPV.
# Nota: Não chamamos validate_atpv() porque ele:
#  - exige RENAVAM como obrigatório (decisão aqui é condicional)
#  - valida vendedor como "nome humano" (decisão aqui é informativo; pode ser PJ)
from validators.atpv import _is_valid_cpf as _is_valid_cpf  # type: ignore
from validators.atpv import _is_valid_cnpj as _is_valid_cnpj  # type: ignore
from validators.atpv import _is_valid_renavam_11 as _is_valid_renavam_11  # type: ignore
from validators.atpv import _normalize_renavam_to_11 as _normalize_renavam_to_11  # type: ignore


_PLATE_RE = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")  # Mercosul/antiga compat
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # VIN 17 chars, exclui I,O,Q

_STATUS_ORDER = ["FAIL", "MISSING", "WARN", "OK"]
_STATUS_RANK = {s: i for i, s in enumerate(_STATUS_ORDER)}


def _safe_read_json(p: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _sanitize_str(s: Any) -> str:
    return str(s).strip()


def _mask_doc(doc: Optional[str]) -> str:
    """
    Mask to avoid leaking full doc in evidence/message.
    Example:
      CPF 11: 123***89
      CNPJ 14: 1234***90
    """
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
    """
    Strong normalization to compare names across docs:
    - strip accents
    - uppercase
    - keep letters/spaces only
    - collapse spaces
    """
    s = s.strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Z ]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _name_matches(a: str, b: str) -> bool:
    """
    Conservative matching:
    - exact after normalization OR
    - one contains the other (to tolerate middle names), requiring reasonable length
    """
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


def _worst_status(a: str, b: str) -> str:
    aa = a if a in _STATUS_RANK else "WARN"
    bb = b if b in _STATUS_RANK else "WARN"
    return aa if _STATUS_RANK[aa] < _STATUS_RANK[bb] else bb


def build_atpv_checks(*, phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Phase 2 ATPV checks.

    Locked decisions for this iteration:
      - RENAVAM condicional (não degrada por ausência; degrada por presente inválido)
      - Vendedor informativo (sem validação "nome humano"; pode ser PJ)
      - Alertas de revisit (RENAVAM/vendedor) via checks OK (visível e determinístico, sem degradar overall_status)
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

    # Required (sem RENAVAM e sem vendedor; vendedor é informativo)
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

    # RENAVAM condicional
    ren_raw = atpv.get("renavam")
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
        ren11 = _normalize_renavam_to_11(str(ren_raw))
        if not ren11:
            checks.append(
                _mk_check(
                    check_id="vehicle.atpv.renavam.conditional",
                    status="WARN",
                    message="RENAVAM presente mas com tamanho inválido.",
                    evidence={"present": True},
                )
            )
        else:
            if _is_valid_renavam_11(ren11):
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

    # Crosscheck comprador ↔ proposta
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
        proposta_doc_raw = _pick_first(proposta, ["cpf", "cpf_financiado", "cpf_cliente", "cpf_titular", "cpf_cnpj", "documento", "documento_numero"])
        proposta_nome_raw = _pick_first(proposta, ["nome_financiado", "nome", "nome_cliente", "cliente_nome", "nome_titular"])

        proposta_doc = _only_digits(str(proposta_doc_raw or ""))
        proposta_nome = _sanitize_str(proposta_nome_raw or "")

        comprador_nome = _sanitize_str(atpv.get("comprador_nome") or "")

        status = "OK"
        msg_parts: List[str] = []

        # doc
        if comprador_doc and proposta_doc:
            if comprador_doc == proposta_doc:
                msg_parts.append("CPF/CNPJ comprador confere com proposta.")
            else:
                status = _worst_status(status, "WARN")
                msg_parts.append("CPF/CNPJ comprador diverge da proposta.")
        else:
            status = _worst_status(status, "WARN")
            msg_parts.append("CPF/CNPJ insuficiente para comparar comprador vs proposta.")

        # nome
        if comprador_nome and proposta_nome:
            if _name_matches(comprador_nome, proposta_nome):
                msg_parts.append("Nome comprador compatível com proposta.")
            else:
                status = _worst_status(status, "WARN")
                msg_parts.append("Nome comprador diverge da proposta.")
        else:
            status = _worst_status(status, "WARN")
            msg_parts.append("Nome insuficiente para comparar comprador vs proposta.")

        checks.append(
            _mk_check(
                check_id="vehicle.atpv.comprador.matches_proposta",
                status=status,
                message=" ".join(msg_parts),
                evidence={
                    "comprador_doc": _mask_doc(comprador_doc),
                    "proposta_doc": _mask_doc(proposta_doc),
                    "comprador_nome_norm": _normalize_name(comprador_nome)[:40] if comprador_nome else "",
                    "proposta_nome_norm": _normalize_name(proposta_nome)[:40] if proposta_nome else "",
                },
            )
        )

    # Vendedor informativo (sem validação vinculante nesta fase)
    vend_nome = _sanitize_str(atpv.get("vendedor_nome") or "")
    vend_doc = _only_digits(str(atpv.get("vendedor_cpf_cnpj") or ""))
    if vend_nome or vend_doc:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.vendedor.informativo",
                status="OK",
                message="Vendedor registrado como informativo (regra não vinculante nesta fase).",
                evidence={"vendedor_doc": _mask_doc(vend_doc), "vendedor_nome_norm": _normalize_name(vend_nome)[:60] if vend_nome else ""},
            )
        )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.atpv.vendedor.informativo",
                status="OK",
                message="Vendedor não disponível; regra informativa (sem impacto nesta fase).",
                evidence={"vendedor_disponivel": False},
            )
        )

    # Followups (visíveis, determinísticos e NÃO degradam overall_status)
    checks.extend(_followup_checks())

    return checks


def _followup_checks() -> List[Dict[str, Any]]:
    return [
        _mk_check(
            check_id="followup.atpv.renavam",
            status="OK",
            message="FOLLOWUP: RENAVAM está condicional; revisar extração e decisão de obrigatoriedade.",
        ),
        _mk_check(
            check_id="followup.atpv.vendedor",
            status="OK",
            message="FOLLOWUP: Vendedor está informativo; revisar regra vinculante condicional quando houver docs correlatos.",
        ),
    ]
