# validators/phase2/detran_validator.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from validators.phase2.utils import load_latest_phase1_json, normalize_doc_id


# -----------------------------
# Types / helpers
# -----------------------------


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
    if isinstance(data, dict):
        return data, None
    return None, None


def _only_digits(value: Any) -> str:
    import re

    s = "" if value is None else str(value)
    return re.sub(r"\D+", "", s)


def _sanitize_name(value: Any) -> str:
    s = "" if value is None else str(value)
    s = " ".join(s.strip().split())
    return s.upper()


def _money_to_cents(value: Any) -> Optional[int]:
    """Converte valores do tipo '57.302,00' / 'R$ 57.302,00' / '57302,00' / '57302' para centavos."""
    s = "" if value is None else str(value)
    s = s.strip()
    if not s:
        return None

    s = s.replace("R$", "").strip()
    s = s.replace(" ", "")

    # casos comuns BR: 57.302,00
    if "," in s:
        # remove separador de milhar
        parts = s.split(",")
        inteiro = parts[0].replace(".", "")
        frac = parts[1] if len(parts) > 1 else "00"
        frac = (frac + "00")[:2]
        if inteiro.isdigit() and frac.isdigit():
            return int(inteiro) * 100 + int(frac)

    # se veio só dígitos, assume reais inteiros
    d = _only_digits(s)
    if d.isdigit() and d:
        return int(d) * 100

    return None


