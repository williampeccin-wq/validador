# validators/phase2/proposta_cnh_validator.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================
# Tipos / Contrato de saída (Phase 2)
# ============================================================

@dataclass(frozen=True)
class FieldSpec:
    """
    Define um campo comparável Proposta ↔ CNH.

    - key: identificador lógico do campo no report (ex.: "cpf", "nome", "nome_mae")
    - proposta_path: dotpath para buscar na proposta
    - cnh_path: dotpath para buscar na CNH (quando strategy == "path")
    - cnh_derive: função derivadora (quando strategy == "derive")
    - normalizer: função de normalização para comparação e explicabilidade
    """
    key: str
    proposta_path: str
    cnh_path: Optional[str] = None
    cnh_derive: Optional[Callable[[Dict[str, Any]], Tuple[Optional[Any], Optional[str]]]] = None
    normalizer: Callable[[Any], Optional[str]] = lambda v: _norm_text(v)


# ============================================================
# Normalização
# ============================================================

_JOINERS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _norm_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        s = _strip_accents(v).upper()
        s = re.sub(r"[^A-Z0-9 /-]+", " ", s)
        s = _collapse_spaces(s)
        return s or None
    return _norm_text(str(v))


def _norm_name(v: Any) -> Optional[str]:
    """
    Normalização mais agressiva para nomes:
    - remove tokens de 1-2 chars (ruído OCR)
    - preserva conectivos (DE/DA/DO/DAS/DOS/E), mas remove no começo/fim
    """
    s = _norm_text(v)
    if not s:
        return None
    toks = s.split()
    cleaned: List[str] = []
    for t in toks:
        if t in _JOINERS:
            cleaned.append(t)
            continue
        if len(t) <= 2:
            continue
        cleaned.append(t)

    while cleaned and cleaned[0] in _JOINERS:
        cleaned.pop(0)
    while cleaned and cleaned[-1] in _JOINERS:
        cleaned.pop()

    # colapsa conectivos repetidos
    out: List[str] = []
    for t in cleaned:
        if out and t in _JOINERS and out[-1] in _JOINERS:
            continue
        out.append(t)

    res = " ".join(out).strip()
    return res or None


