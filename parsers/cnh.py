from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


# ----------------------------
# Helpers / normalization
# ----------------------------

_RE_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_RE_CPF = re.compile(r"\b(\d{3}\.?(?:\d{3})\.?(?:\d{3})-?\d{2})\b")
_RE_CPF_DIGITS = re.compile(r"\D+")


def _only_digits(s: str) -> str:
    return _RE_CPF_DIGITS.sub("", s or "")


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _upper(s: str) -> str:
    return _norm_spaces(s).upper()


def _strip_leading_enum(s: str) -> str:
    # Ex.: "8. MINISTÉRIO ..." -> "MINISTÉRIO ..."
    return re.sub(r"^\s*\d{1,2}\s*[\.)-]\s*", "", s or "").strip()


def _alpha_ratio_letters_only(s: str) -> float:
    """
    Proporção de letras em relação ao total de caracteres "relevantes" (letras + dígitos).
    Pontuação/símbolos não contam no denominador.
    """
    if not s:
        return 0.0
    letters = sum(1 for ch in s if ch.isalpha())
    alnum = sum(1 for ch in s if ch.isalnum())
    return letters / max(alnum, 1)


# Bloqueio de headers institucionais e ruído frequente em CNH digital/exportada
_INSTITUTIONAL_TOKENS = {
    "MINISTÉRIO",
    "MINISTERIO",
    "TRANSPORTES",
    "GOVERNO",
    "GOV",
    "REPÚBLICA",
    "REPUBLICA",
    "FEDERATIVA",
    "BRASIL",
    "QR",
    "QRCODE",
    "QR-CODE",
    "CODE",
    "DOCUMENTO",
    "CARTEIRA",
    "NACIONAL",
    "HABILITAÇÃO",
    "HABILITACAO",
    "SENATRAN",
    "DENATRAN",
    "SERPRO",
    "SECRETARIA",
    "CNH",
    "DIGITAL",
    "VALIDAÇÃO",
    "VALIDACAO",
    "ASSINADOR",
    "ASSINATURA",
}


def _contains_institutional_noise(s: str) -> bool:
    u = _upper(_strip_leading_enum(s))
    if not u:
        return False
    for tok in _INSTITUTIONAL_TOKENS:
        if tok in u:
            return True
    return False


def _strip_noise_lines(lines: list[str]) -> list[str]:
    """
    Remove linhas vazias/curtas. Mantém caixa alta para estabilidade.
    """
    out: list[str] = []
    for ln in lines:
        u = _upper(ln)
        if not u:
            continue
        if len(u) < 3:
            continue
        out.append(u)
    return out


def _find_all_dates(text: str) -> list[str]:
    return _RE_DATE.findall(text or "")


def _find_all_cpfs(text: str) -> list[str]:
    return _RE_CPF.findall(text or "")


def _pick_best_cpf(text: str) -> Optional[str]:
    cpfs = _find_all_cpfs(text)
    candidates: list[str] = []
    for c in cpfs:
        d = _only_digits(c)
        if len(d) == 11:
            candidates.append(d)
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


_ALLOWED_CATEGORIAS = {"A", "B", "C", "D", "E", "AB", "AC", "AD", "AE"}


def _normalize_categoria_token(tok: str) -> str:
    # tolera "A B", "A-B", "A. B" etc
    t = _upper(tok)
    t = re.sub(r"[^A-Z]", "", t)
    return t


