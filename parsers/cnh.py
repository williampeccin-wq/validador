# parsers/cnh.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_UF_RE = re.compile(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b")
_MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{20,}$")


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _normalize_person_name(s: str) -> str:
    """
    Normalize a candidate person name extracted from OCR text.

    OCR para CNH/SENATRAN frequentemente injeta tokens lixo ao redor dos campos.
    """
    if not s:
        return ""

    s = s.split("|", 1)[0]
    s = s.upper().strip()
    s = _DATE_RE.sub(" ", s)

    s = re.sub(r"[\[\]\(\)\{\}<>]", " ", s)
    s = re.sub(r"[^A-ZÀ-Ü\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""

    keep_connectors = {"DE", "DA", "DO", "DAS", "DOS"}
    junk_tokens = {
        "KE", "KH", "RTF", "GE", "GI", "NM", "MM", "NA", "ALO", "ACC",
        "QR", "CODE",
    }
    vowel_re = re.compile(r"[AEIOUÀ-Ü]")

    out: List[str] = []
    for tok in s.split():
        if tok in keep_connectors:
            out.append(tok)
            continue
        if tok in junk_tokens:
            continue
        if len(tok) <= 1:
            continue
        if len(tok) <= 3 and not vowel_re.search(tok):
            continue
        out.append(tok)

    while out and out[0] in keep_connectors:
        out.pop(0)
    while out and out[-1] in keep_connectors:
        out.pop()

    return " ".join(out)


def _extract_cpf(text_upper: str) -> Optional[str]:
    if not text_upper:
        return None
    m = _CPF_RE.search(text_upper)
    if not m:
        return None
    cpf = _only_digits(m.group(0))
    return cpf if len(cpf) == 11 else None


def _extract_all_dates(text_upper: str) -> List[str]:
    if not text_upper:
        return []
    return _DATE_RE.findall(text_upper)


def _is_mrz_line(line: str) -> bool:
    if not line:
        return False
    s = line.strip().upper()
    if not _MRZ_LINE_RE.match(s):
        return False
    return s.count("<") >= 5


def _extract_name_from_mrz(lines: List[str]) -> Optional[str]:
    """Extract name from MRZ-like line, e.g. 'ANDERSON<<SANTOS<DE<BARROS<<<<'."""
    for ln in lines:
        s = ln.strip().upper()
        if not _is_mrz_line(s):
            continue
        parts = [p for p in s.split("<") if p]
        if not parts:
            continue
        candidate = " ".join(parts)
        candidate = _normalize_person_name(candidate)
        if candidate and len(candidate.split()) >= 2:
            return candidate
    return None


def _find_best_name_candidate(lines: List[str]) -> Optional[str]:
    mrz = _extract_name_from_mrz(lines)
    if mrz:
        return mrz

    for i, ln in enumerate(lines):
        u = ln.upper()
        if "NOME" in u and ("SOBRENOME" in u or "NAME" in u):
            if i + 1 < len(lines):
                cand = _normalize_person_name(lines[i + 1])
                if cand and len(cand.split()) >= 2:
                    return cand

    best = None
    best_score = -1
    for ln in lines:
        cand = _normalize_person_name(ln)
        toks = cand.split()
        if len(toks) < 2:
            continue
        score = len(toks)
        if 3 <= len(toks) <= 6:
            score += 2
        if len(toks) > 8:
            score -= 2
        if score > best_score:
            best_score = score
            best = cand

    return best


def _find_city_uf(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Try parse: '12/07/1987, FLORIANOPOLIS, SC'."""
    for ln in lines:
        u = ln.upper()
        if _DATE_RE.search(u) and "," in u:
            parts = [p.strip() for p in u.split(",")]
            if len(parts) >= 3:
                city = parts[1].strip()
                uf_m = _UF_RE.search(parts[2])
                uf = uf_m.group(1) if uf_m else None
                city = re.sub(r"[^A-ZÀ-Ü\s]", " ", city)
                city = _normalize_spaces(city)
                if city and uf:
                    return city, uf
    return None, None


def _find_validade(lines: List[str]) -> Optional[str]:
    dates = _extract_all_dates("\n".join(lines).upper())
    if not dates:
        return None

    def key(d: str) -> Tuple[int, int, int]:
        dd, mm, yy = d.split("/")
        return int(yy), int(mm), int(dd)

    return sorted(dates, key=key)[-1]


def _find_data_nascimento(lines: List[str]) -> Optional[str]:
    for ln in lines:
        u = ln.upper()
        if "," in u and _DATE_RE.search(u):
            ds = _extract_all_dates(u)
            if ds:
                return ds[0]

    dates = _extract_all_dates("\n".join(lines).upper())
    if not dates:
        return None

    def key(d: str) -> Tuple[int, int, int]:
        dd, mm, yy = d.split("/")
        return int(yy), int(mm), int(dd)

    return sorted(dates, key=key)[0]


def _find_categoria_prefere_registro(text_upper: str, cpf_digits: Optional[str]) -> Optional[str]:
    """
    Extrai categoria simples/composta (A-E / AB / AE etc) da zona de registro.
    """
    if not text_upper:
        return None

    matches = list(re.finditer(r"\b(\d{11})\b\s+([A-E]{1,2})\b", text_upper))
    if matches:
        filtered = []
        for m in matches:
            num = m.group(1)
            cat = m.group(2)
            if cpf_digits and num == cpf_digits:
                continue
            filtered.append((m.start(), num, cat))

        pool = filtered if filtered else [(m.start(), m.group(1), m.group(2)) for m in matches]
        pool.sort(key=lambda x: x[0])
        return pool[-1][2]

    m2 = re.search(r"\bCAT\b.{0,60}\b([A-E]{1,2})\b", text_upper)
    if m2:
        return m2.group(1)

    return None


def _clean_filiacao_line(s: str) -> str:
    """
    Limpa ruído de OCR no bloco FILIAÇÃO.
    """
    if not s:
        return ""

    u = s.upper()
    u = u.split("|", 1)[0]
    u = re.sub(r"\bFILIA(?:ÇÃO|CAO)\b", " ", u)
    u = re.sub(r"[^A-ZÀ-Ü\s]", " ", u)
    u = _normalize_spaces(u)
    if not u:
        return ""

    keep_connectors = {"DE", "DA", "DO", "DAS", "DOS"}

    # ⚠️ tokens lixo típicos do campo (inclui os que você viu no Anderson)
    junk_tokens = {
        "S", "M", "O", "OO", "ES", "GI", "NM", "MM", "EM", "RE", "IO", "LH",
        "WERT", "LAT", "LALATE",
        "ASSINATURA", "PORTADOR", "OBSERVACOES", "OBSERVAÇÕES",
        "NACIONALIDADE", "BRASILEIRO", "LEMA",
        "CAT", "HAB", "CNH",
    }

    vowel_re = re.compile(r"[AEIOUÀ-Ü]")

    out: List[str] = []
    for tok in u.split():
        if tok in keep_connectors:
            out.append(tok)
            continue
        if tok in junk_tokens:
            continue

        # regra dura para tirar "LH IO" etc
        if len(tok) < 3:
            continue

        # tokens curtos sem vogal são quase sempre lixo
        if len(tok) <= 3 and not vowel_re.search(tok):
            continue

        out.append(tok)

    while out and out[0] in keep_connectors:
        out.pop(0)
    while out and out[-1] in keep_connectors:
        out.pop()

    return " ".join(out)


def _score_parent_line(s: str) -> float:
    """
    Score de “linha de nome de pai/mãe”.
    Queremos privilegiar nomes com muitas vogais e palavras longas,
    e derrubar linhas “sem sentido”.
    """
    if not s:
        return 0.0
    toks = s.split()
    if len(toks) < 2:
        return 0.0

    vowel_re = re.compile(r"[AEIOUÀ-Ü]")
    vowels = sum(len(vowel_re.findall(t)) for t in toks)
    letters = sum(len(t) for t in toks)
    vowel_ratio = (vowels / letters) if letters else 0.0

    avg_len = letters / max(1, len(toks))
    connectors = {"DE", "DA", "DO", "DAS", "DOS"}
    has_connector = any(t in connectors for t in toks)

    # base
    score = 0.0
    score += 2.0 * vowel_ratio
    score += 0.15 * avg_len
    score += 0.6 if has_connector else 0.0
    score += 0.25 * min(6, len(toks))

    # penaliza tokens “estranhos” recorrentes
    bad = {"WERT", "LAT", "LALATE"}
    if any(t in bad for t in toks):
        score -= 2.0

    return score


def _find_filiacao(lines: List[str]) -> List[str]:
    """
    Extrai FILIAÇÃO:
    - coleta candidatos logo após o label
    - faz ranking por score
    - devolve 1 ou 2 linhas boas (descarta lixo tipo “WERT LAT LALATE”)
    """
    stop_markers = ("ASSINAT", "OBSERV", "NACIONAL", "LEMA", "LOCAL", "I<BR", "SERPRO", "SENATRAN")
    candidates: List[str] = []

    start_idx = None
    for i, ln in enumerate(lines):
        if "FILIA" in ln.upper():
            start_idx = i
            break

    if start_idx is None:
        return []

    for j in range(start_idx + 1, min(start_idx + 14, len(lines))):
        raw = lines[j]
        u = raw.upper()
        if any(m in u for m in stop_markers):
            break

        cleaned = _clean_filiacao_line(raw)
        if not cleaned:
            continue

        if cleaned not in candidates:
            candidates.append(cleaned)

        # não precisa varrer infinito
        if len(candidates) >= 4:
            break

    if not candidates:
        return []

    scored = sorted(((c, _score_parent_line(c)) for c in candidates), key=lambda x: x[1], reverse=True)
    best, best_score = scored[0]

    # pega o segundo só se for “quase tão bom quanto”
    out = [best]
    if len(scored) >= 2:
        second, second_score = scored[1]
        # threshold relativo: evita adicionar lixo
        if second_score >= 0.70 * best_score and second_score >= 1.4:
            out.append(second)

    return out


def analyze_cnh(raw_text: str, filename: str | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse CNH (SENATRAN/SERPRO) from extracted text. Returns (fields, debug)."""
    raw_text = raw_text or ""
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    utext = raw_text.upper()

    nome = _find_best_name_candidate(lines)
    cpf = _extract_cpf(utext)
    categoria = _find_categoria_prefere_registro(utext, cpf_digits=cpf)
    validade = _find_validade(lines)
    data_nascimento = _find_data_nascimento(lines)
    cidade, uf = _find_city_uf(lines)
    filiacao = _find_filiacao(lines)

    low_signal = len(utext) < 1200 or (not cpf and not validade)

    fields = {
        "nome": nome,
        "cpf": cpf,
        "categoria": categoria,
        "data_nascimento": data_nascimento,
        "validade": validade,
        "cidade_nascimento": cidade,
        "uf_nascimento": uf,
        "filiacao": filiacao,
    }

    dbg = {
        "mode": "senatran",
        "filename": filename,
        "text_len": len(raw_text),
        "found_dates": _extract_all_dates(utext),
        "nome_detectado": nome,
        "categoria_detectada": categoria,
        "validade_detectada": validade,
        "cidade_uf_detectado": {"cidade": cidade, "uf": uf},
        "filiacao_detectada": filiacao,
        "low_signal": low_signal,
    }

    return fields, dbg
