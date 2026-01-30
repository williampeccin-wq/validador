from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


# ----------------------------
# Helpers / normalization
# ----------------------------

_RE_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_RE_CPF = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_RE_CPF_DIGITS = re.compile(r"\D+")


def _only_digits(s: str) -> str:
    return _RE_CPF_DIGITS.sub("", s or "")


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _upper(s: str) -> str:
    return _norm_spaces(s).upper()


def _clean_name_token(tok: str) -> str:
    tok = _upper(tok)
    tok = re.sub(r"[^A-ZÇÁÀÂÃÉÊÍÓÔÕÚÜ]", "", tok)
    return tok


def _is_plausible_fullname(s: str) -> bool:
    s = _upper(s)
    if not s:
        return False
    toks = [t for t in s.split() if t]
    if len(toks) < 2:
        return False
    # evita lixo óbvio
    if any(len(t) < 2 for t in toks):
        return False
    return True


def _strip_noise_lines(lines: list[str]) -> list[str]:
    """
    Remove linhas muito curtas/lixo de OCR.
    """
    out: list[str] = []
    for ln in lines:
        u = _upper(ln)
        if not u:
            continue
        if len(u) < 3:
            continue
        # "AAA OER" e similares: deixa passar por enquanto (contratos podem barrar)
        out.append(u)
    return out


def _find_all_dates(text: str) -> list[str]:
    return _RE_DATE.findall(text or "")


def _find_all_cpfs(text: str) -> list[str]:
    return _RE_CPF.findall(text or "")


def _pick_best_cpf(text: str) -> Optional[str]:
    cpfs = _find_all_cpfs(text)
    # normaliza e filtra para 11 dígitos
    candidates = []
    for c in cpfs:
        d = _only_digits(c)
        if len(d) == 11:
            candidates.append(d)
    # pega o primeiro estável
    return candidates[0] if candidates else None


def _looks_like_state_uf(tok: str) -> bool:
    tok = _upper(tok)
    return bool(re.fullmatch(r"[A-Z]{2}", tok))


def _safe_get(lines: list[str], idx: int) -> str:
    if 0 <= idx < len(lines):
        return lines[idx]
    return ""


# ----------------------------
# Field extraction (heuristic)
# ----------------------------

@dataclass
class CNHExtract:
    nome: Optional[str] = None
    cpf: Optional[str] = None
    categoria: Optional[str] = None
    data_nascimento: Optional[str] = None
    validade: Optional[str] = None
    cidade_nascimento: Optional[str] = None
    uf_nascimento: Optional[str] = None
    filiacao: list[str] | None = None


def _extract_categoria(text: str) -> Optional[str]:
    """
    Tenta achar categoria com tolerância a OCR.
    Exemplos: "CAT. AB", "CATEGORIA: AE", etc.
    """
    t = _upper(text)

    # padrões mais comuns
    m = re.search(r"\bCAT(?:\.|EGORIA)?\s*[:\-]?\s*(A|B|C|D|E|AB|AC|AD|AE)\b", t)
    if m:
        return m.group(1)

    # fallback: às vezes vem solto como "AB" em uma linha de "CATEGORIA"
    m2 = re.search(r"\bCATEGORIA\b.*\b(A|B|C|D|E|AB|AC|AD|AE)\b", t)
    if m2:
        return m2.group(1)

    return None


def _extract_nome(lines: list[str]) -> Optional[str]:
    """
    Heurística: procura linha com "NOME" e pega os tokens após,
    ou escolhe a primeira linha "plausível".
    """
    for i, ln in enumerate(lines):
        u = _upper(ln)
        if "NOME" in u:
            # tenta pegar o que vem depois do NOME na mesma linha
            after = re.split(r"\bNOME\b[:\-]?\s*", u, maxsplit=1)
            if len(after) == 2 and _is_plausible_fullname(after[1]):
                return after[1]

            # tenta a próxima linha
            nxt = _safe_get(lines, i + 1)
            if _is_plausible_fullname(nxt):
                return _upper(nxt)

    # fallback: primeira linha com cara de nome
    for ln in lines[:20]:
        if _is_plausible_fullname(ln):
            return _upper(ln)

    return None


