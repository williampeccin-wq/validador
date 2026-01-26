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
    """Normalize a candidate person name extracted from OCR text.

    OCR for CNH/SENATRAN frequently appends garbage tokens (e.g. "KE RTF E E GE A")
    from UI glyphs around the name field. This function aggressively cleans those
    artifacts while keeping legitimate Portuguese connectors (DE/DA/DO/DAS/DOS).
    """
    if not s:
        return ""

    # Keep only the left side when OCR uses "|" separators
    s = s.split("|", 1)[0]

    s = s.upper().strip()
    # Remove dates that often appear on the same line as the name
    s = _DATE_RE.sub(" ", s)

    # Strip bracket-like noise and non-letter characters (keep spaces)
    s = re.sub(r"[\[\]\(\)\{\}<>]", " ", s)
    s = re.sub(r"[^A-ZÀ-Ü\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    if not s:
        return ""

    keep_connectors = {"DE", "DA", "DO", "DAS", "DOS"}
    junk_tokens = {
        # Common OCR debris around CNH name field
        "KE", "KH", "RTF", "GE", "GI", "NM", "MM", "NA", "ALO", "ACC",
        "QR", "CODE",
    }
    vowel_re = re.compile(r"[AEIOUÀ-Ü]")

    out = []
    for tok in s.split():
        if tok in keep_connectors:
            out.append(tok)
            continue
        if tok in junk_tokens:
            continue
        # Drop single-letter tokens ("E" is almost always noise here)
        if len(tok) <= 1:
            continue
        # Drop short tokens with no vowels (e.g. "RTF")
        if len(tok) <= 3 and not vowel_re.search(tok):
            continue
        out.append(tok)

    # Remove connector leftovers at ends (e.g. "DE" as last token)
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
    """Prefer MRZ-derived name. Fallback to the 'NOME' context line."""
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
    Extract category from the *registration-number zone*:
      - look for: 11 digits + whitespace + single-letter category [A-E]
      - ignore a match where the 11 digits == CPF (CPF is also 11 digits)
      - if multiple matches exist, prefer the right-most one (closest to the CNH layout row)
    """
    if not text_upper:
        return None

    matches = list(re.finditer(r"\b(\d{11})\b\s+([A-E])\b", text_upper))
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

    m2 = re.search(r"\bCAT\b.{0,60}\b([A-E])\b", text_upper)
    if m2:
        return m2.group(1)

    return None


def _clean_filiacao_line(s: str) -> str:
    """
    Clean OCR noise from filiacao lines while preserving real names.
    Goal: return something like 'EDSON ESPINDOLA DE BARROS' / 'SONIA MARIA DOS SANTOS'.
    """
    if not s:
        return ""

    u = s.upper()

    # Cut off right-side junk if OCR uses separators
    u = u.split("|", 1)[0]

    # Drop the label itself if it leaked into the line
    u = re.sub(r"\bFILIA(?:ÇÃO|CAO)\b", " ", u)

    # Keep only letters/spaces
    u = re.sub(r"[^A-ZÀ-Ü\s]", " ", u)
    u = _normalize_spaces(u)

    if not u:
        return ""

    keep_connectors = {"DE", "DA", "DO", "DAS", "DOS"}
    # Very common garbage tokens in this region (from UI glyphs / OCR artifacts)
    junk_tokens = {
        "S", "M", "O", "OO", "ES", "GI", "NM", "MM", "EM", "RE", "IO", "LH",
        "WERT", "LAT", "LALATE", "TR", "AH", "B",
        "ASSINATURA", "PORTADOR", "OBSERVACOES", "OBSERVAÇÕES",
        "NACIONALIDADE", "BRASILEIRO", "LEMA",
    }
    vowel_re = re.compile(r"[AEIOUÀ-Ü]")

    out: List[str] = []
    for tok in u.split():
        if tok in keep_connectors:
            out.append(tok)
            continue
        if tok in junk_tokens:
            continue
        # Drop single-letter tokens
        if len(tok) <= 1:
            continue
        # Drop very short tokens without vowels (e.g. "TR")
        if len(tok) <= 2 and not vowel_re.search(tok):
            continue
        out.append(tok)

    # Trim connectors at ends
    while out and out[0] in keep_connectors:
        out.pop(0)
    while out and out[-1] in keep_connectors:
        out.pop()

    return " ".join(out)


def _is_plausible_person_line(s: str) -> bool:
    """
    Heuristic: a plausible parent-name line should have >=2 tokens,
    and >=2 tokens should contain vowels (to reject 'WERT LAT ...').
    """
    if not s:
        return False
    toks = s.split()
    if len(toks) < 2:
        return False
    vowel_re = re.compile(r"[AEIOUÀ-Ü]")
    vowel_tokens = sum(1 for t in toks if vowel_re.search(t))
    if vowel_tokens < 2:
        return False
    # Reject if too many very short tokens (still noisy)
    short = sum(1 for t in toks if len(t) <= 2)
    if short >= max(2, len(toks) // 2):
        return False
    return True


def _find_filiacao(lines: List[str]) -> List[str]:
    """
    Extract filiacao (usually two lines: pai / mãe) after the 'FILIAÇÃO' label,
    aggressively filtering OCR noise.
    """
    stop_markers = ("ASSINAT", "OBSERV", "NACIONAL", "LEMA", "LOCAL", "I<BR", "SERPRO", "SENATRAN")
    out: List[str] = []

    start_idx = None
    for i, ln in enumerate(lines):
        if "FILIA" in ln.upper():
            start_idx = i
            break

    if start_idx is None:
        return []

    # Look ahead a bit; OCR sometimes repeats this block later, so keep it bounded.
    for j in range(start_idx + 1, min(start_idx + 10, len(lines))):
        raw = lines[j]
        u = raw.upper()
        if any(m in u for m in stop_markers):
            break

        cleaned = _clean_filiacao_line(raw)
        if not cleaned:
            continue
        if not _is_plausible_person_line(cleaned):
            continue

        # Avoid accidentally capturing the main name again
        if "CARTEIRA" in cleaned or "HABILIT" in cleaned:
            continue

        out.append(cleaned)
        if len(out) >= 2:
            break

    # Dedup
    dedup: List[str] = []
    for x in out:
        if x not in dedup:
            dedup.append(x)

    return dedup


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
