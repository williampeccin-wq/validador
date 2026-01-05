from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Normalização (explicável e determinística)
# =============================================================================

def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    v = _strip_accents(v)
    v = re.sub(r"\s+", " ", v)
    v = v.upper()
    # remove caracteres não alfanuméricos (mantém espaço)
    v = re.sub(r"[^A-Z0-9 ]+", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def normalize_cpf(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"\D+", "", value)
    if not digits:
        return None
    # Se vier com 10/12/.., não inventa: reporta como está (mas normalizado em dígitos)
    return digits


def normalize_date_to_iso(value: Optional[str]) -> Optional[str]:
    """
    Aceita formatos comuns da Fase 1:
    - DD/MM/YYYY
    - YYYY-MM-DD
    - strings com espaços
    Retorna ISO YYYY-MM-DD ou None se inválida.
    """
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None

    # Tenta YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass

    # Tenta DD/MM/YYYY e variações
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass

    # Se vier com hora junto (ex: 2024-08-01 00:00:00)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T].+$", v)
    if m:
        return m.group(1)

    return None


# =============================================================================
# Mapeamento de campos (onde buscar em cada documento)
# =============================================================================

@dataclass(frozen=True)
class FieldSpec:
    """
    Define como encontrar um campo em cada documento e como normalizá-lo.
    - key: nome canônico do campo no relatório
    - proposta_paths: caminhos (dot-notation) onde tentar ler na proposta
    - cnh_paths: caminhos (dot-notation) onde tentar ler na CNH
    - normalizer: função de normalização
    - comparable_when_missing: se False, campo vira not_comparable quando falta um lado
    """
    key: str
    proposta_paths: Tuple[str, ...]
    cnh_paths: Tuple[str, ...]
    normalizer: Any
    comparable_when_missing: bool = True


DEFAULT_FIELD_SPECS: Tuple[FieldSpec, ...] = (
    FieldSpec(
        key="cpf",
        proposta_paths=("cpf", "cpf_financiado", "documentos.cpf"),
        cnh_paths=("cpf", "documento.cpf", "dados.cpf"),
        normalizer=normalize_cpf,
        comparable_when_missing=True,
    ),
    FieldSpec(
        key="nome",
        proposta_paths=("nome_financiado", "nome", "cliente.nome"),
        cnh_paths=("nome", "nome_completo", "documento.nome"),
        normalizer=normalize_name,
        comparable_when_missing=True,
    ),
    FieldSpec(
        key="data_nascimento",
        proposta_paths=("data_nascimento", "nascimento", "cliente.data_nascimento"),
        cnh_paths=("data_nascimento", "nascimento", "documento.data_nascimento"),
        normalizer=normalize_date_to_iso,
        comparable_when_missing=True,
    ),
)


# =============================================================================
# Utilitários de leitura por path
# =============================================================================

def _get_by_dot_path(obj: Dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur


def _first_present(obj: Dict[str, Any], paths: Tuple[str, ...]) -> Tuple[Optional[str], Optional[Any]]:
    """
    Retorna (path_usado, valor) do primeiro path que existir com valor não-vazio.
    """
    for p in paths:
        raw = _get_by_dot_path(obj, p)
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        return p, raw
    return None, None


# =============================================================================
# Relatório
# =============================================================================

def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    # Para qualquer outro tipo, serializa simples
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def _is_effectively_missing(v: Optional[str]) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def build_proposta_cnh_report(
    *,
    case_id: str,
    proposta_data: Dict[str, Any],
    cnh_data: Dict[str, Any],
    field_specs: Tuple[FieldSpec, ...] = DEFAULT_FIELD_SPECS,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Gera um relatório sem decisões automáticas.
    - Não lança para divergência.
    - Lista campos comparáveis, iguais e divergentes.
    """
    comparable: List[Dict[str, Any]] = []
    iguais: List[Dict[str, Any]] = []
    divergentes: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    not_comparable: List[Dict[str, Any]] = []

    for spec in field_specs:
        p_path, p_raw = _first_present(proposta_data, spec.proposta_paths)
        c_path, c_raw = _first_present(cnh_data, spec.cnh_paths)

        p_raw_s = _safe_str(p_raw)
        c_raw_s = _safe_str(c_raw)

        p_norm = spec.normalizer(p_raw_s) if p_raw_s is not None else None
        c_norm = spec.normalizer(c_raw_s) if c_raw_s is not None else None

        entry = {
            "field": spec.key,
            "proposta": {
                "path": p_path,
                "raw": p_raw_s,
                "normalized": p_norm,
            },
            "cnh": {
                "path": c_path,
                "raw": c_raw_s,
                "normalized": c_norm,
            },
            "status": None,          # preenchido abaixo
            "explain": None,         # preenchido abaixo
        }

        # Regras de comparabilidade
        p_missing = _is_effectively_missing(p_norm)
        c_missing = _is_effectively_missing(c_norm)

        if (p_missing or c_missing) and not spec.comparable_when_missing:
            entry["status"] = "not_comparable"
            entry["explain"] = "Campo não comparável porque está ausente em um dos documentos (configuração do campo)."
            not_comparable.append(entry)
            continue

        # Se falta em ambos -> missing (não é divergência)
        if p_missing and c_missing:
            entry["status"] = "missing"
            entry["explain"] = "Campo ausente nos dois documentos (após normalização)."
            missing.append(entry)
            continue

        # Se falta em um lado -> missing (comparável, mas incompleto)
        if p_missing and not c_missing:
            entry["status"] = "missing"
            entry["explain"] = "Campo ausente na Proposta (após normalização) e presente na CNH."
            missing.append(entry)
            continue

        if c_missing and not p_missing:
            entry["status"] = "missing"
            entry["explain"] = "Campo ausente na CNH (após normalização) e presente na Proposta."
            missing.append(entry)
            continue

        # Ambos presentes -> comparável
        comparable.append(entry)

        if p_norm == c_norm:
            entry["status"] = "equal"
            entry["explain"] = "Valores coincidem após normalização."
            iguais.append(entry)
        else:
            entry["status"] = "different"
            entry["explain"] = "Valores divergem após normalização."
            divergentes.append(entry)

    report = {
        "case_id": case_id,
        "validator": "proposta_vs_cnh",
        "version": "0.1.0",
        "meta": meta or {},
        "summary": {
            "total_fields": len(field_specs),
            "comparable": len(comparable),
            "equal": len(iguais),
            "different": len(divergentes),
            "missing": len(missing),
            "not_comparable": len(not_comparable),
        },
        "sections": {
            "comparable": comparable,
            "equal": iguais,
            "different": divergentes,
            "missing": missing,
            "not_comparable": not_comparable,
        },
    }
    return report


# =============================================================================
# Carregamento opcional de persistência Fase 1 (sem reprocessar)
# =============================================================================

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)


def run_from_phase1_persisted(
    *,
    case_id: str,
    proposta_json_path: Path,
    cnh_json_path: Path,
    out_report_path: Optional[Path] = None,
    field_specs: Tuple[FieldSpec, ...] = DEFAULT_FIELD_SPECS,
) -> Dict[str, Any]:
    """
    Executa o validador usando SOMENTE os JSONs persistidos da Fase 1.
    Se out_report_path for fornecido, persiste o relatório.
    """
    proposta_data = load_json(proposta_json_path)
    cnh_data = load_json(cnh_json_path)

    meta = {
        "inputs": {
            "proposta_json_path": str(proposta_json_path),
            "cnh_json_path": str(cnh_json_path),
        }
    }

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta_data,
        cnh_data=cnh_data,
        field_specs=field_specs,
        meta=meta,
    )

    if out_report_path is not None:
        write_json(out_report_path, report)

    return report
