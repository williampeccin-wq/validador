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
# - Validações cruzadas e inferências (Phase 2) só devem rodar depois que TODOS os documentos
#   forem coletados; durante parsing/extração não bloquear nem concluir.
#
# Este módulo agrega outputs da Phase 1 (JSONs em storage/phase1/<case_id>/...)
# e gera um report único em storage/phase2/<case_id>/report.json
# ======================================================================================

Status = str  # "OK" | "WARN" | "FAIL" | "MISSING"


@dataclass(frozen=True)
class Evidence:
    source: str
    field: str  # ex: "cpf" | "nome" | "salario"


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
    counts: Dict[Status, int] = field(default_factory=dict)


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
    return datetime.now(timezone.utc).isoformat()


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick_latest_json(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists():
        return None
    files = sorted([p for p in dir_path.glob("*.json") if p.is_file()], key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _extract_data(doc_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 1 tende a salvar:
      {"data": {...}, "debug": {...}, "source": {...}}
    Mas os testes da Phase 2 podem gravar payloads minimalistas.
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


def _as_money_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)


def _money_to_float(v: str) -> Optional[float]:
    """
    Aceita '6.700,00', '6700,00', '6700.00', '6700'
    """
    s = (v or "").strip()
    if not s:
        return None

    # remove currency/whitespace
    s = re.sub(r"[Rr]\$|\s", "", s)

    # se tiver vírgula e ponto, assume ponto milhar e vírgula decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    # else: já está com '.'

    try:
        return float(s)
    except Exception:
        return None


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
    *,
    field_left: str,
    field_right: str,
    normalize: Optional[Any] = None,
    missing_is: Status = "WARN",
    mismatch_is: Status = "WARN",
) -> CheckResult:
    left_src, left_data = left
    right_src, right_data = right

    lv = left_data.get(field_left)
    rv = right_data.get(field_right)

    nl = normalize(lv) if (normalize and lv is not None) else lv
    nr = normalize(rv) if (normalize and rv is not None) else rv

    evidence = [Evidence(source=left_src, field=field_left), Evidence(source=right_src, field=field_right)]

    if lv is None or rv is None:
        return CheckResult(
            id=check_id,
            title=title,
            status=missing_is,
            expected="both present",
            found={"left": lv, "right": rv},
            explain="Campo ausente em um dos documentos; não é possível comparar com segurança.",
            evidence=evidence,
        )

    if nl == nr:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=nl,
            found=nr,
            explain="Valores compatíveis.",
            evidence=evidence,
        )

    return CheckResult(
        id=check_id,
        title=title,
        status=mismatch_is,
        expected=nl,
        found=nr,
        explain="Valores divergentes entre documentos.",
        evidence=evidence,
    )


def _check_name_similarity(
    check_id: str,
    title: str,
    left: Tuple[str, Dict[str, Any]],
    right: Tuple[str, Dict[str, Any]],
    *,
    field_left: str,
    field_right: str,
) -> CheckResult:
    left_src, left_data = left
    right_src, right_data = right

    lv = _norm_upper(str(left_data.get(field_left) or ""))
    rv = _norm_upper(str(right_data.get(field_right) or ""))

    evidence = [Evidence(source=left_src, field=field_left), Evidence(source=right_src, field=field_right)]

    if not lv or not rv:
        return CheckResult(
            id=check_id,
            title=title,
            status="WARN",
            expected="both present",
            found={"left": lv, "right": rv},
            explain="Nome ausente em um dos documentos; não é possível comparar com segurança.",
            evidence=evidence,
        )

    # comparação simples (não precisa ser perfeita para o teste atual)
    if lv == rv:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=lv,
            found=rv,
            explain="Nomes idênticos após normalização.",
            evidence=evidence,
        )

    return CheckResult(
        id=check_id,
        title=title,
        status="WARN",
        expected=lv,
        found=rv,
        explain="Nomes diferentes após normalização (similaridade simples).",
        evidence=evidence,
    )


