from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# =========================
# Public API
# =========================

def analyze_holerite(text: str) -> Dict[str, Any]:
    """
    Parser de holerite a partir de texto (native/OCR) já extraído.

    Contrato (mínimo):
      - não bloqueia extração
      - sempre retorna debug.checks e debug.warnings (mesmo vazios)
      - DV de CPF é "soft": apenas anota em debug, nunca zera campo
    """
    text = text or ""

    empregador = _find_empregador(text)
    nome = _find_nome_funcionario(text)
    cpf = _find_cpf(text)
    data_admissao = _find_data_admissao(text)
    total_vencimentos = _find_total_vencimentos(text)

    out: Dict[str, Any] = {
        "nome": nome,
        "cpf": cpf,
        "empregador": empregador,
        "data_admissao": data_admissao,
        "total_vencimentos": total_vencimentos,
        "debug": {
            # blindagem de sanidade (sempre presente)
            "checks": {},
            "warnings": [],
        },
    }

    _run_soft_sanity_checks(out)

    return out


# =========================
# Regexes
# =========================

# CPF (com ou sem pontuação)
_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")

# Datas dd/mm/yyyy (aceita dd-mm-yyyy como OCR)
_DATE_RE = re.compile(r"\b([0-3]?\d)[\/\-]([01]?\d)[\/\-]((?:19|20)\d{2})\b")

# Valores monetários pt-BR (1.234,56 ou 1234,56)
_MONEY_RE = re.compile(r"\b(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\b")

# Empregador: heurística por labels comuns
_EMPREGADOR_LABELS = (
    "EMPREGADOR",
    "EMPRESA",
    "RAZAO SOCIAL",
    "RAZÃO SOCIAL",
    "CNPJ/CPF",
    "CNPJ",
)

# Nome do funcionário: labels comuns
_NOME_LABELS = (
    "NOME",
    "NOME DO FUNCIONARIO",
    "NOME DO FUNCIONÁRIO",
    "FUNCIONARIO",
    "FUNCIONÁRIO",
    "EMPREGADO",
)

# Data admissão: labels comuns
_ADMISSAO_LABELS = (
    "ADMISSAO",
    "ADMISSÃO",
    "DATA ADMISSAO",
    "DATA ADMISSÃO",
    "DT ADMISSAO",
    "DT ADMISSÃO",
)

# Total vencimentos: labels comuns
_TOTAL_VENCIMENTOS_LABELS = (
    "TOTAL DE VENCIMENTOS",
    "TOTAL VENCIMENTOS",
    "TOTAL DOS VENCIMENTOS",
    "VENCIMENTOS",
    "TOTAL PROVENTOS",
    "TOTAL DE PROVENTOS",
)


# =========================
# Extraction helpers
# =========================

def _upper(text: str) -> str:
    return (text or "").upper()


def _lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _find_cpf(text: str) -> Optional[str]:
    m = _CPF_RE.search(text or "")
    if not m:
        return None
    return _only_digits(m.group(1)) or None


def _find_data_admissao(text: str) -> Optional[str]:
    up_lines = [ln.upper() for ln in _lines(text)]

    # 1) via label e data na mesma linha
    for ln in up_lines:
        if any(lbl in ln for lbl in _ADMISSAO_LABELS):
            m = _DATE_RE.search(ln)
            if m:
                return _fmt_date(m.group(1), m.group(2), m.group(3))

    # 2) label em uma linha e data na próxima (OCR comum)
    raw_lines = _lines(text)
    for i, ln in enumerate(raw_lines):
        u = ln.upper()
        if any(lbl in u for lbl in _ADMISSAO_LABELS):
            # tenta mesma linha primeiro
            m = _DATE_RE.search(ln)
            if m:
                return _fmt_date(m.group(1), m.group(2), m.group(3))
            # tenta próxima
            if i + 1 < len(raw_lines):
                m2 = _DATE_RE.search(raw_lines[i + 1])
                if m2:
                    return _fmt_date(m2.group(1), m2.group(2), m2.group(3))

    # 3) fallback: primeira data do documento (arriscado, mas melhor que NULL em alguns layouts)
    m = _DATE_RE.search(text or "")
    if m:
        return _fmt_date(m.group(1), m.group(2), m.group(3))

    return None


