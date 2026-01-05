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
    v = re.sub(r"[^A-Z0-9 ]+", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def normalize_cpf(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"\D+", "", value)
    if not digits:
        return None
    return digits


def normalize_date_to_iso(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass

    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T].+$", v)
    if m:
        return m.group(1)

    return None


# =============================================================================
# Specs
# =============================================================================

@dataclass(frozen=True)
class FieldSpec:
    key: str
    proposta_paths: Tuple[str, ...]
    cnh_paths: Tuple[str, ...]
    normalizer: Any
    comparable_when_missing: bool = True


DEFAULT_FIELD_SPECS: Tuple[FieldSpec, ...] = (
    FieldSpec(
        key="cpf",
        proposta_paths=("cpf", "data.cpf"),
        cnh_paths=("cpf", "data.cpf"),
        normalizer=normalize_cpf,
        comparable_when_missing=True,
    ),
    FieldSpec(
        key="nome",
        proposta_paths=("nome_financiado", "data.nome_financiado", "data.nome"),
        cnh_paths=("nome", "data.nome", "data.nome_completo"),
        normalizer=normalize_name,
        comparable_when_missing=True,
    ),
    FieldSpec(
        key="data_nascimento",
        proposta_paths=("data_nascimento", "data.data_nascimento", "data.nascimento"),
        cnh_paths=("data_nascimento", "data.data_nascimento", "data.nascimento"),
        normalizer=normalize_date_to_iso,
        comparable_when_missing=True,
    ),
)


# =============================================================================
# Lookup helpers (suporta data=dict e data=list)
# =============================================================================

def _is_empty_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _get_by_dot_path(obj: Any, path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur


def _candidate_roots(doc: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """
    roots candidatos para busca:
      - ("", doc)  (wrapper inteiro)
      - ("data", doc["data"]) se data for dict
      - ("data[i]", item) para cada item dict em data se data for list
    """
    roots: List[Tuple[str, Any]] = [("", doc)]
    data = doc.get("data")
    if isinstance(data, dict):
        roots.append(("data", data))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                roots.append((f"data[{i}]", item))
    return roots


def _first_present_in_roots(
    *,
    doc: Dict[str, Any],
    paths: Tuple[str, ...],
) -> Tuple[Optional[str], Optional[Any], str]:
    """
    Retorna (path_reportado, valor, strategy):
      - strategy "path": encontrou no wrapper pelo path literal
      - strategy "root_path": encontrou em data dict root usando path relativo
      - strategy "list_item_path": encontrou em data[i] item dict usando path relativo
      - strategy "none": não achou
    Observação: aqui consideramos "presente" qualquer valor não-vazio; None/vazio não conta.
    """
    # 1) literal no wrapper (permite "data.xxx")
    for p in paths:
        raw = _get_by_dot_path(doc, p)
        if not _is_empty_value(raw):
            return p, raw, "path"

    # 2) roots alternativos com path relativo (sem "data.")
    for prefix, root in _candidate_roots(doc):
        if prefix == "":
            continue
        for p in paths:
            if p.startswith("data."):
                continue
            raw = _get_by_dot_path(root, p)
            if _is_empty_value(raw):
                continue
            strategy = "root_path" if prefix == "data" else "list_item_path"
            return f"{prefix}.{p}", raw, strategy

    return None, None, "none"


def _first_existing_path_even_if_null(
    *,
    doc: Dict[str, Any],
    paths: Tuple[str, ...],
) -> Tuple[Optional[str], Optional[Any], str]:
    """
    Igual ao _first_present_in_roots, mas aqui retorna o primeiro path que EXISTE
    mesmo se o valor for None/vazio. Isso serve para diagnosticar 'missing_null'.
    strategy:
      - "path_exists"
      - "root_path_exists"
      - "list_item_path_exists"
      - "none"
    """
    # 1) literal no wrapper
    for p in paths:
        # checa existência caminhando até o último dict
        cur: Any = doc
        ok = True
        parts = p.split(".")
        for part in parts:
            if not isinstance(cur, dict) or part not in cur:
                ok = False
                break
            cur = cur[part]
        if ok:
            return p, cur, "path_exists"

    # 2) roots alternativos
    for prefix, root in _candidate_roots(doc):
        if prefix == "":
            continue
        for p in paths:
            if p.startswith("data."):
                continue
            cur = root
            ok = True
            for part in p.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    ok = False
                    break
                cur = cur[part]
            if ok:
                strategy = "root_path_exists" if prefix == "data" else "list_item_path_exists"
                return f"{prefix}.{p}", cur, strategy

    return None, None, "none"


# =============================================================================
# Report
# =============================================================================

def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def _is_effectively_missing(v: Optional[str]) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _evidence(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evidências mínimas para rastreabilidade (não decisório).
    """
    out: Dict[str, Any] = {}
    for k in ("document_type", "document_id", "file_path", "file_hash", "created_at", "case_id"):
        if k in doc:
            out[k] = doc.get(k)
    # Se existir debug canônico dentro de data
    data = doc.get("data")
    if isinstance(data, dict) and "debug" in data:
        out["data_debug_keys"] = sorted(list(data.get("debug", {}).keys())) if isinstance(data.get("debug"), dict) else None
    return out


def build_proposta_cnh_report(
    *,
    case_id: str,
    proposta_data: Dict[str, Any],
    cnh_data: Dict[str, Any],
    field_specs: Tuple[FieldSpec, ...] = DEFAULT_FIELD_SPECS,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    comparable: List[Dict[str, Any]] = []
    iguais: List[Dict[str, Any]] = []
    divergentes: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    not_comparable: List[Dict[str, Any]] = []

    for spec in field_specs:
        # 1) Busca por valor presente (não-vazio)
        p_path, p_raw, p_strategy = _first_present_in_roots(doc=proposta_data, paths=spec.proposta_paths)
        c_path, c_raw, c_strategy = _first_present_in_roots(doc=cnh_data, paths=spec.cnh_paths)

        p_raw_s = _safe_str(p_raw)
        c_raw_s = _safe_str(c_raw)

        p_norm = spec.normalizer(p_raw_s) if p_raw_s is not None else None
        c_norm = spec.normalizer(c_raw_s) if c_raw_s is not None else None

        entry = {
            "field": spec.key,
            "proposta": {
                "path": p_path,
                "strategy": p_strategy,
                "raw": p_raw_s,
                "normalized": p_norm,
            },
            "cnh": {
                "path": c_path,
                "strategy": c_strategy,
                "raw": c_raw_s,
                "normalized": c_norm,
            },
            "status": None,
            "status_detail": None,  # "missing_absent" | "missing_null" | None
            "explain": None,
        }

        p_missing = _is_effectively_missing(p_norm)
        c_missing = _is_effectively_missing(c_norm)

        if (p_missing or c_missing) and not spec.comparable_when_missing:
            entry["status"] = "not_comparable"
            entry["explain"] = "Campo não comparável porque está ausente em um dos documentos (configuração do campo)."
            not_comparable.append(entry)
            continue

        # Diagnóstico de missing: distinguir ausente vs nulo
        if p_missing or c_missing:
            # Para cada lado que está missing, checar se o path existe mesmo que o valor seja None
            if p_missing:
                p_exist_path, p_exist_val, p_exist_strategy = _first_existing_path_even_if_null(
                    doc=proposta_data,
                    paths=spec.proposta_paths,
                )
                if p_exist_path is not None:
                    entry["proposta"]["path"] = p_exist_path
                    entry["proposta"]["strategy"] = p_exist_strategy
                    entry["proposta"]["raw"] = _safe_str(p_exist_val)
                    entry["proposta"]["normalized"] = spec.normalizer(_safe_str(p_exist_val)) if _safe_str(p_exist_val) is not None else None
                    entry["status_detail"] = "missing_null"
                else:
                    # mantém strategy atual (none)
                    entry["status_detail"] = "missing_absent"

            if c_missing:
                c_exist_path, c_exist_val, c_exist_strategy = _first_existing_path_even_if_null(
                    doc=cnh_data,
                    paths=spec.cnh_paths,
                )
                if c_exist_path is not None:
                    entry["cnh"]["path"] = c_exist_path
                    entry["cnh"]["strategy"] = c_exist_strategy
                    entry["cnh"]["raw"] = _safe_str(c_exist_val)
                    entry["cnh"]["normalized"] = spec.normalizer(_safe_str(c_exist_val)) if _safe_str(c_exist_val) is not None else None
                    # se já tinha missing_null do outro lado, mantém; senão define
                    entry["status_detail"] = entry["status_detail"] or "missing_null"
                else:
                    entry["status_detail"] = entry["status_detail"] or "missing_absent"

            entry["status"] = "missing"
            if p_missing and c_missing:
                entry["explain"] = "Campo não preenchido nos dois documentos (ausente ou nulo após normalização)."
            elif p_missing:
                entry["explain"] = "Campo não preenchido na Proposta (ausente ou nulo após normalização) e presente na CNH."
            else:
                entry["explain"] = "Campo não preenchido na CNH (ausente ou nulo após normalização) e presente na Proposta."
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
        "version": "0.4.0",
        "meta": meta or {},
        "evidence": {
            "proposta": _evidence(proposta_data),
            "cnh": _evidence(cnh_data),
        },
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
# Optional IO helpers
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
