from __future__ import annotations


# --- WQ CNH postprocess helpers (v1) ---
_WQ_CNH_FILIACAO_BAD_TOKENS = {
    "FILIATION", "FILIACIÓN", "OBSERVAÇÕES", "OBSERVATIONS", "OBSERVACIONES",
    "LOCAL", "PLACE", "LUGAR", "NATURALIDADE", "NASCIMENTO", "DATA", "VALIDADE",
}


def _wq_is_glossary_noise_line(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return True
    up = t.upper()
    # linha muito "título"/glossário multilingue
    hits = sum(1 for tok in _WQ_CNH_FILIACAO_BAD_TOKENS if tok in up)
    if hits >= 2:
        return True
    # linhas com poucos chars úteis e muito ruído
    if len(up) < 6:
        return True
    return False


def _wq_cleanup_filiacao(filiacao):
    if not filiacao:
        return []
    out = []
    for x in filiacao:
        x = (x or "").strip()
        if not x:
            continue
        if _wq_is_glossary_noise_line(x):
            continue
        # remove "lixos" curtos que aparecem como restos de OCR (ex: AAA OER, MAS FIO, ADA THE)
        toks = x.split()
        if len(toks) <= 2 and any(len(t) <= 3 for t in toks):
            continue
        out.append(x)
    # dedupe preservando ordem
    seen = set()
    out2 = []
    for x in out:
        k = x.upper()
        if k in seen:
            continue
        seen.add(k)
        out2.append(x)
    return out2


def _wq_postprocess_out(out: dict) -> dict:
    # não quebra se out não for dict esperado
    if not isinstance(out, dict):
        return out
    if "filiacao" in out:
        out["filiacao"] = _wq_cleanup_filiacao(out.get("filiacao"))
    return out
# --- end WQ helpers ---

import re
from dataclasses import dataclass
from typing import Any, Optional


# ----------------------------
# Helpers / normalization
# ----------------------------

_RE_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_RE_CPF = re.compile(r"\b(\d{3}\.?(?:\d{3})\.?(?:\d{3})-?\d{2})\b")
_RE_CPF_DIGITS = re.compile(r"\D+")


def _wq_wrap_return_v1(*ret):
    """
    Envelopa retornos de analyze_cnh para aplicar pós-processamento sem depender
    do formato (dict, tuple/list com dict na pos 0, etc.).

    Aceita:
      - dict
      - (fields, dbg, parse_error)  -> tuple
      - (dict, ...) ou [dict, ...]
    """
    try:
        # chamada comum: _wq_wrap_return_v1(fields, dbg, parse_error)
        if len(ret) == 3 and isinstance(ret[0], dict):
            fields, dbg, parse_error = ret
            return (_wq_postprocess_out(fields), dbg, parse_error)

        # chamada antiga: _wq_wrap_return_v1(dict)
        if len(ret) == 1:
            r0 = ret[0]
            if isinstance(r0, dict):
                return _wq_postprocess_out(r0)
            if isinstance(r0, (tuple, list)) and r0:
                first = r0[0]
                if isinstance(first, dict):
                    first2 = _wq_postprocess_out(first)
                    if isinstance(r0, tuple):
                        return (first2, *r0[1:])
                    r0b = list(r0)
                    r0b[0] = first2
                    return r0b
            return r0

        # fallback: devolve como tuple
        if isinstance(ret, tuple) and ret and isinstance(ret[0], dict):
            return (_wq_postprocess_out(ret[0]), *ret[1:])
    except Exception:
        # nunca quebra pipeline por pós-processamento
        pass

    return ret if len(ret) != 1 else ret[0]


# >>> WQ ADD
_WQ__OLD_WRAP_RETURN_V1 = _wq_wrap_return_v1


def _wq_wrap_return_v1(*ret):
    out = _WQ__OLD_WRAP_RETURN_V1(*ret)
    if isinstance(out, tuple) and len(out) == 3 and isinstance(out[0], dict) and isinstance(out[1], dict):
        return (out[0], out[1])
    return out
# <<< WQ ADD


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


# Tokens típicos de *labels/campos* (PT/EN/ES) que NÃO podem virar nome.
# Cobre o problema relatado: capturar headers multilíngues como se fossem nomes.
_FIELD_LABEL_NOISE_TOKENS = {
    # PT
    "LOCAL",
    "NASCIMENTO",
    "NATURALIDADE",
    "DATA",
    "EMISSÃO",
    "EMISSAO",
    "VALIDADE",
    "FILIACAO",
    "FILIAÇÃO",
    "FILIA",
    "MAE",
    "MÃE",
    "PAI",
    "PERMISSAO",
    "PERMISSÃO",
    "REGISTRO",
    "RENACH",
    "CPF",
    "DOC",
    "DOCUMENTO",
    "IDENTIDADE",
    "ORGAO",
    "ÓRGÃO",
    "EMISSOR",
    "CATEGORIA",
    "CAT",
    "HAB",
    # EN/ES
    "DATE",
    "PLACE",
    "BIRTH",
    "NATIONALITY",
    "ISSUE",
    "EXPIRY",
    "EXPIRATION",
    "VALID",
    "FILIATION",
    "FILIACION",
}


def _contains_field_label_noise(s: str) -> bool:
    u = _upper(_strip_leading_enum(s))
    if not u:
        return False
    for tok in _FIELD_LABEL_NOISE_TOKENS:
        if tok in u:
            return True
    return False


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


_UF_SET = {'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'}


def _looks_like_state_uf(tok: str) -> bool:
    tok = _upper(tok)
    tok = re.sub(r"[^A-Z]", "", tok)
    return tok in _UF_SET


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


def _extract_categoria_from_lines(lines: list[str], *, _dbg: Optional[dict[str, Any]] = None) -> Optional[str]:
    """
    Estratégia:
      PASSO 0 (alto-confiável): procurar padrão "CPF + REGISTRO(11d) + CATEGORIA" na mesma linha
      ou em 2 linhas concatenadas (linha i + i+1). Isso evita pegar letra 'E/A' perdida no lugar errado.

      Depois, cai no método do anchor "CAT HAB" (com lookahead) e por fim no fallback "CATEGORIA:".
    """
    if _dbg is not None:
        _dbg.setdefault("categoria_debug", {})
        _dbg["categoria_debug"].setdefault("hits", [])
        _dbg["categoria_debug"].setdefault("fallback_hits", [])
        _dbg["categoria_debug"].setdefault("chosen", None)

    # ----------------------------
    # PASSO 0: CPF + REGISTRO + CATEGORIA
    # ----------------------------
    cpf_pat = r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"
    reg_pat = r"\b\d{11}\b"

    # Procurar 2 letras primeiro (AB/AC/AD/AE), depois 1 letra.
    pat_2 = re.compile(rf"({cpf_pat}).*?({reg_pat}).*?\b(AB|AC|AD|AE)\b")
    pat_1 = re.compile(rf"({cpf_pat}).*?({reg_pat}).*?\b(A|B|C|D|E)\b")

    for i in range(min(len(lines), 260)):
        l0 = lines[i]
        l1 = _safe_get(lines, i + 1)
        combo = _upper(l0 + " " + l1)

        m2 = pat_2.search(combo)
        if m2:
            cand = m2.group(3)
            if cand in _ALLOWED_CATEGORIAS:
                if _dbg is not None:
                    _dbg["categoria_debug"]["chosen"] = {
                        "value": cand,
                        "mode": "cpf_registro_categoria_2letters",
                        "line": _upper(l0),
                        "lookahead200": combo[:200],
                    }
                return cand

        m1 = pat_1.search(combo)
        if m1:
            cand = m1.group(3)
            if cand in _ALLOWED_CATEGORIAS:
                # NÃO aceitar "A" se houver qualquer 2-letras no combo (mesmo distante)
                if cand == "A" and re.search(r"\b(AB|AC|AD|AE)\b", combo):
                    continue

                if _dbg is not None:
                    _dbg["categoria_debug"]["chosen"] = {
                        "value": cand,
                        "mode": "cpf_registro_categoria_1letter",
                        "line": _upper(l0),
                        "lookahead200": combo[:200],
                    }
                return cand

    # ----------------------------
    # PASSO 1+: Anchor CAT HAB (com lookahead)
    # ----------------------------
    def _is_placeholder_tail(t: str) -> bool:
        if not t:
            return False
        eq = t.count("=")
        letters = sum(1 for ch in t if "A" <= ch <= "Z")
        return eq >= 2 and letters <= 2

    for i, ln in enumerate(lines[:300]):
        u = _upper(ln)

        if not re.search(r"\b9\b", u):
            continue
        if "CAT" not in u:
            continue
        if "HAB" not in u and "CATHAB" not in u.replace(" ", ""):
            continue
        if "REGIST" not in u:
            continue

        anchor_match = re.search(r"(CAT\s*HAB|CATHAB)", u)
        if not anchor_match:
            continue

        tail = u[anchor_match.end() :]
        tail80 = tail[:80]
        tail25 = tail[:25]

        if _dbg is not None:
            _dbg["categoria_debug"]["hits"].append({"line": u, "tail80": tail80, "tail25": tail25})

        # 1) Preferir 2 letras na própria linha
        for m in re.finditer(r"\b(AB|AC|AD|AE)\b", tail80):
            cand = m.group(1)
            if cand in _ALLOWED_CATEGORIAS:
                if _dbg is not None:
                    _dbg["categoria_debug"]["chosen"] = {"value": cand, "mode": "cat_hab_2letters_same_line", "line": u}
                return cand

        next1 = _upper(_safe_get(lines, i + 1))
        next2 = _upper(_safe_get(lines, i + 2))
        lookahead = (tail + " " + next1 + " " + next2).strip()
        lookahead200 = lookahead[:200]

        tail_has_only_A = bool(re.search(r"\bA\b", tail25)) and not bool(
            re.search(r"\b(B|C|D|E|AB|AC|AD|AE)\b", tail80)
        )
        if _is_placeholder_tail(tail25) or tail_has_only_A:
            m2 = re.search(r"\b(AB|AC|AD|AE)\b", lookahead200)
            if m2:
                cand = m2.group(1)
                if cand in _ALLOWED_CATEGORIAS:
                    if _dbg is not None:
                        _dbg["categoria_debug"]["chosen"] = {
                            "value": cand,
                            "mode": "cat_hab_2letters_lookahead",
                            "line": u,
                            "lookahead200": lookahead200,
                        }
                    return cand

            m3 = re.search(r"\b(B|C|D|E)\b", lookahead200)
            if m3:
                cand = m3.group(1)
                if cand in _ALLOWED_CATEGORIAS:
                    if _dbg is not None:
                        _dbg["categoria_debug"]["chosen"] = {
                            "value": cand,
                            "mode": "cat_hab_1letter_lookahead",
                            "line": u,
                            "lookahead200": lookahead200,
                        }
                    return cand

        # 3) Só então aceitar 1 letra na própria linha
        for m in re.finditer(r"\b(A|B|C|D|E)\b", tail25):
            cand = m.group(1)
            if cand in _ALLOWED_CATEGORIAS:
                if _dbg is not None:
                    _dbg["categoria_debug"]["chosen"] = {"value": cand, "mode": "cat_hab_1letter_same_line", "line": u}
                return cand

    # ----------------------------
    # PASSO 2: fallback label direto
    # ----------------------------
    for i, ln in enumerate(lines[:260]):
        u = _upper(ln)
        if "CATEG" not in u and "CAT" not in u:
            continue

        if _dbg is not None:
            _dbg["categoria_debug"]["fallback_hits"].append({"line": u})

        m = re.search(r"\bCATEG(?:ORIA)?\b\s*[:\-]?\s*(.+)$", u)
        if m:
            tail = m.group(1).strip()
            m2 = re.match(r"^([A-E](?:\s*[\-\.]?\s*[B-E])?)\b", tail)
            if m2:
                cand = _normalize_categoria_token(m2.group(1))
                if cand in _ALLOWED_CATEGORIAS:
                    if _dbg is not None:
                        _dbg["categoria_debug"]["chosen"] = {"value": cand, "mode": "categ_label", "line": u}
                    return cand
            cand_inline = _normalize_categoria_token(tail)
            if cand_inline in _ALLOWED_CATEGORIAS:
                if _dbg is not None:
                    _dbg["categoria_debug"]["chosen"] = {"value": cand_inline, "mode": "categ_label_inline", "line": u}
                return cand_inline

        for j in range(1, 4):
            nxt = _safe_get(lines, i + j)
            if not nxt:
                continue
            nu = _upper(nxt)
            stripped = re.sub(r"\s+", "", nu)
            if len(stripped) > 8:
                continue
            cand2 = _normalize_categoria_token(nu)
            if cand2 in _ALLOWED_CATEGORIAS:
                if _dbg is not None:
                    _dbg["categoria_debug"]["chosen"] = {"value": cand2, "mode": "categ_nextline", "line": nu}
                return cand2

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

    # Evita capturar labels multilíngues ("LOCAL DE NASCIMENTO / DATE AND PLACE", etc.) como nome.
    if _contains_field_label_noise(s0):
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

    if _contains_field_label_noise(s):
        return -10**7

    toks = s.split()
    if len(toks) < 2:
        return -10**6

    score = 0
    score += min(len(toks), 7) * 10
    score += int(_alpha_ratio_letters_only(s) * 40)

    # bônus por partículas típicas
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
    # Procura do fim para o começo (em PDFs exportados, MRZ costuma estar no rodapé).
    # Regra determinística: precisa ter o padrão SOBRENOME<<NOME(s).
    for ln in reversed(lines[-220:]):
        if "<<" not in ln:
            continue

        u = _upper(ln)
        if not re.search(r"[A-Z]{2,}<<[A-Z]", u):
            continue

        # Alguns OCRs duplicam a MRZ ou trazem lixo no começo; pega apenas o maior bloco com '<<'.
        blocks = [b for b in re.split(r"\s+", u) if "<<" in b]
        candidate_block = max(blocks, key=len) if blocks else u

        # Normaliza: SOBRENOME<<NOMES<... -> "SOBRENOME NOMES"
        if "<<" in candidate_block:
            left, right = candidate_block.split("<<", 1)
            right = right.replace("<", " ")
            cand = f"{left} {right}"
        else:
            cand = candidate_block.replace("<", " ")

        cand = _clean_person_name_line(cand)
        if _is_plausible_fullname(cand):
            return cand

    return None


def _extract_nome(lines: list[str]) -> Optional[str]:
    """
    Estratégia (determinística e auditável):
    0) MRZ (<<) quando presente e plausível. (Maior confiabilidade nos PDFs exportados.)
    1) Campo imediatamente após label de nome ("NOME", "NOME E SOBRENOME", "NOME CIVIL", "NAME").
    2) Fallback: melhor candidato por score (após filtros anti-label/institucional).
    """
    # 0) MRZ primeiro
    mrz = _extract_mrz_name(lines)
    if mrz:
        return mrz

    candidates: list[str] = []

    # 1) Label de nome -> linha seguinte / inline
    # Nota: percorre um pouco mais para cobrir variações (alguns PDFs repetem blocos).
    name_label_re = re.compile(
        r"\b(NOME\s+E\s+SOBRENOME|NOME\s+CIVIL|NOME|NAME)\b\s*[:\-]?\s*(.*)$"
    )

    # tokens que, se aparecerem na MESMA linha do label, indicam header multi-campo (rejeitar)
    label_line_reject = {
        "LOCAL",
        "NASCIMENTO",
        "DATE",
        "PLACE",
        "BIRTH",
        "NATURALIDADE",
        "FILIAC",
        "CPF",
        "CAT",
        "HAB",
        "REGISTRO",
    }

    for i, ln in enumerate(lines[:220]):
        u = _upper(ln)
        if "NOME" not in u and "NAME" not in u:
            continue

        # Se a linha parece um header cheio de outros campos, rejeita.
        if any(tok in u for tok in label_line_reject) and not u.strip().startswith("NOME") and not u.strip().startswith("NAME"):
            continue

        m = name_label_re.search(u)
        if not m:
            continue

        tail = m.group(2) or ""
        cand_inline = _clean_person_name_line(tail)
        if cand_inline and _is_plausible_fullname(cand_inline):
            candidates.append(cand_inline)

        # Próximas linhas (primeira que não é outro label)
        for j in (1, 2, 3):
            nxt = _upper(_safe_get(lines, i + j))
            if not nxt:
                continue
            # Evita cair em "NOME CIVIL"/"CPF" etc.
            if name_label_re.search(nxt) and ("NOME" in nxt or "NAME" in nxt):
                continue
            if _contains_institutional_noise(nxt) or _contains_field_label_noise(nxt):
                continue
            cand2 = _clean_person_name_line(nxt)
            if _is_plausible_fullname(cand2):
                candidates.append(cand2)
                break

    if candidates:
        candidates.sort(key=_name_candidate_score, reverse=True)
        return candidates[0]

    # 2) Fallback por score (com filtros já embutidos em _is_plausible_fullname)
    scored: list[tuple[int, str]] = []
    for ln in lines[:140]:
        # Rejeita linhas muito longas: geralmente são frases institucionais ou blocos concatenados.
        if len(_upper(ln)) > 90:
            continue
        cand = _clean_person_name_line(ln)
        if _is_plausible_fullname(cand):
            scored.append((_name_candidate_score(cand), cand))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    return None


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
    out: list[str] = []

    for ln in lines[:260]:
        mae = _extract_after_label(ln, r"\bM[ÃA]E\b\s*[:\-]?\s*")
        if mae and _is_plausible_filiacao_line(mae):
            out.append(mae)

        pai = _extract_after_label(ln, r"\bPAI\b\s*[:\-]?\s*")
        if pai and _is_plausible_filiacao_line(pai):
            out.append(pai)

    if not out:
        for i, ln in enumerate(lines[:260]):
            u = _upper(ln)
            letters = re.sub(r"[^A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ]", "", u)

            is_filiacao_marker = ("FILIA" in letters) or ("FILIAC" in letters) or ("FILI" in letters and "AO" in letters)
            is_filiacao_marker = is_filiacao_marker or ("FI" in letters and "ICAO" in letters)

            if is_filiacao_marker:
                tail = re.split(r"(FILIA(?:ÇÃO|CAO)?|FILIACAO|FILIATION|FILIACION)", u, maxsplit=1)
                if len(tail) >= 3:
                    cand = _clean_person_name_line(tail[-1])
                    if cand and _is_plausible_filiacao_line(cand):
                        out.append(cand)

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

    dedup: list[str] = []
    seen = set()
    for x in out:
        k = _upper(x)
        if k and k not in seen:
            dedup.append(k)
            seen.add(k)

    return dedup


def _extract_nascimento_validade(text: str, dates: list[str]) -> tuple[Optional[str], Optional[str]]:
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
    """Best-effort extraction of (cidade, UF) for naturalidade.

    CNH exportada do app costuma trazer a naturalidade no bloco:
    "DATA, LOCAL E UF DE NASCIMENTO" e o valor no formato:
        DD/MM/AAAA, CIDADE, UF

    Alguns OCRs também trazem "NATURALIDADE".

    Regras:
    - Nunca inventa: só retorna se encontrar UF válida (whitelist) e cidade plausível.
    - Determinístico: baseado em âncoras e regex, sem heurísticas probabilísticas.
    """

    def _extract_from_text(txt: str) -> tuple[Optional[str], Optional[str]]:
        u = _upper(txt)
        # Padrão principal: data, cidade, UF (com vírgulas)
        m = re.search(
            r"\b(\d{2}[/-]\d{2}[/-]\d{4})\s*,\s*([A-ZÀ-Ú][A-ZÀ-Ú\s'\-\.]{2,}?)\s*,\s*([A-Z]{2})\b",
            u,
        )
        if not m:
            return None, None
        cidade = _norm_spaces(m.group(2)).strip(" \t\"'|.,;-_")
        uf = re.sub(r"[^A-Z]", "", m.group(3))
        if not uf or uf not in _UF_SET:
            return None, None
        if not cidade or len(cidade) < 3:
            return None, None
        if _alpha_ratio_letters_only(cidade) < 0.6:
            return None, None
        return cidade, uf

    for i, ln in enumerate(lines):
        u = _upper(ln)

        # 1) Âncora forte do bloco de naturalidade (OCR pode distorcer, então é por contains)
        if ("LOCAL" in u and "UF" in u and "NASC" in u):
            chunk = "\n".join([ln, _safe_get(lines, i + 1), _safe_get(lines, i + 2)])
            cidade, uf = _extract_from_text(chunk)
            if cidade and uf:
                return cidade, uf

        # 2) Fallback: NATURALIDADE / NATURAL
        if "NATURAL" in u:
            tail = re.split(r"NATURAL(?:IDADE)?\s*[:\-]?\s*", u, maxsplit=1)
            cand = tail[1] if len(tail) == 2 else ""
            chunk = "\n".join([cand, _safe_get(lines, i + 1), _safe_get(lines, i + 2)])
            cidade, uf = _extract_from_text(chunk)
            if cidade and uf:
                return cidade, uf

            # ainda assim: alguns OCRs trazem "CIDADE, UF" sem data
            u2 = _upper(_safe_get(lines, i + 1))
            m2 = re.search(r"\b([A-ZÀ-Ú][A-ZÀ-Ú\s'\-\.]{2,}?)\s*,\s*([A-Z]{2})\b", u2)
            if m2:
                cidade = _norm_spaces(m2.group(1)).strip(" \t\"'|.,;-_")
                uf = re.sub(r"[^A-Z]", "", m2.group(2))
                if uf in _UF_SET and cidade and _alpha_ratio_letters_only(cidade) >= 0.6:
                    return cidade, uf

    return None, None


def analyze_cnh(
    raw_text: str,
    *,
    filename: Optional[str] = None,
    **_kwargs: Any,
) -> tuple[dict, dict]:
    text = raw_text or ""
    lines = _strip_noise_lines(text.splitlines())

    dbg: dict[str, Any] = {"filename": filename}

    cpf = _pick_best_cpf(text)
    dates = _find_all_dates(text)
    data_nasc, validade = _extract_nascimento_validade(text, dates)

    nome = _extract_nome(lines)
    categoria = _extract_categoria_from_lines(lines, _dbg=dbg)
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

    # ----------------------------
    # Hard checks (não bloqueia; reporta parse_error)
    # ----------------------------
    missing: list[str] = []
    invalid: list[str] = []

    # Nome
    if not (nome and isinstance(nome, str) and _is_plausible_fullname(nome)):
        missing.append("nome")

    # CPF
    if not (cpf and isinstance(cpf, str) and len(cpf) == 11 and cpf.isdigit()):
        missing.append("cpf")

    # Datas
    if not (data_nasc and re.match(r"^\d{2}/\d{2}/\d{4}$", data_nasc)):
        missing.append("data_nascimento")
    if not (validade and re.match(r"^\d{2}/\d{2}/\d{4}$", validade)):
        missing.append("validade")

    # Categoria
    if not (categoria and categoria in _ALLOWED_CATEGORIAS):
        missing.append("categoria")

    # Filiação (best-effort; mas audita)
    if filiacao is None:
        invalid.append("filiacao:null")
    else:
        if not isinstance(filiacao, list):
            invalid.append("filiacao:not_list")
        else:
            if len(filiacao) == 0:
                invalid.append("filiacao:empty")

    parse_error: Optional[dict] = None
    if missing or invalid:
        parse_error = {
            "type": "ParserError",
            "code": "CNH_REQUIRED_FIELDS_MISSING_OR_INVALID",
            "message": "CNH parse incomplete (non-blocking).",
            "missing": missing,
            "invalid": invalid,
        }

    dbg.update(
        {
            "found_dates": dates,
            "found_cpfs": _find_all_cpfs(text),
            "extracted": {k: fields.get(k) for k in ["nome", "cpf", "categoria", "data_nascimento", "validade"]},
            "parse_error": parse_error,
        }
    )

    return _wq_wrap_return_v1(fields, dbg, parse_error)