def _find_total_vencimentos(text: str) -> Optional[str]:
    """
    Retorna string monetária no formato pt-BR como aparece (ex.: 1.234,56).
    Mantém como string para não quebrar contrato existente.
    """
    raw_lines = _lines(text)
    up_lines = [ln.upper() for ln in raw_lines]

    # 1) Procura label e valor na mesma linha (prioritário)
    for raw, up in zip(raw_lines, up_lines):
        if any(lbl in up for lbl in _TOTAL_VENCIMENTOS_LABELS):
            m = _MONEY_RE.search(raw)
            if m:
                return _norm_money(m.group(1))

    # 2) Label em uma linha, valor na próxima (OCR)
    for i, up in enumerate(up_lines):
        if any(lbl in up for lbl in _TOTAL_VENCIMENTOS_LABELS):
            if i + 1 < len(raw_lines):
                m = _MONEY_RE.search(raw_lines[i + 1])
                if m:
                    return _norm_money(m.group(1))

    # 3) fallback: procura "TOTAL DE VENCIMENTOS <valor>" em texto corrido
    m = re.search(
        r"TOTAL\s+DE\s+VENCIMENTOS\s*([0-9\.]+,[0-9]{2})",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        return _norm_money(m.group(1))

    # 4) fallback: pega último valor monetário do documento (último recurso; pode errar)
    all_money = _MONEY_RE.findall(text or "")
    if all_money:
        return _norm_money(all_money[-1])

    return None


def _find_empregador(text: str) -> Optional[str]:
    raw_lines = _lines(text)
    up_lines = [ln.upper() for ln in raw_lines]

    # 1) procura label e pega próxima linha como valor
    for i, up in enumerate(up_lines):
        if any(lbl in up for lbl in _EMPREGADOR_LABELS):
            # tenta extrair algo "EMPRESA: X"
            parts = re.split(r"[:\-]\s*", raw_lines[i], maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                cand = parts[1].strip()
                return _clean_text_value(cand)

            # senão pega a próxima linha
            if i + 1 < len(raw_lines):
                cand = raw_lines[i + 1].strip()
                cand = _clean_text_value(cand)
                if cand:
                    return cand

    # 2) fallback: primeira linha longa que parece razão social (heurística simples)
    for ln in raw_lines[:12]:
        u = ln.upper()
        if len(u) >= 12 and "CPF" not in u and "FUNCION" not in u and "ADMISS" not in u:
            cand = _clean_text_value(ln)
            if cand and len(cand.split()) >= 2:
                return cand

    return None


def _find_nome_funcionario(text: str) -> Optional[str]:
    raw_lines = _lines(text)
    up_lines = [ln.upper() for ln in raw_lines]

    # 1) label + valor após ":" na mesma linha
    for raw, up in zip(raw_lines, up_lines):
        if any(lbl == up.strip() for lbl in _NOME_LABELS) or any(f"{lbl}:" in up for lbl in _NOME_LABELS):
            parts = re.split(r"[:\-]\s*", raw, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                cand = _clean_text_value(parts[1])
                if cand and len(cand.split()) >= 2:
                    return cand

    # 2) label em uma linha, nome na próxima
    for i, up in enumerate(up_lines):
        if any(lbl == up.strip() for lbl in _NOME_LABELS) or any(lbl in up for lbl in _NOME_LABELS):
            if i + 1 < len(raw_lines):
                cand = _clean_text_value(raw_lines[i + 1])
                if cand and len(cand.split()) >= 2:
                    return cand

    # 3) fallback: nome próximo do CPF (OCR costuma colar)
    cpf_match = _CPF_RE.search(text or "")
    if cpf_match:
        # pega um window antes do CPF e tenta última linha "name-like"
        idx = cpf_match.start()
        window = (text or "")[:idx]
        w_lines = _lines(window)[-6:]
        for ln in reversed(w_lines):
            cand = _clean_text_value(ln)
            if cand and len(cand.split()) >= 2 and not _looks_like_money(cand):
                return cand

    return None


# =========================
# Sanity + DV checks (soft)
# =========================

def _cpf_is_valid(cpf_digits: str) -> Tuple[bool, str]:
    """
    cpf_digits: apenas dígitos.
    Retorna (ok, reason): ok|empty|bad_length|all_equal|dv_mismatch
    """
    d = _only_digits(cpf_digits or "")
    if not d:
        return False, "empty"
    if len(d) != 11:
        return False, "bad_length"
    if d == d[0] * 11:
        return False, "all_equal"

    nums = [int(x) for x in d]
    s1 = sum(nums[i] * (10 - i) for i in range(9))
    dv1 = (s1 * 10) % 11
    dv1 = 0 if dv1 == 10 else dv1

    s2 = sum(nums[i] * (11 - i) for i in range(10))
    dv2 = (s2 * 10) % 11
    dv2 = 0 if dv2 == 10 else dv2

    if nums[9] == dv1 and nums[10] == dv2:
        return True, "ok"
    return False, "dv_mismatch"


def _run_soft_sanity_checks(out: Dict[str, Any]) -> None:
    """
    Blindagem mínima:
      - debug.checks e debug.warnings sempre presentes
      - DV do CPF é diagnóstico (soft), não altera campos extraídos
      - warnings determinísticos
    """
    dbg = out.setdefault("debug", {})
    checks: Dict[str, Any] = dbg.setdefault("checks", {})
    warnings: List[str] = dbg.setdefault("warnings", [])

    # CPF: valida DV apenas se tiver 11 dígitos
    cpf = out.get("cpf")
    cpf_str = "" if cpf is None else str(cpf)
    cpf_norm = _only_digits(cpf_str)

    ok, reason = _cpf_is_valid(cpf_norm)
    checks["cpf"] = {
        "raw": cpf,
        "normalized": cpf_norm,
        "dv_ok": bool(ok),
        "reason": reason,
    }

    # warning só se "parece CPF" e falhou de verdade
    if cpf_norm and len(cpf_norm) == 11 and not ok and reason in ("all_equal", "dv_mismatch"):
        if reason == "all_equal":
            warnings.append(f"CPF inválido (dígitos repetidos) (extraído='{cpf_str}')")
        else:
            warnings.append(f"CPF DV inválido (extraído='{cpf_str}')")

    # Sanidade: DV inválido nunca pode zerar CPF (garantia conceitual)
    if checks["cpf"]["dv_ok"] is False and cpf_norm:
        assert out.get("cpf") not in (None, ""), "DV inválido não pode zerar 'cpf'"

    # Total vencimentos: se existe, não pode ser string vazia
    tv = out.get("total_vencimentos")
    if tv is not None:
        tvs = str(tv).strip()
        if not tvs:
            warnings.append("TOTAL_VENCIMENTOS vazio (extraído como string vazia)")

    # Data admissão: se existe, deve estar no formato dd/mm/yyyy (sanidade leve)
    da = out.get("data_admissao")
    if da is not None:
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(da).strip()):
            warnings.append(f"DATA_ADMISSAO em formato inesperado (extraído='{da}')")


# =========================
# Formatting + cleaning
# =========================

def _fmt_date(d: str, m: str, y: str) -> str:
    dd = f"{int(d):02d}"
    mm = f"{int(m):02d}"
    yy = f"{int(y):04d}"
    return f"{dd}/{mm}/{yy}"


def _norm_money(s: str) -> str:
    s = (s or "").strip()
    # mantém 1.234,56 / 1234,56 como vem
    return s


def _clean_text_value(s: str) -> Optional[str]:
    """
    Limpa artefatos típicos de OCR e valores obviamente inválidos.
    """
    if not s:
        return None
    t = (s or "").strip()
    # remove lixo isolado
    if t in ("[", "]", "|", "I", "l"):
        return None
    # compacta espaços
    t = re.sub(r"\s{2,}", " ", t).strip()
    # corta valores absurdamente curtos
    if len(t) < 2:
        return None
    return t


def _looks_like_money(s: str) -> bool:
    return bool(_MONEY_RE.search(s or ""))
