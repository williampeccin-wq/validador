from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ======================================================================================
# Master Report (Phase 2) — agregador explicável
#
# Regras do projeto:
# - Não bloquear parsing/extração (Phase 1).
# - Phase 2 roda APENAS depois que documentos foram coletados e persistidos.
# - Output determinístico, explicável, sem "mágica" e sem depender de OCR/texto bruto.
#
# Nota de domínio:
# - "folha de pagamento", "contracheque" e "holerite" são o mesmo documento (preferimos "holerite").
#   Neste master_report, qualquer nomenclatura vira "holerite" como tipo lógico.
# ======================================================================================


# -----------------------------
# Tipos
# -----------------------------
Status = str  # "OK" | "WARN" | "FAIL" | "MISSING"


@dataclass(frozen=True)
class Evidence:
    """Onde veio o dado (sem vazar texto inteiro)."""
    source: str  # ex: "phase1/proposta_daycoval" | "phase1/cnh"
    field: str   # ex: "cpf" | "nome" | "salario"


@dataclass(frozen=True)
class CheckResult:
    id: str
    title: str
    status: Status
    expected: Optional[Any] = None
    found: Optional[Any] = None
    explain: str = ""
    evidence: List[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class ReportSummary:
    overall_status: Status
    counts: Dict[str, int]


@dataclass(frozen=True)
class MasterReport:
    case_id: str
    created_at: str
    inputs: Dict[str, Any]
    checks: List[CheckResult]
    summary: ReportSummary
    debug: Dict[str, Any] = field(default_factory=dict)


# -----------------------------
# Utilitários
# -----------------------------
def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _pick_latest_json(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return None
    candidates = sorted(dir_path.glob("*.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]


def _extract_data(doc_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 1 costuma persistir algo como:
      { "document_type": "...", "data": {...}, "debug": {...}, ... }
    Mas este helper tolera variações.
    """
    if isinstance(doc_json.get("data"), dict):
        return doc_json["data"]
    return {k: v for k, v in doc_json.items() if k not in {"debug", "source", "document_type", "documento"}}


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _norm_upper(s: str) -> str:
    return _norm_spaces(s).upper()


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _as_money_str(x: Any) -> Optional[str]:
    """
    Normaliza valores monetários do tipo "3.700,00" ou "3700,00" para string canônica "3700.00".
    Retorna None se não der para interpretar.
    """
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None

    s = s.replace("R$", "").replace(" ", "").replace("\u00a0", "")

    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}", s):
        s = s.replace(".", "").replace(",", ".")
        return s

    if re.fullmatch(r"\d+,\d{2}", s):
        s = s.replace(",", ".")
        return s

    if re.fullmatch(r"\d+\.\d{2}", s):
        return s

    if re.fullmatch(r"\d+", s):
        return s + ".00"

    return None


def _money_to_float(m: Optional[str]) -> Optional[float]:
    if not m:
        return None
    try:
        return float(m)
    except Exception:
        return None


def _diff_ratio(a: str, b: str) -> float:
    """
    Similaridade simples (sem dependências).
    1.0 = igual, 0.0 = totalmente diferente.
    """
    a = _norm_upper(a)
    b = _norm_upper(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    ta = set(a.split())
    tb = set(b.split())
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _overall_from_checks(checks: List[CheckResult]) -> ReportSummary:
    counts = {"OK": 0, "WARN": 0, "FAIL": 0, "MISSING": 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1

    if counts.get("FAIL", 0) > 0:
        overall = "FAIL"
    elif counts.get("WARN", 0) > 0:
        overall = "WARN"
    elif counts.get("MISSING", 0) > 0:
        overall = "MISSING"
    else:
        overall = "OK"

    return ReportSummary(overall_status=overall, counts=counts)


# -----------------------------
# Aliases de tipos (Phase 1 -> tipo lógico)
# -----------------------------
_HOLERITE_ALIASES = {
    "holerite",
    "folha_pagamento",
    "folha_de_pagamento",
    "folha_pgto",
    "folha",
    "contracheque",
    "contra_cheque",
    "contra-cheque",
    "recibo_pagamento_salario",
    "recibo_de_pagamento",
}


def _normalize_doc_type(doc_type: str) -> str:
    dt = (doc_type or "").strip().lower()
    if dt in _HOLERITE_ALIASES:
        return "holerite"
    return dt


def _get_doc(inputs: Dict[str, Dict[str, Any]], *doc_types: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Retorna (source, data) do primeiro doc_type encontrado (aceita alias).
    doc_types devem ser do tipo lógico, ex: "holerite", "extrato_bancario".
    """
    for dt in doc_types:
        if dt in inputs:
            return (f"phase1/{dt}", inputs[dt]["_data"])
    return None


# -----------------------------
# Checks (regras iniciais)
# -----------------------------
def _check_field_equal(
    check_id: str,
    title: str,
    left: Tuple[str, Dict[str, Any]],
    right: Tuple[str, Dict[str, Any]],
    field_left: str,
    field_right: str,
    *,
    normalize: Optional[str] = None,  # "digits" | "upper" | None
    missing_is: Status = "MISSING",
    mismatch_is: Status = "FAIL",
) -> CheckResult:
    left_src, left_data = left
    right_src, right_data = right

    a = left_data.get(field_left)
    b = right_data.get(field_right)

    if a is None or b is None:
        explain = f"Campo ausente: {'left' if a is None else ''}{' e ' if (a is None and b is None) else ''}{'right' if b is None else ''}".strip()
        return CheckResult(
            id=check_id,
            title=title,
            status=missing_is,
            expected=a,
            found=b,
            explain=explain,
            evidence=[
                Evidence(source=left_src, field=field_left),
                Evidence(source=right_src, field=field_right),
            ],
        )

    if normalize == "digits":
        aa = _digits_only(str(a))
        bb = _digits_only(str(b))
    elif normalize == "upper":
        aa = _norm_upper(str(a))
        bb = _norm_upper(str(b))
    else:
        aa = str(a)
        bb = str(b)

    if aa == bb:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=aa,
            found=bb,
            explain="Campos compatíveis.",
            evidence=[
                Evidence(source=left_src, field=field_left),
                Evidence(source=right_src, field=field_right),
            ],
        )

    return CheckResult(
        id=check_id,
        title=title,
        status=mismatch_is,
        expected=aa,
        found=bb,
        explain="Divergência entre documentos.",
        evidence=[
            Evidence(source=left_src, field=field_left),
            Evidence(source=right_src, field=field_right),
        ],
    )


def _check_name_soft(
    check_id: str,
    title: str,
    left: Tuple[str, Dict[str, Any]],
    right: Tuple[str, Dict[str, Any]],
    field_left: str,
    field_right: str,
    *,
    warn_threshold: float = 0.75,
) -> CheckResult:
    left_src, left_data = left
    right_src, right_data = right

    a = left_data.get(field_left)
    b = right_data.get(field_right)

    if a is None or b is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=a,
            found=b,
            explain="Nome ausente em um dos documentos; não é possível comparar.",
            evidence=[
                Evidence(source=left_src, field=field_left),
                Evidence(source=right_src, field=field_right),
            ],
        )

    aa = _norm_upper(str(a))
    bb = _norm_upper(str(b))

    if aa == bb:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=aa,
            found=bb,
            explain="Nomes idênticos após normalização.",
            evidence=[
                Evidence(source=left_src, field=field_left),
                Evidence(source=right_src, field=field_right),
            ],
        )

    ratio = _diff_ratio(aa, bb)
    if ratio >= warn_threshold:
        return CheckResult(
            id=check_id,
            title=title,
            status="WARN",
            expected=aa,
            found=bb,
            explain=f"Nomes similares (similaridade≈{ratio:.2f}). Recomenda-se revisão humana.",
            evidence=[
                Evidence(source=left_src, field=field_left),
                Evidence(source=right_src, field=field_right),
            ],
        )

    return CheckResult(
        id=check_id,
        title=title,
        status="FAIL",
        expected=aa,
        found=bb,
        explain=f"Nomes divergentes (similaridade≈{ratio:.2f}).",
        evidence=[
            Evidence(source=left_src, field=field_left),
            Evidence(source=right_src, field=field_right),
        ],
    )


def _compute_declared_income_total(
    proposta_src: str,
    proposta_data: Dict[str, Any],
    *,
    salario_field: str = "salario",
    outras_rendas_field: str = "outras_rendas",
) -> Tuple[Optional[float], List[Evidence], str]:
    declared_sal = _money_to_float(_as_money_str(proposta_data.get(salario_field)))
    declared_outras = _money_to_float(_as_money_str(proposta_data.get(outras_rendas_field)))

    evidence = [
        Evidence(source=proposta_src, field=salario_field),
        Evidence(source=proposta_src, field=outras_rendas_field),
    ]

    if declared_sal is None and declared_outras is None:
        return None, evidence, "Proposta não possui salário/outras rendas em formato interpretável."

    declared_total = (declared_sal or 0.0) + (declared_outras or 0.0)
    return declared_total, evidence, ""


def _compute_proven_income_from_holerite(
    holerite_src: str,
    holerite_data: Dict[str, Any],
    *,
    holerite_total_field: str = "total_vencimentos",
) -> Tuple[Optional[float], List[Evidence], str]:
    proven = _money_to_float(_as_money_str(holerite_data.get(holerite_total_field)))
    evidence = [Evidence(source=holerite_src, field=holerite_total_field)]
    if proven is None:
        return None, evidence, "Holerite presente, mas total_vencimentos não está em formato interpretável."
    return proven, evidence, ""


def _compute_proven_income_from_extrato(
    extrato_src: str,
    extrato_data: Dict[str, Any],
) -> Tuple[Optional[float], List[Evidence], str]:
    """
    Extrato é inerentemente mais variado.
    Aqui tentamos APENAS campos agregados que o parser eventualmente já produza.
    Se não existir, tratamos como "prova presente, mas valor inapreensível" (WARN).
    """
    candidate_fields = [
        "renda_mensal",
        "media_creditos",
        "media_creditos_validos",
        "media_entradas",
        "media_depositos",
        "total_creditos",
        "total_creditos_validos",
    ]

    for f in candidate_fields:
        v = _money_to_float(_as_money_str(extrato_data.get(f)))
        if v is not None:
            return v, [Evidence(source=extrato_src, field=f)], ""

    return None, [Evidence(source=extrato_src, field="(agregados)")], "Extrato presente, mas não há campo agregado interpretável para renda."


def _compare_declared_vs_proven(
    check_id: str,
    title: str,
    *,
    declared_total: float,
    proven: float,
    evidence: List[Evidence],
    tolerance_ratio: float = 0.10,
) -> CheckResult:
    if declared_total <= 0.0:
        status = "WARN" if proven > 0 else "OK"
        explain = "Renda declarada total é zero (ou ausente); comprovante indica valor. Recomenda-se revisão."
        return CheckResult(
            id=check_id,
            title=title,
            status=status,
            expected=f"{declared_total:.2f}",
            found=f"{proven:.2f}",
            explain=explain,
            evidence=evidence,
        )

    diff = abs(proven - declared_total)
    ratio = diff / declared_total

    if ratio <= tolerance_ratio:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=f"{declared_total:.2f}",
            found=f"{proven:.2f}",
            explain=f"Renda comprovada compatível (diferença≈{ratio:.2%}).",
            evidence=evidence,
        )

    if proven < declared_total:
        return CheckResult(
            id=check_id,
            title=title,
            status="WARN",
            expected=f"{declared_total:.2f}",
            found=f"{proven:.2f}",
            explain=f"Renda comprovada menor que declarada (diferença≈{ratio:.2%}). Recomenda-se revisão.",
            evidence=evidence,
        )

    return CheckResult(
        id=check_id,
        title=title,
        status="FAIL",
        expected=f"{declared_total:.2f}",
        found=f"{proven:.2f}",
        explain=f"Renda comprovada maior que declarada com discrepância relevante (diferença≈{ratio:.2%}).",
        evidence=evidence,
    )


def _check_income_declared_vs_proven_any_proof(
    check_id: str,
    title: str,
    proposta: Tuple[str, Dict[str, Any]],
    holerite: Optional[Tuple[str, Dict[str, Any]]],
    extrato: Optional[Tuple[str, Dict[str, Any]]],
    *,
    tolerance_ratio: float = 0.10,
) -> CheckResult:
    proposta_src, proposta_data = proposta

    declared_total, declared_evidence, declared_err = _compute_declared_income_total(proposta_src, proposta_data)
    if declared_total is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=None,
            found=None,
            explain=declared_err or "Renda declarada inapreensível na proposta.",
            evidence=declared_evidence,
        )

    # nenhum comprovante => MISSING (essa é a regra que você pediu)
    if holerite is None and extrato is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=f"{declared_total:.2f}",
            found=None,
            explain="Nenhum comprovante de renda presente (holerite/contracheque/folha ou extrato).",
            evidence=declared_evidence,
        )

    # Prioridade: holerite (mais determinístico), senão extrato
    proven = None
    evidence: List[Evidence] = list(declared_evidence)
    explain_parts: List[str] = []

    if holerite is not None:
        hol_src, hol_data = holerite
        prov_h, ev_h, err_h = _compute_proven_income_from_holerite(hol_src, hol_data)
        evidence.extend(ev_h)
        if prov_h is not None:
            proven = prov_h
        else:
            explain_parts.append(err_h)

    if proven is None and extrato is not None:
        ex_src, ex_data = extrato
        prov_e, ev_e, err_e = _compute_proven_income_from_extrato(ex_src, ex_data)
        evidence.extend(ev_e)
        if prov_e is not None:
            proven = prov_e
        else:
            explain_parts.append(err_e)

    # há comprovante(s), mas nenhum valor apurável => WARN (não MISSING)
    if proven is None:
        present = []
        if holerite is not None:
            present.append("holerite")
        if extrato is not None:
            present.append("extrato_bancario")
        explain = "Comprovante(s) presente(s), mas não foi possível apurar valor: " + "; ".join([p for p in explain_parts if p])
        if not explain_parts:
            explain = "Comprovante(s) presente(s), mas não foi possível apurar valor."
        return CheckResult(
            id=check_id,
            title=title,
            status="WARN",
            expected=f"{declared_total:.2f}",
            found={"present": present},
            explain=explain,
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


# -----------------------------
# Entrada/saída (storage)
# -----------------------------
def load_phase1_inputs(case_id: str, phase1_root: str = "storage/phase1") -> Dict[str, Dict[str, Any]]:
    """
    Retorna dict por tipo de documento (tipo lógico):
      {
        "proposta_daycoval": {"_path": "...json", "_raw": {...}, "_data": {...}},
        "cnh": {...},
        "holerite": {...},              # inclui aliases (folha/contracheque)
        "extrato_bancario": {...},
        ...
      }
    """
    base = Path(phase1_root) / case_id
    if not base.exists():
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for doc_type_dir in sorted([p for p in base.iterdir() if p.is_dir()]):
        latest = _pick_latest_json(doc_type_dir)
        if not latest:
            continue

        raw = _safe_read_json(latest)
        data = _extract_data(raw)

        logical_type = _normalize_doc_type(doc_type_dir.name)

        # Se um alias e "holerite" existirem simultaneamente, preferimos o mais recente (mtime),
        # mas como percorremos dirs em ordem e usamos mtime por dir, precisamos comparar aqui.
        if logical_type in out:
            prev_path = Path(out[logical_type]["_path"])
            try:
                if latest.stat().st_mtime <= prev_path.stat().st_mtime:
                    continue
            except Exception:
                pass

        out[logical_type] = {
            "_path": str(latest),
            "_raw": raw,
            "_data": data,
        }

    return out


def save_phase2_report(report: MasterReport, phase2_root: str = "storage/phase2") -> Path:
    base = Path(phase2_root) / report.case_id
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / "report.json"

    payload = asdict(report)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# -----------------------------
# Orquestração principal
# -----------------------------
def build_master_report(
    case_id: str,
    *,
    phase1_root: str = "storage/phase1",
    phase2_root: str = "storage/phase2",
) -> MasterReport:
    inputs = load_phase1_inputs(case_id, phase1_root=phase1_root)

    # fontes padronizadas (tipo lógico)
    proposta = _get_doc(inputs, "proposta_daycoval")
    cnh = _get_doc(inputs, "cnh")
    holerite = _get_doc(inputs, "holerite")
    extrato = _get_doc(inputs, "extrato_bancario")

    checks: List[CheckResult] = []

    # Proposta x CNH
    if proposta is None or cnh is None:
        checks.append(
            CheckResult(
                id="proposta_vs_cnh.minimum",
                title="Documentos mínimos para comparação Proposta ↔ CNH",
                status="MISSING",
                expected="proposta_daycoval + cnh",
                found={
                    "proposta_daycoval": bool(proposta),
                    "cnh": bool(cnh),
                },
                explain="Necessário ter Proposta e CNH persistidos no Phase 1 para rodar comparações.",
                evidence=[],
            )
        )
    else:
        checks.append(
            _check_field_equal(
                "proposta_vs_cnh.cpf",
                "CPF Proposta ↔ CNH",
                proposta,
                cnh,
                field_left="cpf",
                field_right="cpf",
                normalize="digits",
                missing_is="MISSING",
                mismatch_is="FAIL",
            )
        )

        checks.append(
            _check_name_soft(
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

    # Renda declarada vs comprovada
    # Regra: MISSING só quando não existir NENHUM comprovante (holerite OU extrato).
    if proposta is None:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.minimum",
                title="Renda declarada vs comprovada",
                status="MISSING",
                expected="proposta_daycoval (+ holerite/extrato opcional)",
                found={
                    "proposta_daycoval": False,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain="Sem proposta não há renda declarada para comparar.",
                evidence=[],
            )
        )
    else:
        checks.append(
            _check_income_declared_vs_proven_any_proof(
                "income.declared_vs_proven.proposta_provas",
                "Renda declarada (Proposta) ↔ comprovada (Holerite/Extrato)",
                proposta=proposta,
                holerite=holerite,
                extrato=extrato,
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