def _compute_declared_income_total(
    proposta_src: str,
    proposta_data: Dict[str, Any],
) -> Tuple[Optional[float], List[Evidence], str]:
    """
    Renda declarada: usa campos comuns da proposta.
    - salario
    - outras_rendas
    - renda_total (se existir)
    """
    evidence: List[Evidence] = []
    for f in ("renda_total", "salario", "outras_rendas"):
        if f in proposta_data:
            evidence.append(Evidence(source=proposta_src, field=f))

    if proposta_data.get("renda_total") is not None:
        total = _money_to_float(_as_money_str(proposta_data.get("renda_total")))
        if total is None:
            return None, evidence, "Campo renda_total presente, mas não interpretável."
        return total, evidence, ""

    salario = _money_to_float(_as_money_str(proposta_data.get("salario")))
    outras = _money_to_float(_as_money_str(proposta_data.get("outras_rendas")))

    if salario is None and outras is None:
        return None, evidence, "Campos de renda declarada (salario/outras_rendas) ausentes ou não interpretáveis."

    declared_total = float(salario or 0.0) + float(outras or 0.0)
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
    Extrato: para Phase 2 (income proof rules), os campos aceitos como "apuráveis" são os esperados pelo teste:
      - renda_apurada
      - renda_recorrente
      - creditos_recorrentes_total
      - creditos_validos_total
    """
    candidate_fields = [
        "renda_apurada",
        "renda_recorrente",
        "creditos_recorrentes_total",
        "creditos_validos_total",
    ]

    for f in candidate_fields:
        v = _money_to_float(_as_money_str(extrato_data.get(f)))
        if v is not None:
            return v, [Evidence(source=extrato_src, field=f)], ""

    return None, [Evidence(source=extrato_src, field="(renda_apurada/renda_recorrente/creditos_*)")], (
        "Extrato presente, mas sem qualquer um dos campos apuráveis "
        "(renda_apurada / renda_recorrente / creditos_recorrentes_total / creditos_validos_total)."
    )


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
            expected=declared_total,
            found=proven,
            explain=explain,
            evidence=evidence,
        )

    delta = abs(proven - declared_total)
    ratio = delta / declared_total if declared_total else 1.0

    if ratio <= tolerance_ratio:
        return CheckResult(
            id=check_id,
            title=title,
            status="OK",
            expected=f"{declared_total:.2f}",
            found=f"{proven:.2f}",
            explain=f"Compatível dentro da tolerância ({tolerance_ratio:.0%}).",
            evidence=evidence,
        )

    return CheckResult(
        id=check_id,
        title=title,
        status="WARN",
        expected=f"{declared_total:.2f}",
        found=f"{proven:.2f}",
        explain=f"Diferença relevante (diferença≈{ratio:.2%}).",
        evidence=evidence,
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
    p = base / "report.json"
    p.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# -----------------------------
# Builder principal
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
                explain="Sem ambos os documentos não é possível executar validações cruzadas.",
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
                normalize=_digits_only,
                missing_is="MISSING",
                mismatch_is="FAIL",
            )
        )

        checks.append(
            _check_name_similarity(
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
                normalize=_norm_upper,
                missing_is="WARN",
                mismatch_is="WARN",
            )
        )

        checks.append(
            _check_field_equal(
                "proposta_vs_cnh.cidade_nascimento",
                "Cidade nascimento Proposta ↔ CNH",
                proposta,
                cnh,
                field_left="cidade_nascimento",
                field_right="cidade_nascimento",
                normalize=_norm_upper,
                missing_is="WARN",
                mismatch_is="WARN",
            )
        )

    # Renda declarada vs comprovada — SEMPRE emitir 3 checks:
    #   1) income.declared_vs_proven.minimum
    #   2) income.declared_vs_proven.proof
    #   3) income.declared_vs_proven.total
    #
    # Regras (tests/test_phase2_master_report_income_proof_rules.py):
    # - minimum: MISSING quando proposta existe e NÃO há docs de prova (holerite/extrato/folha); OK quando há.
    # - proof: WARN quando há doc de prova mas nenhum campo apurável; OK caso contrário.
    # - total: comparação declarado vs comprovado (tolerância 10%) SOMENTE quando houver prova apurável.
    proof_present = not (holerite is None and extrato is None)

    proven_val: Optional[float] = None
    proven_evidence: List[Evidence] = []
    proven_notes: List[str] = []

    # prioridade: holerite (ou folha/contracheque aliasado como holerite)
    if holerite is not None:
        h_src, h_data = holerite
        v, ev, err = _compute_proven_income_from_holerite(h_src, h_data)
        proven_evidence.extend(ev)
        if v is not None:
            proven_val = v
        elif err:
            proven_notes.append(err)

    # depois: extrato (apenas se holerite não apurou)
    if proven_val is None and extrato is not None:
        e_src, e_data = extrato
        v, ev, err = _compute_proven_income_from_extrato(e_src, e_data)
        proven_evidence.extend(ev)
        if v is not None:
            proven_val = v
        elif err:
            proven_notes.append(err)

    apuravel = proven_val is not None

    # 1) minimum
    if proposta is None:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.minimum",
                title="Renda declarada vs comprovada — mínimos",
                status="MISSING",
                expected="proposta_daycoval",
                found={
                    "proposta_daycoval": False,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain="Sem proposta não há renda declarada para comparar.",
                evidence=[],
            )
        )
    elif not proof_present:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.minimum",
                title="Renda declarada vs comprovada — mínimos",
                status="MISSING",
                expected="ao menos 1 comprovante (holerite/extrato/folha)",
                found={
                    "proposta_daycoval": True,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain="Proposta existe, mas não há nenhum documento de prova de renda (holerite/extrato/folha).",
                evidence=[],
            )
        )
    else:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.minimum",
                title="Renda declarada vs comprovada — mínimos",
                status="OK",
                expected="ao menos 1 comprovante (holerite/extrato/folha)",
                found={
                    "proposta_daycoval": True,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain="Há proposta e ao menos um documento de prova de renda.",
                evidence=[],
            )
        )

    # 2) proof
    if not proof_present:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.proof",
                title="Renda comprovada — apuração",
                status="OK",
                expected="(n/a)",
                found={"proof_docs": False},
                explain="Sem documentos de prova; o status MISSING é tratado pelo check income.declared_vs_proven.minimum.",
                evidence=[],
            )
        )
    elif not apuravel:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.proof",
                title="Renda comprovada — apuração",
                status="WARN",
                expected="ao menos 1 campo de renda interpretável",
                found={
                    "proof_docs": True,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain=(
                    "Há documento(s) de prova, mas nenhum campo de renda apurável foi encontrado."
                    + ((" " + " | ".join(proven_notes)) if proven_notes else "")
                ),
                evidence=proven_evidence,
            )
        )
    else:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.proof",
                title="Renda comprovada — apuração",
                status="OK",
                expected="ao menos 1 campo de renda interpretável",
                found={
                    "proof_docs": True,
                    "holerite": bool(holerite),
                    "extrato_bancario": bool(extrato),
                },
                explain="Há documento(s) de prova com campo(s) de renda interpretável(is).",
                evidence=proven_evidence,
            )
        )

    # 3) total
    if proposta is None:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.total",
                title="Renda declarada (Proposta) ↔ comprovada (Total)",
                status="MISSING",
                expected="proposta_daycoval",
                found={"proposta_daycoval": False},
                explain="Sem proposta não há renda declarada para comparar.",
                evidence=[],
            )
        )
    else:
        proposta_src, proposta_data = proposta
        declared_total, declared_evidence, declared_err = _compute_declared_income_total(proposta_src, proposta_data)
        if declared_total is None:
            checks.append(
                CheckResult(
                    id="income.declared_vs_proven.total",
                    title="Renda declarada (Proposta) ↔ comprovada (Total)",
                    status="WARN",
                    expected="renda declarada interpretável",
                    found={"declared_total": None},
                    explain=declared_err or "Renda declarada inapreensível na proposta.",
                    evidence=declared_evidence,
                )
            )
        elif not apuravel:
            checks.append(
                CheckResult(
                    id="income.declared_vs_proven.total",
                    title="Renda declarada (Proposta) ↔ comprovada (Total)",
                    status="OK",
                    expected=f"{declared_total:.2f}",
                    found={"proven_total": None, "proof_docs": proof_present},
                    explain="Sem renda comprovada apurável; comparação não executada (ver income.declared_vs_proven.proof).",
                    evidence=(list(declared_evidence) + list(proven_evidence)),
                )
            )
        else:
            checks.append(
                _compare_declared_vs_proven(
                    check_id="income.declared_vs_proven.total",
                    title="Renda declarada (Proposta) ↔ comprovada (Total)",
                    declared_total=declared_total,
                    proven=float(proven_val or 0.0),
                    evidence=(list(declared_evidence) + list(proven_evidence)),
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