def _norm_cpf(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    digits = re.sub(r"\D+", "", s)
    if len(digits) != 11:
        return None
    # não decide "válido/inválido" aqui; apenas normaliza
    return digits


def _norm_date_ddmmyyyy(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", s)
    if not m:
        return None
    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{dd}/{mm}/{yyyy}"


# ============================================================
# Acesso por dot-path (suporta [idx] em listas)
# ============================================================

_INDEX_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$")


def _get_by_dot_path(obj: Any, path: str) -> Any:
    """
    Ex.:
      "data.cpf"
      "data.filiacao[1]"
    """
    if obj is None or not path:
        return None

    cur: Any = obj
    for part in path.split("."):
        if cur is None:
            return None

        m = _INDEX_RE.match(part)
        if m:
            key = m.group(1)
            idx = int(m.group(2))

            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None

            if isinstance(cur, list):
                if 0 <= idx < len(cur):
                    cur = cur[idx]
                else:
                    return None
            else:
                return None
            continue

        # normal dict access
        if isinstance(cur, dict):
            cur = cur.get(part)
            continue

        # list access not supported unless explicit [idx]
        return None

    return cur


def _candidate_roots_with_prefix(doc: Dict[str, Any], prefix: str) -> List[Tuple[Any, str]]:
    """
    Retorna possíveis roots para buscar campos.
    Mantém um 'prefixo' apenas para fins de debug/explicação (não altera o path real).
    """
    roots: List[Tuple[Any, str]] = []

    # root: documento inteiro
    roots.append((doc, prefix + "$"))

    # root: doc["data"] (onde o Phase1 persiste os campos extraídos)
    data = doc.get("data")
    roots.append((data, prefix + "data"))

    # caso legado: data pode ser lista (ex.: múltiplas páginas/segmentos)
    if isinstance(data, list):
        for i, item in enumerate(data[:3]):
            roots.append((item, f"{prefix}data[{i}]"))

    return roots


def _first_value_for_paths(
    doc: Dict[str, Any],
    paths: List[str],
    *,
    prefix: str,
) -> Tuple[Optional[Any], Optional[str], str]:
    """
    Busca o primeiro valor não-nulo em uma lista de paths,
    tentando contra roots candidatas (doc e doc["data"] etc).
    Retorna: (raw_value, matched_path, strategy)
    """
    roots = _candidate_roots_with_prefix(doc, prefix=prefix)

    for p in paths:
        # Para consistência do report, mantemos o path "lógico" sempre como o que o spec pede (geralmente "data.x")
        # Então tentamos aplicar o path contra cada root, aceitando que o root já pode ser doc["data"].
        for root_obj, _root_label in roots:
            raw = _get_by_dot_path(root_obj, p.replace("data.", "", 1) if root_obj is doc.get("data") and p.startswith("data.") else p)
            if raw is not None:
                return raw, p, "path"

    return None, None, "none"


# ============================================================
# Derivações CNH (Phase 2) — sem alterar Phase 1
# ============================================================

def _derive_cnh_nome_mae(cnh_doc: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    """
    Deriva nome da mãe a partir do contrato atual da CNH:
      - cnh.data.filiacao é lista; mãe tipicamente é o índice 1.
    Retorna (raw_value, explain_path)
    """
    # tenta caminhos possíveis, sem inferir nada além do índice
    candidates = [
        "data.filiacao[1]",
        "filiacao[1]",  # se alguém armazenou diretamente
    ]
    for p in candidates:
        v = _get_by_dot_path(cnh_doc, p)
        if v is not None:
            return v, p
        # tenta dentro de data se root for dict já
        data = cnh_doc.get("data")
        if isinstance(data, dict):
            vv = _get_by_dot_path(data, p.replace("data.", "", 1) if p.startswith("data.") else p)
            if vv is not None:
                return vv, p
    return None, None


# ============================================================
# Specs comparáveis Proposta ↔ CNH
# ============================================================

_FIELDS: List[FieldSpec] = [
    FieldSpec(
        key="cpf",
        proposta_path="data.cpf",
        cnh_path="data.cpf",
        normalizer=_norm_cpf,
    ),
    FieldSpec(
        key="nome",
        proposta_path="data.nome_financiado",
        cnh_path="data.nome",
        normalizer=_norm_name,
    ),
    FieldSpec(
        key="data_nascimento",
        proposta_path="data.data_nascimento",
        cnh_path="data.data_nascimento",
        normalizer=_norm_date_ddmmyyyy,
    ),
    FieldSpec(
        key="cidade_nascimento",
        proposta_path="data.cidade_nascimento",
        cnh_path="data.cidade_nascimento",
        normalizer=_norm_name,  # cidade: normalização de texto/acentos; name-like é OK
    ),
    FieldSpec(
        key="uf_nascimento",
        proposta_path="data.uf",
        cnh_path="data.uf_nascimento",
        normalizer=_norm_text,
    ),
    # FUNDAMENTAL: nome_mae — derivado da CNH via filiacao[1]
    FieldSpec(
        key="nome_mae",
        proposta_path="data.nome_mae",
        cnh_path=None,
        cnh_derive=_derive_cnh_nome_mae,
        normalizer=_norm_name,
    ),
]


# ============================================================
# Report builder (Phase 2) — explicável, sem decisão automática
# ============================================================

def build_proposta_cnh_report(
    *,
    case_id: str,
    proposta_doc: Dict[str, Any],
    cnh_doc: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Gera relatório explicável de comparação Proposta ↔ CNH.

    Regras:
    - Não bloqueia fluxo
    - Não conclui "aprovado/reprovado"
    - Apenas lista campos comparáveis: iguais, divergentes, ausentes
    - Usa somente dados já persistidos no Phase 1 (proposta_doc/cnh_doc)
    """
    report: Dict[str, Any] = {
        "version": "phase2.proposta_vs_cnh.v1",
        "case_id": case_id,
        "inputs": {
            "proposta_document_id": proposta_doc.get("document_id"),
            "cnh_document_id": cnh_doc.get("document_id"),
            "proposta_document_type": proposta_doc.get("document_type"),
            "cnh_document_type": cnh_doc.get("document_type"),
            "proposta_file_path": proposta_doc.get("file_path"),
            "cnh_file_path": cnh_doc.get("file_path"),
        },
        "summary": {},
        "sections": {
            "equal": [],
            "different": [],
            "missing": [],
            "not_comparable": [],
        },
    }

    counts = {
        "total_fields": len(_FIELDS),
        "comparable": 0,
        "equal": 0,
        "different": 0,
        "missing": 0,
        "not_comparable": 0,
    }

    for spec in _FIELDS:
        # Proposta (sempre path)
        p_raw, p_path, p_strategy = _first_value_for_paths(
            proposta_doc,
            [spec.proposta_path],
            prefix="proposta.",
        )

        # CNH (path ou derive)
        c_raw: Optional[Any] = None
        c_path: Optional[str] = None
        c_strategy: str = "none"

        if spec.cnh_derive is not None:
            c_raw, c_path = spec.cnh_derive(cnh_doc)
            c_strategy = "derive" if c_raw is not None else "none"
        elif spec.cnh_path is not None:
            c_raw, c_path, c_strategy = _first_value_for_paths(
                cnh_doc,
                [spec.cnh_path],
                prefix="cnh.",
            )

        p_norm = spec.normalizer(p_raw)
        c_norm = spec.normalizer(c_raw)

        # comparabilidade (aqui: ambos presentes e normalizáveis)
        is_p_present = p_norm is not None
        is_c_present = c_norm is not None

        item = {
            "field": spec.key,
            "proposta": {
                "path": p_path,
                "strategy": p_strategy,
                "raw": p_raw,
                "normalized": p_norm,
            },
            "cnh": {
                "path": c_path,
                "strategy": c_strategy,
                "raw": c_raw,
                "normalized": c_norm,
            },
            "status": None,
            "status_detail": None,
            "explain": None,
        }

        # não comparável (ex.: ambos ausentes) — ainda assim entra no relatório
        if not is_p_present and not is_c_present:
            counts["not_comparable"] += 1
            item["status"] = "not_comparable"
            item["status_detail"] = "both_absent_or_unreadable"
            item["explain"] = "Campo ausente ou não normalizável em ambos os documentos; não há base para comparação."
            report["sections"]["not_comparable"].append(item)
            continue

        # missing: um presente e outro ausente
        if is_p_present and not is_c_present:
            counts["missing"] += 1
            item["status"] = "missing"
            item["status_detail"] = "missing_absent"
            item["explain"] = "Campo presente na Proposta e ausente (ou não normalizável) na CNH."
            report["sections"]["missing"].append(item)
            continue

        if not is_p_present and is_c_present:
            counts["missing"] += 1
            item["status"] = "missing"
            item["status_detail"] = "missing_in_proposta"
            item["explain"] = "Campo presente na CNH e ausente (ou não normalizável) na Proposta."
            report["sections"]["missing"].append(item)
            continue

        # ambos presentes => comparável
        counts["comparable"] += 1

        if p_norm == c_norm:
            counts["equal"] += 1
            item["status"] = "equal"
            item["status_detail"] = "normalized_equal"
            item["explain"] = "Valores normalizados são idênticos entre Proposta e CNH."
            report["sections"]["equal"].append(item)
        else:
            counts["different"] += 1
            item["status"] = "different"
            item["status_detail"] = "normalized_diff"
            item["explain"] = "Valores normalizados divergem entre Proposta e CNH. Revisão humana recomendada."
            report["sections"]["different"].append(item)

    report["summary"] = counts
    return report
