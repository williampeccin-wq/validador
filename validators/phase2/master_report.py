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
    # Pelo padrão do seu storage, nomes costumam ser UUIDs; ordenar por mtime é o mais robusto.
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
    # fallback: se o json já é o payload "flat"
    return {k: v for k, v in doc_json.items() if k not in {"debug", "source", "document_type", "documento"}}


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _norm_upper(s: str) -> str:
    return _norm_spaces(s).upper()


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _as_money_str(x: Any) -> Optional[str]:
    """
    Normaliza valores monetários do tipo "3.700,00" ou "3700,00" para string canônica "3700.00" (ponto decimal).
    Retorna None se não der para interpretar.
    """
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None

    # remove moeda e espaços
    s = s.replace("R$", "").replace(" ", "").replace("\u00a0", "")

    # casos como "3.700,00" (pt-BR)
    # remove separador de milhar e troca vírgula por ponto
    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}", s):
        s = s.replace(".", "").replace(",", ".")
        return s

    # casos como "3700,00"
    if re.fullmatch(r"\d+,\d{2}", s):
        s = s.replace(",", ".")
        return s

    # casos como "3700.00"
    if re.fullmatch(r"\d+\.\d{2}", s):
        return s

    # casos como "3700"
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
    Similaridade bem simples (não traz dependências).
    1.0 = igual, 0.0 = totalmente diferente
    """
    a = _norm_upper(a)
    b = _norm_upper(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # Jaccard de tokens
    ta = set(a.split())
    tb = set(b.split())
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _overall_from_checks(checks: List[CheckResult]) -> ReportSummary:
    counts = {"OK": 0, "WARN": 0, "FAIL": 0, "MISSING": 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1

    # Severidade: FAIL > WARN > MISSING > OK
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


def _check_income_declared_vs_proven(
    check_id: str,
    title: str,
    proposta: Tuple[str, Dict[str, Any]],
    holerite: Optional[Tuple[str, Dict[str, Any]]] = None,
    *,
    salario_field: str = "salario",
    outras_rendas_field: str = "outras_rendas",
    holerite_total_field: str = "total_vencimentos",
    tolerance_ratio: float = 0.10,
) -> CheckResult:
    proposta_src, proposta_data = proposta
    declared_sal = _money_to_float(_as_money_str(proposta_data.get(salario_field)))
    declared_outras = _money_to_float(_as_money_str(proposta_data.get(outras_rendas_field)))

    if declared_sal is None and declared_outras is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=None,
            found=None,
            explain="Proposta não possui salário/outras rendas em formato interpretável.",
            evidence=[
                Evidence(source=proposta_src, field=salario_field),
                Evidence(source=proposta_src, field=outras_rendas_field),
            ],
        )

    declared_total = (declared_sal or 0.0) + (declared_outras or 0.0)

    if holerite is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=f"{declared_total:.2f}",
            found=None,
            explain="Holerite ausente; não é possível comprovar renda declarada.",
            evidence=[
                Evidence(source=proposta_src, field=salario_field),
                Evidence(source=proposta_src, field=outras_rendas_field),
            ],
        )

    holerite_src, holerite_data = holerite
    proven = _money_to_float(_as_money_str(holerite_data.get(holerite_total_field)))
    if proven is None:
        return CheckResult(
            id=check_id,
            title=title,
            status="MISSING",
            expected=f"{declared_total:.2f}",
            found=None,
            explain="Holerite presente, mas total_vencimentos não está em formato interpretável.",
            evidence=[
                Evidence(source=holerite_src, field=holerite_total_field),
                Evidence(source=proposta_src, field=salario_field),
                Evidence(source=proposta_src, field=outras_rendas_field),
            ],
        )

    # comparação com tolerância
    # - se declarado_total == 0 e proven > 0: WARN (caso extremo/estranho)
    # - senão, avalia razão de diferença
    if declared_total <= 0.0:
        status = "WARN" if proven > 0 else "OK"
        explain = "Renda declarada total é zero (ou ausente); holerite indica valor. Recomenda-se revisão."
        return CheckResult(
            id=check_id,
            title=title,
            status=status,
            expected=f"{declared_total:.2f}",
            found=f"{proven:.2f}",
            explain=explain,
            evidence=[
                Evidence(source=proposta_src, field=salario_field),
                Evidence(source=proposta_src, field=outras_rendas_field),
                Evidence(source=holerite_src, field=holerite_total_field),
            ],
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
            evidence=[
                Evidence(source=proposta_src, field=salario_field),
                Evidence(source=proposta_src, field=outras_rendas_field),
                Evidence(source=holerite_src, field=holerite_total_field),
            ],
        )

    # diferença grande: WARN se holerite for menor (pode ter descontos / outra base), FAIL se muito discrepante
    if proven < declared_total:
        return CheckResult(
            id=check_id,
            title=title,
            status="WARN",
            expected=f"{declared_total:.2f}",
            found=f"{proven:.2f}",
            explain=f"Renda comprovada menor que declarada (diferença≈{ratio:.2%}). Recomenda-se revisão.",
            evidence=[
                Evidence(source=proposta_src, field=salario_field),
                Evidence(source=proposta_src, field=outras_rendas_field),
                Evidence(source=holerite_src, field=holerite_total_field),
            ],
        )

    return CheckResult(
        id=check_id,
        title=title,
        status="FAIL",
        expected=f"{declared_total:.2f}",
        found=f"{proven:.2f}",
        explain=f"Renda comprovada maior que declarada com discrepância relevante (diferença≈{ratio:.2%}).",
        evidence=[
            Evidence(source=proposta_src, field=salario_field),
            Evidence(source=proposta_src, field=outras_rendas_field),
            Evidence(source=holerite_src, field=holerite_total_field),
        ],
    )


# -----------------------------
# Entrada/saída (storage)
# -----------------------------
def load_phase1_inputs(case_id: str, phase1_root: str = "storage/phase1") -> Dict[str, Dict[str, Any]]:
    """
    Retorna dict por tipo de documento:
      {
        "proposta_daycoval": {"_path": "...json", "_raw": {...}, "_data": {...}},
        "cnh": {...},
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
        out[doc_type_dir.name] = {
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

    # fontes padronizadas
    proposta = None
    cnh = None
    holerite = None

    if "proposta_daycoval" in inputs:
        proposta = ("phase1/proposta_daycoval", inputs["proposta_daycoval"]["_data"])
    if "cnh" in inputs:
        cnh = ("phase1/cnh", inputs["cnh"]["_data"])
    if "holerite" in inputs:
        holerite = ("phase1/holerite", inputs["holerite"]["_data"])

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

        # UF/cidade — tratamos como WARN se divergente
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

    # Renda declarada vs comprovada (por enquanto: proposta x holerite)
    if proposta is None:
        checks.append(
            CheckResult(
                id="income.declared_vs_proven.minimum",
                title="Renda declarada vs comprovada",
                status="MISSING",
                expected="proposta_daycoval (+ holerite opcional)",
                found={"proposta_daycoval": False, "holerite": bool(holerite)},
                explain="Sem proposta não há renda declarada para comparar.",
                evidence=[],
            )
        )
    else:
        checks.append(
            _check_income_declared_vs_proven(
                "income.declared_vs_proven.proposta_holerite",
                "Renda declarada (Proposta) ↔ comprovada (Holerite)",
                proposta,
                holerite=holerite,
            )
        )

    summary = _overall_from_checks(checks)

    report = MasterReport(
        case_id=case_id,
        created_at=_utc_iso(),
        inputs={
            k: {"path": v.get("_path")} for k, v in inputs.items()
        },
        checks=checks,
        summary=summary,
        debug={
            "phase1_root": phase1_root,
            "phase2_root": phase2_root,
            "version": "phase2-master-report-v1",
        },
    )

    # persistência
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


# Conveniência CLI: python -m validators.phase2.master_report <case_id>
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