def _extract_categoria_from_lines(lines: list[str]) -> Optional[str]:
    """
    FIX CRÍTICO:
    - Não pode "achar" categoria dentro do rótulo (CATEGORIA) nem em palavras vizinhas.
    - Só aceita:
      (1) valor logo após o rótulo na mesma linha (depois de ':' '-' etc),
      (2) valor em uma das próximas linhas, desde que a linha seja curta/compatível.

    Isso elimina falso-positivo tipo pegar 'C' de 'CATEGORIA' ou 'E' de qualquer lugar.
    """
    # regex do rótulo (variações comuns)
    label_re = re.compile(r"\bCAT(?:\.|\b)|\bCATEG(?:ORIA)?\b", re.IGNORECASE)

    # 1) varre procurando o rótulo
    for i, ln in enumerate(lines[:260]):
        if not label_re.search(ln):
            continue

        u = _upper(ln)

        # 1a) tenta extrair depois do rótulo na mesma linha
        # ex: "CATEGORIA: AB" / "CAT. - AE" / "CAT AB"
        # pega o trecho após a ocorrência do rótulo e um separador opcional
        m = re.search(r"(?:\bCAT(?:\.)?\b|\bCATEG(?:ORIA)?\b)\s*[:\-]?\s*(.+)$", u)
        if m:
            tail = m.group(1).strip()
            cand = _normalize_categoria_token(tail)
            # às vezes tail contém outras coisas; então:
            # - se for exatamente uma categoria válida, retorna
            if cand in _ALLOWED_CATEGORIAS:
                return cand
            # - senão, tenta pegar um token curto no começo
            m2 = re.match(r"^([A-E](?:[\s\-\.]*[B-E])?)\b", tail)
            if m2:
                cand2 = _normalize_categoria_token(m2.group(1))
                if cand2 in _ALLOWED_CATEGORIAS:
                    return cand2

        # 1b) tenta próxima(s) linha(s) com linha curta
        # ex: linha seguinte é "AB" ou "A B"
        for j in range(1, 5):
            nxt = _safe_get(lines, i + j)
            if not nxt:
                continue
            nu = _upper(nxt)

            # evita rodapé/MRZ e outras seções
            if "I<BR" in nu or "<<<" in nu or "ASSINADOR" in nu or "SERPRO" in nu:
                break

            # pega apenas se a linha for "curta o bastante" para ser valor
            # (evita pegar 'E' perdido dentro de uma frase)
            stripped = re.sub(r"\s+", "", nu)
            if len(stripped) > 8:
                continue

            cand3 = _normalize_categoria_token(nu)
            if cand3 in _ALLOWED_CATEGORIAS:
                return cand3

            m3 = re.fullmatch(r"\s*([A-E])\s*[\-\.]?\s*([B-E])\s*", nu)
            if m3:
                cand4 = (m3.group(1) + m3.group(2)).upper()
                if cand4 in _ALLOWED_CATEGORIAS:
                    return cand4

    # 2) fallback conservador: procurar "CATEGORIA: XX" no texto já em linhas não ajuda;
    # se não achou via rótulo + valor, é melhor retornar None do que inventar.
    return None


def _clean_person_name_line(s: str) -> str:
    """
    Limpa ruído inicial e mantém apenas letras e espaços.
    Remove tokens curtos típicos de ruído OCR (exceto partículas).
    """
    u = _upper(_strip_leading_enum(s))
    if not u:
        return ""

    u = re.sub(r"[^A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ\s]", " ", u)
    u = _norm_spaces(u)

    toks = [t for t in u.split() if t]
    cleaned: list[str] = []
    for t in toks:
        if len(t) <= 2 and t not in {"DA", "DE", "DO", "DOS", "DAS"}:
            continue
        cleaned.append(t)

    return " ".join(cleaned).strip()


def _is_plausible_fullname(s: str) -> bool:
    s0 = _clean_person_name_line(s)
    if not s0:
        return False

    if "<" in s0:
        return False

    if _contains_institutional_noise(s0):
        return False

    toks = s0.split()
    if len(toks) < 2:
        return False

    if _alpha_ratio_letters_only(s0) < 0.70:
        return False

    return True