def _pick_first(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d and d.get(k) not in (None, ""):
            return d.get(k)
    return None


def _first_present_doc_type(presence: Dict[str, Dict[str, Any]], doc_types: List[str]) -> Optional[str]:
    for dt in doc_types:
        meta = presence.get(dt) or {}
        if bool(meta.get("present")):
            return dt
    return None


# -----------------------------
# Initials matching
# -----------------------------


_STOPWORDS = {
    "DA",
    "DE",
    "DO",
    "DAS",
    "DOS",
    "E",
    "LTDA",
    "ME",
    "EPP",
    "S/A",
    "SA",
    "S.A.",
    "SOCIEDADE",
    "ANONIMA",
    "ANÔNIMA",
}


def _name_to_initials_tokens(name: str) -> List[str]:
    tokens = [t for t in _sanitize_name(name).split() if t]
    out: List[str] = []
    for t in tokens:
        if t in _STOPWORDS:
            continue
        # ignora tokens muito curtos que não ajudam
        if len(t) == 1:
            continue
        out.append(t[0])
    return out


def _initials_match(detran_initials: str, vendor_name: str) -> Tuple[bool, Dict[str, Any]]:
    """Match fraco: DETRAN (ofuscado) fornece iniciais; comparamos com iniciais do nome do vendedor.

    Critério conservador:
      - precisa haver >=2 iniciais no DETRAN
      - comparamos a sequência (prefixo) com as iniciais do vendedor, ignorando stopwords.
    """
    detran_tokens = [c for c in (detran_initials or "").strip().upper() if "A" <= c <= "Z" or c in "ÁÉÍÓÚÂÊÔÃÕÇ"]
    vendor_tokens = _name_to_initials_tokens(vendor_name)

    ok = False
    if len(detran_tokens) >= 2 and len(vendor_tokens) >= 2:
        # compara prefixo do vendedor com o DETRAN, no tamanho do DETRAN (ou do vendedor, o menor)
        n = min(len(detran_tokens), len(vendor_tokens))
        ok = detran_tokens[:n] == vendor_tokens[:n]

    evidence = {
        "detran_initials": detran_initials,
        "detran_tokens": detran_tokens,
        "vendor_name": vendor_name,
        "vendor_tokens": vendor_tokens,
    }
    return ok, evidence


# -----------------------------
# Public API
# -----------------------------


def build_detran_checks(*, phase1_case_root: Path, presence: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Phase 2: DETRAN checks.

    Fonte: documento de consulta DETRAN (SC) coletado na Phase 1.
    Doc types aceitos (ordem): detran_sc, consulta_detran, detran.

    Regras (status):
      - owner vs ATPV vendedor:
          * OK: doc forte (CPF/CNPJ) bate
          * FAIL: doc forte em ambos e diverge
          * WARN: só iniciais batem (consulta aberta/ofuscada) -> evidência fraca
          * MISSING: insuficiente para comparar (aberta sem iniciais, ou ATPV sem vendedor)
      - restrição administrativa:
          * FAIL se True; OK se False; WARN se None
      - alienação fiduciária:
          * FAIL se "ativa"; OK se "inativa"/"ausente"; WARN se "desconhecida"/None
      - IPVA atraso:
          * FAIL se True; OK se False; WARN se None
      - débitos (debitos+multas) <= Vlr Compra (proposta):
          * FAIL se total > compra; OK se <=; MISSING se não houver compra ou total não apurável
    """
    checks: List[Dict[str, Any]] = []

    detran_doc_type = _first_present_doc_type(presence, ["detran_sc", "consulta_detran", "detran"])
    if not detran_doc_type:
        return []

    checks.append(_mk_check(check_id="vehicle.detran.present", status="OK", message=f"Consulta DETRAN presente (Phase 1) via '{detran_doc_type}'."))

    detran, detran_err = _read_phase1_latest_data(phase1_case_root, detran_doc_type)
    if detran_err:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.input.read_error",
                status="WARN",
                message="Falha ao ler JSON de DETRAN (Phase 1); validações DETRAN podem estar incompletas.",
                evidence={"error": detran_err, "doc_type": detran_doc_type},
            )
        )
        return checks

    detran = detran or {}

    # --- Load ATPV (para cruzar proprietário x vendedor)
    atpv_meta = presence.get("atpv") or {}
    atpv_present = bool(atpv_meta.get("present"))
    atpv: Dict[str, Any] = {}
    atpv_err: Optional[str] = None
    if atpv_present:
        atpv, atpv_err = _read_phase1_latest_data(phase1_case_root, "atpv")
        atpv = atpv or {}

    # -----------------------------
    # 1) Owner matches ATPV vendedor
    # -----------------------------
    detran_owner_doc_raw = detran.get("proprietario_doc")
    detran_owner_doc = normalize_doc_id(detran_owner_doc_raw)
    detran_owner_doc_ofuscado = bool(detran.get("proprietario_doc_ofuscado"))
    detran_owner_initials = detran.get("proprietario_iniciais") or ""

    atpv_vendor_doc_raw = atpv.get("vendedor_cpf_cnpj") if atpv_present else None
    atpv_vendor_doc = normalize_doc_id(atpv_vendor_doc_raw)
    atpv_vendor_name = _sanitize_name(atpv.get("vendedor_nome") if atpv_present else "")

    # (A) caminho forte por doc
    if detran_owner_doc and atpv_vendor_doc:
        if detran_owner_doc == atpv_vendor_doc:
            checks.append(
                _mk_check(
                    check_id="vehicle.detran.owner.matches_atpv_vendedor",
                    status="OK",
                    message="Proprietário no DETRAN coincide com o vendedor do ATPV (match por documento).",
                    evidence={"match_mode": "doc", "detran_owner_doc": "***" + detran_owner_doc[-4:], "atpv_vendor_doc": "***" + atpv_vendor_doc[-4:]},
                )
            )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.detran.owner.matches_atpv_vendedor",
                    status="FAIL",
                    message="Proprietário no DETRAN diverge do vendedor do ATPV (documentos válidos e diferentes).",
                    evidence={"match_mode": "doc", "detran_owner_doc": "***" + detran_owner_doc[-4:], "atpv_vendor_doc": "***" + atpv_vendor_doc[-4:]},
                )
            )
    else:
        # (B) caminho fraco por iniciais (consulta aberta)
        # só faz sentido se DETRAN está ofuscado (nome/doc)
        if detran_owner_initials and atpv_vendor_name:
            ok, ev = _initials_match(str(detran_owner_initials), str(atpv_vendor_name))
            if ok:
                checks.append(
                    _mk_check(
                        check_id="vehicle.detran.owner.matches_atpv_vendedor",
                        status="WARN",
                        message="Proprietário no DETRAN parece coincidir com o vendedor do ATPV (match por iniciais; evidência fraca).",
                        evidence={"match_mode": "initials", **ev, "detran_doc_ofuscado": bool(detran.get('proprietario_nome_ofuscado') or detran_owner_doc_ofuscado)},
                    )
                )
            else:
                # se o detran é aberto/ofuscado, mismatch por iniciais não é prova de divergência
                checks.append(
                    _mk_check(
                        check_id="vehicle.detran.owner.matches_atpv_vendedor",
                        status="MISSING",
                        message="Não foi possível comprovar proprietário DETRAN = vendedor ATPV (iniciais não confirmaram; consulta aberta/ofuscada não permite prova forte).",
                        evidence={"match_mode": "initials", **ev, "detran_doc_ofuscado": bool(detran.get('proprietario_nome_ofuscado') or detran_owner_doc_ofuscado)},
                    )
                )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.detran.owner.matches_atpv_vendedor",
                    status="MISSING",
                    message="Insuficiente para comparar proprietário DETRAN vs vendedor do ATPV (documento/nome/iniciais ausentes).",
                    evidence={
                        "detran_owner_doc_present": bool(detran_owner_doc_raw),
                        "detran_owner_initials_present": bool(detran_owner_initials),
                        "atpv_present": bool(atpv_present),
                        "atpv_vendor_doc_present": bool(atpv_vendor_doc_raw),
                        "atpv_vendor_name_present": bool(atpv_vendor_name),
                    },
                )
            )

    # -----------------------------
    # 2) Restrição administrativa
    # -----------------------------
    restr_admin = detran.get("restricao_administrativa_ativa")
    if restr_admin is True:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.restricao_administrativa.absent",
                status="FAIL",
                message="DETRAN indica restrição/bloqueio administrativo ativo.",
                evidence={"restricao_administrativa_ativa": True, "evidence": (detran.get("evidence") or {}).get("restricao_admin", "")},
            )
        )
    elif restr_admin is False:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.restricao_administrativa.absent",
                status="OK",
                message="Sem restrição administrativa ativa no DETRAN.",
                evidence={"restricao_administrativa_ativa": False, "evidence": (detran.get("evidence") or {}).get("restricao_admin", "")},
            )
        )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.restricao_administrativa.absent",
                status="WARN",
                message="Não foi possível determinar com segurança se há restrição administrativa ativa no DETRAN.",
                evidence={"restricao_administrativa_ativa": None, "evidence": (detran.get("evidence") or {}).get("restricao_admin", "")},
            )
        )

    # -----------------------------
    # 3) Alienação fiduciária
    # -----------------------------
    alien_status = (detran.get("alienacao_fiduciaria_status") or "").strip().lower() if detran.get("alienacao_fiduciaria_status") else None
    if alien_status == "ativa":
        checks.append(
            _mk_check(
                check_id="vehicle.detran.alienacao_fiduciaria.inactive_or_absent",
                status="FAIL",
                message="Alienação fiduciária ativa no DETRAN.",
                evidence={"alienacao_fiduciaria_status": "ativa", "evidence": (detran.get("evidence") or {}).get("alienacao", "")},
            )
        )
    elif alien_status in {"inativa", "ausente"}:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.alienacao_fiduciaria.inactive_or_absent",
                status="OK",
                message="Alienação fiduciária inativa/ausente no DETRAN.",
                evidence={"alienacao_fiduciaria_status": alien_status, "evidence": (detran.get("evidence") or {}).get("alienacao", "")},
            )
        )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.alienacao_fiduciaria.inactive_or_absent",
                status="WARN",
                message="Não foi possível determinar com segurança o status de alienação fiduciária no DETRAN.",
                evidence={"alienacao_fiduciaria_status": alien_status, "evidence": (detran.get("evidence") or {}).get("alienacao", "")},
            )
        )

    # -----------------------------
    # 4) IPVA em atraso
    # -----------------------------
    ipva = detran.get("ipva_em_atraso")
    if ipva is True:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.ipva.no_overdue",
                status="FAIL",
                message="DETRAN indica IPVA em atraso / em aberto / dívida ativa.",
                evidence={"ipva_em_atraso": True, "evidence": (detran.get("evidence") or {}).get("ipva", "")},
            )
        )
    elif ipva is False:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.ipva.no_overdue",
                status="OK",
                message="Sem indicação de IPVA em atraso no DETRAN.",
                evidence={"ipva_em_atraso": False, "evidence": (detran.get("evidence") or {}).get("ipva", "")},
            )
        )
    else:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.ipva.no_overdue",
                status="WARN",
                message="Não foi possível determinar com segurança se há IPVA em atraso no DETRAN.",
                evidence={"ipva_em_atraso": None, "evidence": (detran.get("evidence") or {}).get("ipva", "")},
            )
        )

    # -----------------------------
    # 5) Débitos <= Vlr. Compra (proposta)
    # -----------------------------
    # Total de débitos: debitos_total_cents + multas_total_cents (Phase 1 DETRAN já extraiu)
    detran_debitos = detran.get("debitos_total_cents")
    detran_multas = detran.get("multas_total_cents")
    total_debitos_cents: Optional[int] = None
    if isinstance(detran_debitos, int) and isinstance(detran_multas, int):
        total_debitos_cents = detran_debitos + detran_multas

    proposta_meta = presence.get("proposta_daycoval") or {}
    proposta_present = bool(proposta_meta.get("present"))
    proposta: Dict[str, Any] = {}
    proposta_err: Optional[str] = None
    if proposta_present:
        proposta, proposta_err = _read_phase1_latest_data(phase1_case_root, "proposta_daycoval")
        proposta = proposta or {}

    # o usuário informou que a referência é "Vlr. Compra"
    # chaves variam; tentamos várias
    compra_raw = _pick_first(
        proposta,
        [
            "vlr_compra",
            "vlr_compra_reais",
            "vlr_compra_cents",
            "valor_compra",
            "valor_compra_reais",
            "valor_compra_cents",
            "vlr_molicar",          # às vezes aparece como proxy em alguns layouts
            "vlr_mercado",          # fallback fraco se compra não existir
        ],
    )
    compra_cents: Optional[int] = None
    if isinstance(compra_raw, int):
        # se já estiver em cents (heurística: muito grande)
        compra_cents = compra_raw if compra_raw > 100000 else compra_raw * 100
    else:
        compra_cents = _money_to_cents(compra_raw)

    if total_debitos_cents is None:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.debitos.total_vs_valor_compra",
                status="MISSING",
                message="Não foi possível apurar total de débitos no DETRAN para comparar com valor de compra.",
                evidence={"debitos_total_cents": detran_debitos, "multas_total_cents": detran_multas},
            )
        )
    elif compra_cents is None:
        checks.append(
            _mk_check(
                check_id="vehicle.detran.debitos.total_vs_valor_compra",
                status="MISSING",
                message='Não foi possível apurar "Vlr. Compra" na proposta para comparar com débitos do DETRAN.',
                evidence={"proposta_present": bool(proposta_present), "proposta_read_error": proposta_err or "", "compra_raw": compra_raw},
            )
        )
    else:
        if total_debitos_cents > compra_cents:
            checks.append(
                _mk_check(
                    check_id="vehicle.detran.debitos.total_vs_valor_compra",
                    status="FAIL",
                    message="Total de débitos (DETRAN) excede o valor de compra (proposta).",
                    evidence={
                        "total_debitos_cents": total_debitos_cents,
                        "valor_compra_cents": compra_cents,
                        "debitos_total_cents": detran_debitos,
                        "multas_total_cents": detran_multas,
                    },
                )
            )
        else:
            checks.append(
                _mk_check(
                    check_id="vehicle.detran.debitos.total_vs_valor_compra",
                    status="OK",
                    message="Total de débitos (DETRAN) está dentro do valor de compra (proposta).",
                    evidence={
                        "total_debitos_cents": total_debitos_cents,
                        "valor_compra_cents": compra_cents,
                        "debitos_total_cents": detran_debitos,
                        "multas_total_cents": detran_multas,
                    },
                )
            )

    return checks