def _extract_filiacao(lines: list[str]) -> list[str]:
    """
    Heurística: procura "FILIAÇÃO" e pega 1-2 linhas seguintes,
    com limpeza básica.
    """
    out: list[str] = []
    for i, ln in enumerate(lines):
        u = _upper(ln)
        if "FILIA" in u:  # pega FILIAÇÃO, FILIACAO etc
            # tenta extrair na mesma linha depois do rótulo
            parts = re.split(r"FILIA(?:ÇÃO|CAO)?\s*[:\-]?\s*", u, maxsplit=1)
            if len(parts) == 2 and parts[1]:
                cand = parts[1].strip()
                if cand:
                    out.append(cand)

            # pega próximas linhas (mãe/pai)
            for j in range(1, 4):
                nxt = _safe_get(lines, i + j)
                if not nxt:
                    continue
                nu = _upper(nxt)
                # para quando bate em outro rótulo típico
                if any(k in nu for k in ["VALIDADE", "NASC", "CATEG", "CPF", "DOC", "NATURAL"]):
                    break
                out.append(nu)

            break

    out = _strip_noise_lines(out)

    # dedup mantendo ordem
    dedup: list[str] = []
    seen = set()
    for x in out:
        k = _upper(x)
        if k and k not in seen:
            dedup.append(k)
            seen.add(k)

    return dedup


def _extract_nascimento_validade(text: str, dates: list[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Regra simples:
    - nascimento tende a ser a data mais antiga (>= 1900)
    - validade tende a ser a data mais futura (>= ano atual-1)
    Como o OCR traz datas extras, isso é heurístico.
    """
    if not dates:
        return None, None

    parsed: list[tuple[int, int, int, str]] = []
    for d in dates:
        try:
            dd, mm, yyyy = d.split("/")
            y = int(yyyy)
            m = int(mm)
            day = int(dd)
            parsed.append((y, m, day, d))
        except Exception:
            continue

    if not parsed:
        return None, None

    parsed.sort()  # por ano/mes/dia

    # nascimento: primeira >=1900 e <= (ano atual + 1) mas não precisa de now aqui
    birth = None
    for y, m, day, d in parsed:
        if 1900 <= y <= 2100:
            birth = d
            break

    # validade: última >=1900
    validity = None
    for y, m, day, d in reversed(parsed):
        if 1900 <= y <= 2100:
            validity = d
            break

    # evita escolher a mesma data quando só tem uma
    return birth, validity


def _extract_naturalidade(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Busca NATURALIDADE / MUNICÍPIO / UF.
    Heurística: encontra linha com NATURALIDADE e tenta achar "CIDADE UF".
    """
    for i, ln in enumerate(lines):
        u = _upper(ln)
        if "NATURAL" in u:
            tail = re.split(r"NATURAL(?:IDADE)?\s*[:\-]?\s*", u, maxsplit=1)
            cand = tail[1] if len(tail) == 2 else ""
            cand = _upper(cand)

            # tenta extrair "CIDADE UF"
            toks = cand.split()
            if len(toks) >= 2 and _looks_like_state_uf(toks[-1]):
                uf = toks[-1]
                cidade = " ".join(toks[:-1]).strip()
                if cidade:
                    return cidade, uf

            # tenta próxima linha
            nxt = _upper(_safe_get(lines, i + 1))
            toks = nxt.split()
            if len(toks) >= 2 and _looks_like_state_uf(toks[-1]):
                uf = toks[-1]
                cidade = " ".join(toks[:-1]).strip()
                if cidade:
                    return cidade, uf

    return None, None


def analyze_cnh(
    raw_text: str,
    *,
    filename: Optional[str] = None,
    **_kwargs: Any,
) -> tuple[dict, dict]:
    """
    IMPORTANTE:
    - O pipeline (selector/phase1) pode chamar analyze_cnh(..., filename="...").
    - Para evitar regressão futura, aceitamos **_kwargs silenciosamente.

    Retorna: (fields, debug)
    """
    text = raw_text or ""
    lines = _strip_noise_lines(text.splitlines())

    dbg: dict[str, Any] = {"filename": filename}

    cpf = _pick_best_cpf(text)
    dates = _find_all_dates(text)
    categoria = _extract_categoria(text)
    nome = _extract_nome(lines)
    filiacao = _extract_filiacao(lines)
    cidade, uf = _extract_naturalidade(lines)

    data_nasc, validade = _extract_nascimento_validade(text, dates)

    fields: dict[str, Any] = {
        "nome": nome,
        "cpf": cpf,
        "categoria": categoria,
        "data_nascimento": data_nasc,
        "validade": validade,
        "cidade_nascimento": cidade,
        "uf_nascimento": uf,
        "filiacao": filiacao,
    }

    dbg.update(
        {
            "found_dates": dates,
            "found_cpfs": _find_all_cpfs(text),
            "extracted": {k: fields.get(k) for k in ["nome", "cpf", "categoria", "data_nascimento", "validade"]},
        }
    )

    return fields, dbg