def _name_candidate_score(line: str) -> int:
    s = _clean_person_name_line(line)
    if not s:
        return -10**9

    if _contains_institutional_noise(s):
        return -10**7

    toks = s.split()
    if len(toks) < 2:
        return -10**6

    score = 0
    score += min(len(toks), 7) * 10
    score += int(_alpha_ratio_letters_only(s) * 40)

    for p in ("DA", "DE", "DO", "DOS", "DAS"):
        if p in toks:
            score += 4

    score -= sum(1 for t in toks if len(t) <= 2) * 8
    return score


def _extract_mrz_name(lines: list[str]) -> Optional[str]:
    """
    Fallback crítico: muitos PDFs exportados trazem o nome mais "limpo"
    na linha MRZ (ex.: "BRUNO<<LIMA<CARNEIRO<<<<<<<<<<").
    """
    for ln in lines[-160:]:
        if "<<" not in ln:
            continue
        u = _upper(ln)
        if not re.search(r"[A-Z]{2,}<<[A-Z]", u):
            continue

        cand = u.replace("<", " ")
        cand = _clean_person_name_line(cand)
        if _is_plausible_fullname(cand):
            return cand

    return None


def _extract_nome(lines: list[str]) -> Optional[str]:
    """
    Estratégia (mínima e determinística):
    1) Contexto de 'NOME' quando houver.
    2) Fallback: melhor candidato por score no bloco superior.
    3) Fallback final: MRZ (linha com '<<').
    """
    candidates: list[str] = []

    # 1) tenta âncora NOME
    for i, ln in enumerate(lines[:120]):
        u = _upper(ln)
        if "NOME" in u:
            after = re.split(r"\bNOME\b[:\-]?\s*", u, maxsplit=1)
            if len(after) == 2:
                cand = _clean_person_name_line(after[1])
                if _is_plausible_fullname(cand):
                    candidates.append(cand)

            nxt = _safe_get(lines, i + 1)
            cand2 = _clean_person_name_line(nxt)
            if _is_plausible_fullname(cand2):
                candidates.append(cand2)

    if candidates:
        candidates.sort(key=_name_candidate_score, reverse=True)
        return candidates[0]

    # 2) fallback por score (primeiras linhas), evitando institucional
    scored: list[tuple[int, str]] = []
    for ln in lines[:90]:
        cand = _clean_person_name_line(ln)
        if _is_plausible_fullname(cand):
            scored.append((_name_candidate_score(cand), cand))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    # 3) MRZ
    return _extract_mrz_name(lines)


def _is_plausible_filiacao_line(s: str) -> bool:
    s0 = _clean_person_name_line(s)
    if not s0:
        return False

    if "<" in s:
        return False

    if _contains_institutional_noise(s0):
        return False

    toks = s0.split()
    if len(toks) < 2:
        return False

    if _alpha_ratio_letters_only(s0) < 0.70:
        return False

    return True


def _extract_after_label(line: str, label_regex: str) -> Optional[str]:
    u = _upper(line)
    m = re.search(label_regex, u)
    if not m:
        return None
    tail = u[m.end() :]
    tail = _clean_person_name_line(tail)
    return tail or None


