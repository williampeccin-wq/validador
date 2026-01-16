"""
Phase 2 — Master Report

Objetivo:
- Consolidar resultados de múltiplos validadores (proposta vs cnh, renda, etc.) em um único report.
- NÃO bloquear execução durante parsing/coleta: o report deve ser gerado mesmo com Phase 1 vazio/incompleto.
- Contrato: salvar JSON em phase2/<case_id>/report.json.

Notas importantes:
- O status agregado é calculado a partir dos checks.
- Para compatibilidade com testes/consumidores, o JSON inclui também "overall_status" e "status" no topo
  (além de summary.overall_status).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# Tipos
# -----------------------------


@dataclass(frozen=True)
class Evidence:
    source: str
    path: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None


@dataclass(frozen=True)
class CheckResult:
    id: str
    title: str
    status: str  # OK | WARN | FAIL | MISSING
    expected: Any = None
    found: Any = None
    explain: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MasterSummary:
    overall_status: str
    counts: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MasterReport:
    case_id: str
    created_at: str
    inputs: Dict[str, Dict[str, Any]]
    checks: List[CheckResult]
    summary: MasterSummary
    debug: Dict[str, Any] = field(default_factory=dict)


# -----------------------------
# Helpers gerais
# -----------------------------


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_upper(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return s.strip().upper()


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_money(s: Any) -> Optional[float]:
    """
    Aceita strings tipo:
      "R$ 1.234,56"
      "1234,56"
      "1.234,56"
      "1234.56"
    E retorna float.
    """
    if s is None:
        return None
    if isinstance(s, (int, float)):
        try:
            return float(s)
        except Exception:
            return None
    if not isinstance(s, str):
        return None

    raw = s.strip()
    if not raw:
        return None

    # Remove prefixos/sufixos comuns
    raw = raw.replace("R$", "").replace("r$", "")
    raw = raw.replace("\u00a0", " ")  # NBSP
    raw = raw.strip()

    # Remove quaisquer caracteres que não sejam dígitos, separadores ou sinal
    raw = re.sub(r"[^0-9,.\-]", "", raw)
    if not raw:
        return None

    # Heurística BR: separador decimal é vírgula quando existe
    # e ponto é milhar. Ex: 1.234,56
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    # else: já está com ponto decimal ou número inteiro

    try:
        return float(raw)
    except Exception:
        return None


def _overall_from_checks(checks: List[CheckResult]) -> MasterSummary:
    """
    Severidade:
      FAIL > WARN > MISSING > OK
    """
    counts: Dict[str, int] = {"OK": 0, "WARN": 0, "FAIL": 0, "MISSING": 0}
    for c in checks:
        s = (c.status or "").upper()
        if s not in counts:
            counts[s] = 0
        counts[s] += 1

    if counts.get("FAIL", 0) > 0:
        overall = "FAIL"
    elif counts.get("WARN", 0) > 0:
        overall = "WARN"
    elif counts.get("MISSING", 0) > 0:
        overall = "MISSING"
    else:
        overall = "OK"

    return MasterSummary(overall_status=overall, counts=counts)


# -----------------------------
# Leitura Phase 1 (inputs)
# -----------------------------


_HOLERITE_ALIASES = {
    "holerite",
    "contra-cheque",
    "contra_cheque",
    "contracheque",
    "folha",
    "folha_de_pagamento",
    "folha_pagamento",
    "folha_pgto",
    "folha_de_pgto",
}


def _list_case_doc_jsons(case_root: Path, logical_type: str) -> List[Path]:
    """
    Procura docs do tipo em:
      phase1/<case_id>/<logical_type>/*.json
    """
    p = case_root / logical_type
    if not p.exists() or not p.is_dir():
        return []
    return sorted(p.glob("*.json"))


def _load_latest_json(path_list: List[Path]) -> Optional[Dict[str, Any]]:
    if not path_list:
        return None
    p = path_list[-1]
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_latest_input(case_root: Path, logical_type: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Retorna tuple(path, data_dict) do JSON mais recente do tipo.
    """
    paths = _list_case_doc_jsons(case_root, logical_type)
    if not paths:
        return None
    p = paths[-1]
    payload = _load_latest_json(paths)
    if not payload:
        return None

    # Contrato Phase 1: payload contém "data" (ou estrutura semelhante)
    # Se não houver, tentamos usar payload diretamente.
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        return (str(p), data)
    if isinstance(payload, dict):
        return (str(p), payload)
    return None


def _discover_holerite_input(case_root: Path) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Phase 1 pode salvar holerite/folha com diferentes pastas.
    Procuramos qualquer alias, retornando o mais recente encontrado.
    """
    candidates: List[Tuple[Path, Dict[str, Any]]] = []
    for alias in sorted(_HOLERITE_ALIASES):
        paths = _list_case_doc_jsons(case_root, alias)
        if not paths:
            continue
        p = paths[-1]
        payload = _load_latest_json(paths)
        if not payload or not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.append((p, data))
        else:
            candidates.append((p, payload))

    if not candidates:
        return None

    # escolher o mais recente pelo nome do arquivo (uuid) não garante timestamp, mas é o mesmo critério do Phase 1
    candidates = sorted(candidates, key=lambda t: str(t[0]))
    p, data = candidates[-1]
    return (str(p), data)


def _collect_inputs(case_id: str, phase1_root: str) -> Dict[str, Dict[str, Any]]:
    """
    Retorna:
      {
        "proposta_daycoval": {"_path": "...", ...data...},
        "cnh": {"_path": "...", ...},
        "holerite": {"_path": "...", ...},
        "extrato_bancario": {"_path": "...", ...},
      }
    """
    case_root = Path(phase1_root) / case_id
    out: Dict[str, Dict[str, Any]] = {}

    proposta = _load_latest_input(case_root, "proposta_daycoval")
    if proposta:
        p, d = proposta
        out["proposta_daycoval"] = {"_path": p, **d}

    cnh = _load_latest_input(case_root, "cnh")
    if cnh:
        p, d = cnh
        out["cnh"] = {"_path": p, **d}

    hol = _discover_holerite_input(case_root)
    if hol:
        p, d = hol
        out["holerite"] = {"_path": p, **d}

    ext = _load_latest_input(case_root, "extrato_bancario")
    if ext:
        p, d = ext
        out["extrato_bancario"] = {"_path": p, **d}

    return out


def _get_input_tuple(inputs: Dict[str, Dict[str, Any]], key: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    v = inputs.get(key)
    if not v:
        return None
    p = v.get("_path")
    if not isinstance(p, str):
        p = None
    d = dict(v)
    d.pop("_path", None)
    return (p or "", d)


# -----------------------------
# Checks Proposta vs CNH (exemplo)
# -----------------------------


def _similarity(a: str, b: str) -> float:
    """
    Similaridade simples baseada em tokens (não é perfeito, mas é suficiente para MVP).
    """
    a = _normalize_spaces(a).upper()
    b = _normalize_spaces(b).upper()
    if not a or not b:
        return 0.0
    sa = set(a.split(" "))
    sb = set(b.split(" "))
    if not sa or not sb:
        return 0.0
    inter = len(sa.intersection(sb))
    uni = len(sa.union(sb))
    return inter / uni if uni else 0.0


def _check_field_equal(
    check_id: str,
    title: str,
    left: Tuple[str, Dict[str, Any]],
    right: Tuple[str, Dict[str, Any]],
    *,
    field_left: str,
    field_right: str,
    normalize: Optional[str] = None,  # "upper" | None
    missing_is: str = "MISSING",
    mismatch_is: str = "WARN",
) -> CheckResult:
    lp, ld = left
    rp, rd = right
    lv = ld.get(field_left)
    rv = rd.get(field_right)

    if normalize == "upper":
        lv = _safe_upper(lv) if isinstance(lv, str) else lv
        rv = _safe_upper(rv) if isinstance(rv, str) else rv

    evidence = [
        Evidence(source="proposta_daycoval", path=lp, field=field_left, value=lv),
        Evidence(source="cnh", path=rp, field=field_right, value=rv),
    ]

    if lv in (None, "") or rv in (None, ""):
        return CheckResult(
            id=check_id,
            title=title,
            status=missing_is,
            expected=f"{field_left} == {field_right}",
            found={"left": lv, "right": rv},
            explain="Campos ausentes para comparação.",
            evidence=evidence,
        )

    if lv == rv:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=lv,
            found=rv,
            explain="Campos iguais.",
            evidence=evidence,
        )

    return CheckResult(
        id=check_id,
        title=title,
        status=mismatch_is,
        expected=lv,
        found=rv,
        explain="Campos divergentes.",
        evidence=evidence,
    )


def _check_field_similarity(
    check_id: str,
    title: str,
    left: Tuple[str, Dict[str, Any]],
    right: Tuple[str, Dict[str, Any]],
    *,
    field_left: str,
    field_right: str,
    min_ok: float = 0.75,
) -> CheckResult:
    lp, ld = left
    rp, rd = right
    lv = ld.get(field_left)
    rv = rd.get(field_right)

    evidence = [
        Evidence(source="proposta_daycoval", path=lp, field=field_left, value=lv),
        Evidence(source="cnh", path=rp, field=field_right, value=rv),
    ]

    if not isinstance(lv, str) or not isinstance(rv, str) or not lv.strip() or not rv.strip():
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=f"similaridade >= {min_ok}",
            found={"left": lv, "right": rv},
            explain="Nome ausente ou inválido para similaridade.",
            evidence=evidence,
        )

    sim = _similarity(lv, rv)
    status = "OK" if sim >= min_ok else "WARN"

    return CheckResult(
        id=check_id,
        title=title,
        status=status,
        expected=f">= {min_ok}",
        found={"similarity": sim},
        explain="Similaridade por tokens entre nomes.",
        evidence=evidence,
        details={"min_ok": min_ok},
    )


# -----------------------------
# Checks de renda (contrato novo)
# -----------------------------


def _compare_declared_vs_proven(
    *,
    check_id: str,
    title: str,
    declared_total: float,
    proven: float,
    evidence: List[Evidence],
    tolerance_ratio: float = 0.10,
) -> CheckResult:
    """
    declared_total: renda declarada (proposta)
    proven: renda comprovada (holerite ou extrato)
    tolerance_ratio: tolerância proporcional (default 10%)
    """
    if declared_total <= 0:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected="declared_total > 0",
            found={"declared_total": declared_total},
            explain="Renda declarada inválida ou ausente para comparação.",
            evidence=evidence,
        )

    diff = abs(declared_total - proven)
    ratio = diff / declared_total if declared_total else 1.0

    if ratio <= tolerance_ratio:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=f"{declared_total:.2f}",
            found={"proven": proven},
            explain=f"Comprovado dentro da tolerância ({tolerance_ratio:.0%}).",
            evidence=evidence,
            details={"diff": diff, "ratio": ratio, "tolerance_ratio": tolerance_ratio},
        )

    return CheckResult(
        id=check_id,
        title=title,
        status="FAIL",
        expected=f"{declared_total:.2f} ± {tolerance_ratio:.0%}",
        found={"proven": proven},
        explain="Comprovado fora da tolerância.",
        evidence=evidence,
        details={"diff": diff, "ratio": ratio, "tolerance_ratio": tolerance_ratio},
    )


def _compute_declared_income_total(proposta: Tuple[str, Dict[str, Any]]) -> Tuple[Optional[float], List[Evidence], Optional[str]]:
    """
    Renda declarada na proposta:
      - salario
      - outras_rendas
      - soma dos dois quando possível
    """
    p, data = proposta
    salario = _parse_money(data.get("salario"))
    outras = _parse_money(data.get("outras_rendas"))

    evidence = [
        Evidence(source="proposta_daycoval", path=p, field="salario", value=data.get("salario")),
        Evidence(source="proposta_daycoval", path=p, field="outras_rendas", value=data.get("outras_rendas")),
    ]

    if salario is None and outras is None:
        return None, evidence, "Sem campos de renda declarada (salario/outras_rendas)."

    total = 0.0
    if salario is not None:
        total += salario
    if outras is not None:
        total += outras

    if total <= 0:
        return None, evidence, "Renda declarada <= 0."

    return total, evidence, None


def _compute_proven_income_from_holerite(holerite: Tuple[str, Dict[str, Any]]) -> Tuple[Optional[float], List[Evidence], Optional[str]]:
    """
    Campos comuns em holerite/folha:
      - total_vencimentos
      - total_vencimentos_mes
      - total_vencimentos_bruto
      - total_proventos
    """
    p, data = holerite
    candidates = [
        ("total_vencimentos", data.get("total_vencimentos")),
        ("total_vencimentos_mes", data.get("total_vencimentos_mes")),
        ("total_vencimentos_bruto", data.get("total_vencimentos_bruto")),
        ("total_proventos", data.get("total_proventos")),
    ]

    evidence = [Evidence(source="holerite", path=p, field=k, value=v) for k, v in candidates]

    for k, v in candidates:
        val = _parse_money(v)
        if val is not None and val > 0:
            return val, evidence, None

    return None, evidence, "Holerite presente, mas sem campo apurável de total de vencimentos/proventos."


def _compute_proven_income_from_extrato(extrato: Tuple[str, Dict[str, Any]]) -> Tuple[Optional[float], List[Evidence], Optional[str]]:
    """
    Extrato pode ter:
      - renda_apurada
      - renda_recorrente
      - creditos_recorrentes_total
      - creditos_validos_total
    """
    p, data = extrato
    candidates = [
        ("renda_apurada", data.get("renda_apurada")),
        ("renda_recorrente", data.get("renda_recorrente")),
        ("creditos_recorrentes_total", data.get("creditos_recorrentes_total")),
        ("creditos_validos_total", data.get("creditos_validos_total")),
    ]

    evidence = [Evidence(source="extrato_bancario", path=p, field=k, value=v) for k, v in candidates]

    for k, v in candidates:
        val = _parse_money(v)
        if val is not None and val > 0:
            return val, evidence, None

    return None, evidence, "Extrato presente, mas sem campo apurável de renda/creditos recorrentes."


def _check_income_declared_vs_proven_any_proof(
    proposta: Tuple[str, Dict[str, Any]],
    holerite: Optional[Tuple[str, Dict[str, Any]]],
    extrato: Optional[Tuple[str, Dict[str, Any]]],
    *,
    check_id: str = "income.declared_vs_proven",
    title: str = "Renda declarada vs comprovada",
    tolerance_ratio: float = 0.10,
) -> CheckResult:
    """
    Lógica original (mantida para utilidade interna): compara quando houver qualquer prova apurável.
    """
    declared_total, evidence_declared, err_declared = _compute_declared_income_total(proposta)

    evidence: List[Evidence] = []
    evidence.extend(evidence_declared)

    has_any_proof_doc = bool(holerite) or bool(extrato)
    if not has_any_proof_doc:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected="holerite/folha ou extrato",
            found={"holerite": False, "extrato_bancario": False},
            explain="Sem documentos de prova; não é possível comprovar renda.",
            evidence=evidence,
        )

    # compute proven: prefer holerite if exists, else extrato
    proven = None
    proven_src = None
    proven_evidence: List[Evidence] = []
    proven_errs: List[str] = []

    if holerite is not None:
        v, ev, err = _compute_proven_income_from_holerite(holerite)
        proven_evidence.extend(ev)
        if v is not None:
            proven = v
            proven_src = "holerite"
        elif err:
            proven_errs.append(err)

    if proven is None and extrato is not None:
        v, ev, err = _compute_proven_income_from_extrato(extrato)
        proven_evidence.extend(ev)
        if v is not None:
            proven = v
            proven_src = "extrato_bancario"
        elif err:
            proven_errs.append(err)

    evidence.extend(proven_evidence)

    if declared_total is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected="renda declarada (salario/outras_rendas)",
            found={"declared_total": None},
            explain=err_declared or "Renda declarada ausente.",
            evidence=evidence,
        )

    if proven is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="WARN",
            expected=f"{declared_total:.2f}",
            found={"proven": None, "proven_src": proven_src},
            explain="Documento de prova presente, mas nenhum campo apurável foi encontrado. " + " / ".join(proven_errs),
            evidence=evidence,
        )

    return _compare_declared_vs_proven(
        check_id=check_id,
        title=title,
        declared_total=declared_total,
        proven=proven,
        evidence=evidence,
        tolerance_ratio=tolerance_ratio,
    )


def _income_declared_total(proposta: Optional[Tuple[str, Dict[str, Any]]]) -> Tuple[Optional[float], List[Evidence], Optional[str]]:
    if proposta is None:
        return None, [], "Sem proposta; não há renda declarada."
    return _compute_declared_income_total(proposta)


def _income_best_proven(
    holerite: Optional[Tuple[str, Dict[str, Any]]],
    extrato: Optional[Tuple[str, Dict[str, Any]]],
) -> Tuple[Optional[float], List[Evidence], List[str]]:
    """
    Retorna (proven_best, evidence, errs).
    Preferência: holerite > extrato.
    """
    proven_best: Optional[float] = None
    evidence: List[Evidence] = []
    errs: List[str] = []

    if holerite is not None:
        v, ev, err = _compute_proven_income_from_holerite(holerite)
        evidence.extend(ev)
        if v is not None:
            return v, evidence, errs
        if err:
            errs.append(err)

    if extrato is not None:
        v, ev, err = _compute_proven_income_from_extrato(extrato)
        evidence.extend(ev)
        if v is not None:
            return v, evidence, errs
        if err:
            errs.append(err)

    return None, evidence, errs


# -----------------------------
# Entrada/saída (storage)
# -----------------------------


def save_phase2_report(report: MasterReport, phase2_root: str = "storage/phase2") -> Path:
    """
    Salva report JSON em:
      <phase2_root>/<case_id>/report.json
    """
    out_dir = Path(phase2_root) / report.case_id
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = asdict(report)

    # Compatibilidade: consumidores/testes esperam um status agregado no topo.
    # (o report já possui summary.overall_status, mas aqui normalizamos também em root)
    overall = None
    try:
        overall = report.summary.overall_status
    except Exception:
        overall = None

    if not isinstance(overall, str) or not overall:
        overall = "OK"

    payload["overall_status"] = overall
    payload["status"] = overall

    out_path = out_dir / "report.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# -----------------------------
# Builder principal
# -----------------------------


def build_master_report(
    case_id: str,
    *,
    phase1_root: str = "storage/phase1",
    phase2_root: str = "storage/phase2",
) -> MasterReport:
    inputs = _collect_inputs(case_id, phase1_root=phase1_root)

    proposta = _get_input_tuple(inputs, "proposta_daycoval")
    cnh = _get_input_tuple(inputs, "cnh")
    holerite = _get_input_tuple(inputs, "holerite")
    extrato = _get_input_tuple(inputs, "extrato_bancario")

    checks: List[CheckResult] = []

    # Gate1 básico (opcional aqui): proposta + cnh
    has_gate1 = bool(proposta) and bool(cnh)
    checks.append(
        CheckResult(
            id="phase1.required_docs",
            title="Documentos mínimos (Gate 1)",
            status="OK" if has_gate1 else "MISSING",
            expected="proposta_daycoval + cnh",
            found={"proposta_daycoval": bool(proposta), "cnh": bool(cnh)},
            explain="Sem ambos os documentos não é possível executar validações cruzadas.",
            evidence=[],
        )
    )

    if proposta and cnh:
        checks.append(
            _check_field_similarity(
                "proposta_vs_cnh.nome",
                "Nome Proposta ↔ CNH (similaridade)",
                proposta,
                cnh,
                field_left="nome_financiado",
                field_right="nome",
            )
        )

        checks.append(
            _check_field_equal(
                "proposta_vs_cnh.data_nascimento",
                "Data de nascimento Proposta ↔ CNH",
                proposta,
                cnh,
                field_left="data_nascimento",
                field_right="data_nascimento",
                normalize=None,
                missing_is="MISSING",
                mismatch_is="FAIL",
            )
        )

        checks.append(
            _check_field_equal(
                "proposta_vs_cnh.uf",
                "UF Proposta ↔ CNH",
                proposta,
                cnh,
                field_left="uf",
                field_right="uf_nascimento",
                normalize="upper",
                missing_is="MISSING",
                mismatch_is="WARN",
            )
        )

        checks.append(
            _check_field_equal(
                "proposta_vs_cnh.cidade",
                "Cidade Proposta ↔ CNH",
                proposta,
                cnh,
                field_left="cidade_nascimento",
                field_right="cidade_nascimento",
                normalize="upper",
                missing_is="MISSING",
                mismatch_is="WARN",
            )
        )

    # Renda declarada vs comprovada (contrato): SEMPRE emitimos 3 checks.
    # - income.declared_vs_proven.minimum: MISSING quando proposta existe e não há docs de prova; OK quando há.
    # - income.declared_vs_proven.proof: WARN quando há prova mas nenhum campo apurável; OK caso contrário.
    # - income.declared_vs_proven.total: comparação (tolerância 10%) quando houver prova apurável.

    has_proof_docs = bool(holerite) or bool(extrato)

    # 1) minimum
    if proposta is None:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.minimum",
                title="Renda declarada vs comprovada (mínimo)",
                status="MISSING",
                expected="proposta_daycoval + (holerite/contracheque/folha ou extrato)",
                found={
                    "proposta_daycoval": False,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain="Sem proposta não há renda declarada para comparar.",
                evidence=[],
            )
        )
        declared_total = None
        declared_evidence: List[Evidence] = []
        declared_err = "Sem proposta; não há renda declarada."
    else:
        if not has_proof_docs:
            checks.append(
                CheckResult(
                    id="income.declared_vs_proven.minimum",
                    title="Renda declarada vs comprovada (mínimo)",
                    status="MISSING",
                    expected="holerite/contracheque/folha ou extrato",
                    found={
                        "proposta_daycoval": True,
                        "holerite": False,
                        "extrato_bancario": False,
                    },
                    explain="Proposta existe, mas não há documentos de prova (holerite/extrato/folha).",
                    evidence=[],
                )
            )
        else:
            checks.append(
                CheckResult(
                    id="income.declared_vs_proven.minimum",
                    title="Renda declarada vs comprovada (mínimo)",
                    status="OK",
                    expected=">=1 doc de prova",
                    found={"proof_docs": True},
                    explain="Há documento(s) de prova para renda.",
                    evidence=[],
                )
            )

        declared_total, declared_evidence, declared_err = _income_declared_total(proposta)

    # 2) proof
    proven_best, proven_evidence, proven_errs = _income_best_proven(holerite, extrato)
    proof_evidence: List[Evidence] = []
    proof_evidence.extend(proven_evidence)

    if not has_proof_docs:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.proof",
                title="Renda declarada vs comprovada (prova apurável)",
                status="OK",
                expected="(n/a)",
                found={"proof_docs": False},
                explain="Sem documentos de prova; o status MISSING é tratado pelo check income.declared_vs_proven.minimum.",
                evidence=[],
            )
        )
    else:
        if proven_best is None:
            checks.append(
                CheckResult(
                    id="income.declared_vs_proven.proof",
                    title="Renda declarada vs comprovada (prova apurável)",
                    status="WARN",
                    expected="valor apurável em holerite/extrato",
                    found={"proven": None},
                    explain="Há documento de prova, mas nenhum campo apurável foi encontrado. " + " / ".join(proven_errs),
                    evidence=proof_evidence,
                )
            )
        else:
            checks.append(
                CheckResult(
                    id="income.declared_vs_proven.proof",
                    title="Renda declarada vs comprovada (prova apurável)",
                    status="OK",
                    expected="valor apurável em holerite/extrato",
                    found={"proven": proven_best},
                    explain="Documento de prova contém valor apurável.",
                    evidence=proof_evidence,
                )
            )

    # 3) total (só compara quando houver prova apurável)
    total_evidence: List[Evidence] = []
    total_evidence.extend(declared_evidence)
    total_evidence.extend(proven_evidence)

    if declared_total is None:
        # Não duplicamos o MISSING do minimum aqui; total é sobre comparação.
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.total",
                title="Renda declarada vs comprovada (total)",
                status="MISSING",
                expected="renda declarada (salario/outras_rendas)",
                found={"declared_total": None},
                explain=declared_err or "Renda declarada ausente.",
                evidence=total_evidence,
            )
        )
    elif proven_best is None:
        # Não duplicamos o WARN aqui; o WARN é do check proof.
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.total",
                title="Renda declarada vs comprovada (total)",
                status="OK",
                expected=f"{declared_total:.2f}",
                found={"proven": None},
                explain="Sem valor comprovado apurável; comparação não executada (ver income.declared_vs_proven.proof).",
                evidence=total_evidence,
            )
        )
    else:
        checks.append(
            _compare_declared_vs_proven(
                check_id="income.declared_vs_proven.total",
                title="Renda declarada (Proposta) ↔ comprovada (Holerite/Extrato)",
                declared_total=declared_total,
                proven=proven_best,
                evidence=total_evidence,
                tolerance_ratio=0.10,
            )
        )

    summary = _overall_from_checks(checks)

    report = MasterReport(
        case_id=case_id,
        created_at=_utc_iso(),
        inputs={k: {"path": v.get("_path")} for k, v in inputs.items()},
        checks=checks,
        summary=summary,
        debug={
            "phase1_root": phase1_root,
            "phase2_root": phase2_root,
            "version": "phase2-master-report-v2",
            "doc_type_aliases": {
                "holerite": sorted(_HOLERITE_ALIASES),
            },
        },
    )

    save_phase2_report(report, phase2_root=phase2_root)
    return report


def build_master_report_and_return_path(
    case_id: str,
    *,
    phase1_root: str = "storage/phase1",
    phase2_root: str = "storage/phase2",
) -> str:
    report = build_master_report(case_id, phase1_root=phase1_root, phase2_root=phase2_root)
    return str(Path(phase2_root) / case_id / "report.json")


def _main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python -m validators.phase2.master_report <case_id>")
        return 2
    case_id = argv[1]
    p = build_master_report_and_return_path(case_id)
    print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(os.sys.argv))