def _extract_filiacao(lines: list[str], nome: Optional[str]) -> list[str]:
    """
    Estratégia determinística:
      1) MAE/PAI explícitos, se existirem.
      2) marcador FILIA* aproximado + próximas linhas plausíveis.
      3) fallback: antes do MRZ, pega 2 melhores linhas plausíveis que não sejam o próprio nome.
    """
    out: list[str] = []

    # 1) MAE / PAI explícitos
    for ln in lines[:260]:
        mae = _extract_after_label(ln, r"\bM[ÃA]E\b\s*[:\-]?\s*")
        if mae and _is_plausible_filiacao_line(mae):
            out.append(mae)

        pai = _extract_after_label(ln, r"\bPAI\b\s*[:\-]?\s*")
        if pai and _is_plausible_filiacao_line(pai):
            out.append(pai)

    # 2) marcador de filiação aproximado
    if not out:
        for i, ln in enumerate(lines[:260]):
            u = _upper(ln)
            letters = re.sub(r"[^A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ]", "", u)

            # aceita FILIA/FILIACAO; e casos OCR tipo FITICAO
            is_filiacao_marker = ("FILIA" in letters) or ("FILIAC" in letters) or ("FILI" in letters and "AO" in letters)
            is_filiacao_marker = is_filiacao_marker or ("FI" in letters and "ICAO" in letters)

            if is_filiacao_marker:
                # mesma linha
                tail = re.split(r"(FILIA(?:ÇÃO|CAO)?|FILIACAO|FILIATION|FILIACION)", u, maxsplit=1)
                if len(tail) >= 3:
                    cand = _clean_person_name_line(tail[-1])
                    if cand and _is_plausible_filiacao_line(cand):
                        out.append(cand)

                # próximas linhas
                for j in range(1, 9):
                    nxt = _safe_get(lines, i + j)
                    if not nxt:
                        continue
                    nu = _upper(nxt)

                    if "I<BR" in nu or "<<<" in nu or "ASSINADOR" in nu or "SERPRO" in nu:
                        break

                    cand2 = _clean_person_name_line(nu)
                    if cand2 and _is_plausible_filiacao_line(cand2):
                        out.append(cand2)

                break

    # 3) fallback: melhores candidatos antes do MRZ
    if not out:
        mrz_idx = None
        for i, ln in enumerate(lines):
            if "I<BR" in ln or re.match(r"^I<BR", ln):
                mrz_idx = i
                break

        search_block = lines[:mrz_idx] if mrz_idx is not None else lines
        search_block = search_block[-80:]

        nome_toks = set((_upper(nome or "").split()))
        scored: list[tuple[int, str]] = []
        for ln in search_block:
            cand = _clean_person_name_line(ln)
            if not cand:
                continue
            if not _is_plausible_filiacao_line(cand):
                continue

            # evita pegar o próprio nome
            cand_toks = set(cand.split())
            overlap = len(cand_toks & nome_toks) if nome_toks else 0
            if nome_toks and overlap >= max(2, min(3, len(nome_toks))):
                continue

            scored.append((_name_candidate_score(cand), cand))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            out = [scored[0][1]]
            for _, cand in scored[1:]:
                if cand != out[0]:
                    out.append(cand)
                if len(out) >= 2:
                    break

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
    - validade tende a ser a data mais futura (>= 1900)
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

    parsed.sort()

    birth = None
    for y, m, day, d in parsed:
        if 1900 <= y <= 2100:
            birth = d
            break

    validity = None
    for y, m, day, d in reversed(parsed):
        if 1900 <= y <= 2100:
            validity = d
            break

    return birth, validity


def _extract_naturalidade(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Busca NATURALIDADE / MUNICÍPIO / UF.
    """
    for i, ln in enumerate(lines):
        u = _upper(ln)
        if "NATURAL" in u:
            tail = re.split(r"NATURAL(?:IDADE)?\s*[:\-]?\s*", u, maxsplit=1)
            cand = _upper(tail[1]) if len(tail) == 2 else ""

            toks = cand.split()
            if len(toks) >= 2 and _looks_like_state_uf(toks[-1]):
                uf = toks[-1]
                cidade = " ".join(toks[:-1]).strip()
                if cidade:
                    return cidade, uf

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
    Retorna: (fields, debug)
    """
    text = raw_text or ""
    lines = _strip_noise_lines(text.splitlines())

    dbg: dict[str, Any] = {"filename": filename}

    cpf = _pick_best_cpf(text)
    dates = _find_all_dates(text)
    data_nasc, validade = _extract_nascimento_validade(text, dates)

    nome = _extract_nome(lines)
    categoria = _extract_categoria_from_lines(lines)  # << FIX: determinístico e sem falso positivo
    filiacao = _extract_filiacao(lines, nome)

    cidade, uf = _extract_naturalidade(lines)

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
