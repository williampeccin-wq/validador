<<<<<<< HEAD
# parsers/cnh.py
=======
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
<<<<<<< HEAD
# Normalização básica (contrato do golden)
# ============================================================

_NAME_JOINERS = {"DE", "DA", "DO", "DAS", "DOS", "E"}

_OCR_DIGIT_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "S": "5",
        "B": "8",
        "Z": "2",
        "G": "6",
    }
)


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _upper(s: str) -> str:
    return _strip_accents(s or "").upper()


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _cleanup_name(s: str) -> Optional[str]:
    if not s:
        return None

    u = _upper(s)
    u = re.sub(r"[^A-Z0-9 ]+", " ", u)
    u = _collapse_spaces(u)
    if not u:
        return None

    toks = u.split()
    cleaned: List[str] = []
    for t in toks:
        if t in _NAME_JOINERS:
            cleaned.append(t)
            continue
        if len(t) <= 2:
            continue
        cleaned.append(t)

    while cleaned and cleaned[0] in _NAME_JOINERS:
        cleaned.pop(0)
    while cleaned and cleaned[-1] in _NAME_JOINERS:
        cleaned.pop()

    collapsed: List[str] = []
    for t in cleaned:
        if collapsed and t in _NAME_JOINERS and collapsed[-1] in _NAME_JOINERS:
            continue
        collapsed.append(t)

    out = " ".join(collapsed).strip()
    return out or None


def _title_city(s: str) -> Optional[str]:
    if not s:
        return None
    u = _upper(s)
    u = re.sub(r"[^A-Z ]+", " ", u)
    u = _collapse_spaces(u)
    if not u:
        return None
    return u.title()


# ============================================================
# Datas dd/mm/yyyy
# ============================================================

def _find_dates_ddmmyyyy(text: str) -> List[str]:
    return re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", _upper(text))


def _parse_date_ddmmyyyy(d: str) -> Optional[date]:
    try:
        dd, mm, yyyy = d.split("/")
        return date(int(yyyy), int(mm), int(dd))
=======
# Utilitários
# ============================================================
_UFS_BR = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}

_BANNED_HEAD_TOKENS = {
    "REPUBLICA","FEDERATIVA","BRASIL","MINISTERIO","SECRETARIA","SENATRAN",
    "CARTEIRA","NACIONAL","HABILITACAO","DRIVER","LICENSE","PERMISO","CONDUCCION",
    "GOV","QRCODE","QR","CODE","DOCUMENTO","ASSINADOR","SERPRO","CERTIFICADO","DIGITAL"
}

_NAME_JOINERS = {"DE", "DA", "DO", "DOS", "DAS", "E"}

def _norm_spaces(txt: str) -> str:
    return re.sub(r"\s+", " ", (txt or "").replace("\u00a0", " ")).strip()

def _remover_acentos(txt: str) -> str:
    nfkd = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _upper(txt: str) -> str:
    return _norm_spaces(_remover_acentos(txt)).upper()

def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _extract_cpf(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b", text or "")
    if not m:
        return None
    cpf = _only_digits(m.group(1))
    return cpf if len(cpf) == 11 else None

def _find_dates(text: str) -> List[str]:
    return re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text or "")

def _parse_date_ddmmyyyy(s: str) -> Optional[Tuple[int, int, int]]:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (s or "").strip())
    if not m:
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= dd <= 31 and 1 <= mm <= 12 and 1900 <= yyyy <= 2100):
        return None
    return (yyyy, mm, dd)

def _dt_from_ddmmyyyy(s: str) -> Optional[date]:
    p = _parse_date_ddmmyyyy(s)
    if not p:
        return None
    yyyy, mm, dd = p
    try:
        return date(yyyy, mm, dd)
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
    except Exception:
        return None


# ============================================================
<<<<<<< HEAD
# CPF (checksum + tolerância OCR + sliding window)
# ============================================================

def _normalize_ocr_digits(s: str) -> str:
    if not s:
        return ""
    u = _upper(s)
    return u.translate(_OCR_DIGIT_TRANSLATION)


def _cpf_is_valid(cpf11: str) -> bool:
    if not cpf11 or len(cpf11) != 11 or not cpf11.isdigit():
        return False
    if cpf11 == cpf11[0] * 11:
        return False

    nums = [int(c) for c in cpf11]

    s1 = sum(nums[i] * (10 - i) for i in range(9))
    dv1 = (s1 * 10) % 11
    dv1 = 0 if dv1 == 10 else dv1
    if dv1 != nums[9]:
        return False

    s2 = sum(nums[i] * (11 - i) for i in range(10))
    dv2 = (s2 * 10) % 11
    dv2 = 0 if dv2 == 10 else dv2
    return dv2 == nums[10]


def _cpf_candidates_from_digit_stream(digits: str) -> List[str]:
    """
    Extrai candidatos por janela móvel de 11 dígitos em um stream contínuo.
    Retorna todos os CPFs válidos (checksum ok) na ordem em que aparecem.
    """
    out: List[str] = []
    if not digits or len(digits) < 11:
        return out

    for i in range(0, len(digits) - 10):
        cand = digits[i : i + 11]
        if _cpf_is_valid(cand):
            # evita duplicado imediato
            if not out or out[-1] != cand:
                out.append(cand)
    return out


def _extract_cpf(text: str) -> Optional[str]:
    """
    Estratégia robusta:
      1) procurar âncora "CPF" e olhar uma janela de caracteres depois dela
         - normaliza OCR->dígitos
         - gera stream de dígitos contínuo e faz sliding window
      2) fallback: varre o documento inteiro (stream contínuo) e faz sliding window
    """
    if not text:
        return None

    norm = _normalize_ocr_digits(text)

    # 1) Âncoras "CPF" (janela de 200 caracteres após a âncora)
    for m in re.finditer(r"\bCPF\b", norm):
        start = m.end()
        chunk = norm[start : start + 200]
        digits = re.sub(r"[^0-9]", "", chunk)
        cands = _cpf_candidates_from_digit_stream(digits)
        if cands:
            return cands[0]

    # 2) Fallback global: stream contínuo
    digits_all = re.sub(r"[^0-9]", "", norm)
    cands_all = _cpf_candidates_from_digit_stream(digits_all)
    if cands_all:
        return cands_all[0]

    return None


# ============================================================
# Nome / Nascimento / Local / Validade / Filiação
# ============================================================

def _extract_nome(text: str) -> Tuple[Optional[str], str]:
    u = _upper(text)

    m = re.search(r"\[\s*([A-Z][A-Z ]{8,80}?)\s*\]", u)
    if m:
        nm = _cleanup_name(m.group(1))
        return nm, "brackets"

    m = re.search(r"NOME\s+E\s+SOBRENOME.*?\n([A-Z][A-Z ]{8,80})", u, flags=re.DOTALL)
    if m:
        nm = _cleanup_name(m.group(1))
        return nm, "label_line"

    lines = [ln.strip() for ln in u.splitlines() if ln.strip()]
    for ln in lines[:12]:
        if len(ln) < 12:
            continue
        if any(ch.isdigit() for ch in ln):
            continue
        cand = _cleanup_name(ln)
        if cand and len(cand.split()) >= 2:
            return cand, "topline"
=======
# Datas: emissão e validade
# ============================================================
def _extract_emissao_validade(text: str) -> Tuple[Optional[str], Optional[str]]:
    u = _upper(text)

    m = re.search(r"DATA\s+EMISS[AÃ]O(.{0,240})", u, flags=re.IGNORECASE | re.DOTALL)
    if m:
        chunk = m.group(0)
        dates = _find_dates(chunk)
        if len(dates) >= 2:
            return dates[0], dates[1]

    m2 = re.search(r"\bVALIDADE\b.*?(\d{2}/\d{2}/\d{4})", u, flags=re.IGNORECASE | re.DOTALL)
    if m2:
        val = m2.group(1).strip()
        before = u[max(0, m2.start() - 180):m2.start()]
        dates = _find_dates(before)
        emissao = dates[-1] if dates else None
        return emissao, val

    return None, None


# ============================================================
# Limpeza de cidade (remove prefixos lixo tipo "MN")
# ============================================================
def _clean_city(raw_city: str) -> Optional[str]:
    if not raw_city:
        return None
    u = _upper(raw_city)

    # Remove tokens de cabeçalho caso tenham colado
    toks = [t for t in u.split() if t not in _BANNED_HEAD_TOKENS]

    # Remove "prefixos lixo": tokens curtos (<=2) que não são conectivos usuais e aparecem antes do primeiro token "real"
    cleaned: List[str] = []
    for t in toks:
        # permite conectivos (raros em cidade, mas não custa)
        if t in _NAME_JOINERS:
            cleaned.append(t)
            continue

        # token curto no começo -> provavelmente lixo ("MN", "OO", "M", etc.)
        if not cleaned and len(t) <= 2:
            continue

        # remove tokens curtos suspeitos mesmo no meio, exceto se for "DO/DA/DE" etc.
        if len(t) == 1:
            continue

        cleaned.append(t)

    # Se ainda ficou começando com token curto, remove em loop
    while cleaned and len(cleaned[0]) <= 2 and cleaned[0] not in _NAME_JOINERS:
        cleaned.pop(0)

    city = _norm_spaces(" ".join(cleaned))
    if not city:
        return None

    # "MN FLORIANOPOLIS" -> "FLORIANOPOLIS" (garante que exista ao menos 1 token 3+)
    if not any(len(t) >= 3 for t in city.split()):
        return None

    return city


# ============================================================
# Local (cidade/UF)
# ============================================================
def _best_city_uf_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    u = _upper(text)
    matches: List[Tuple[int, str, str]] = []

    for m in re.finditer(r"\b([A-ZÇÃÕÁÉÍÓÚ ]{3,60})\s*,\s*([A-Z]{2})\b", u):
        matches.append((m.start(), _norm_spaces(m.group(1)), m.group(2)))

    for m in re.finditer(r"\b([A-ZÇÃÕÁÉÍÓÚ ]{3,60})\s+([A-Z]{2})\b", u):
        matches.append((m.start(), _norm_spaces(m.group(1)), m.group(2)))

    if not matches:
        return None, None

    best = None
    best_score = -10**9
    L = len(u)

    for pos, cidade_raw, uf in matches:
        if uf not in _UFS_BR:
            continue

        cidade = _clean_city(cidade_raw)
        if not cidade:
            continue

        # evita cabeçalho
        if set(cidade.split()) & _BANNED_HEAD_TOKENS:
            continue

        score = pos
        window = u[max(0, pos - 140): min(L, pos + 140)]
        if "DEPARTAMENTO ESTADUAL" in window or "DE TRANSITO" in window or "DETRAN" in window:
            score += 2000

        if score > best_score:
            best_score = score
            best = (cidade, uf)

    return best if best else (None, None)


# ============================================================
# Nome — fonte primária: valor entre colchetes [NOME COMPLETO]
# ============================================================
def _clean_person_name(raw: str) -> Optional[str]:
    """
    Limpa ruídos do OCR e mantém só tokens plausíveis de nome:
    - remove tokens de 1 letra (S, M, O etc.)
    - remove tokens de 2 letras que não sejam conectivos (DE/DA/DO/DOS/DAS/E)
    - remove tokens de cabeçalho
    """
    if not raw:
        return None
    u = _upper(raw)

    # mantém letras e espaços
    u = re.sub(r"[^A-ZÇÃÕÁÉÍÓÚ\s]", " ", u)
    u = _norm_spaces(u)

    toks_in = u.split()
    toks: List[str] = []
    for t in toks_in:
        if t in _BANNED_HEAD_TOKENS:
            continue
        if len(t) == 1:
            continue
        if len(t) == 2 and t not in _NAME_JOINERS:
            # "MM", "OO", "RE" etc. -> lixo
            continue
        toks.append(t)

    # remove prefixos curtos sobrando (resíduo do OCR)
    while toks and len(toks[0]) <= 2 and toks[0] not in _NAME_JOINERS:
        toks.pop(0)

    s = _norm_spaces(" ".join(toks))
    if len(s.split()) < 2:
        return None
    return s

def _extract_nome_preferencial(text: str) -> Tuple[Optional[str], str]:
    u = _upper(text)

    # 1) Melhor caso: [ANDERSON SANTOS DE BARROS]
    m = re.search(r"\[([A-ZÇÃÕÁÉÍÓÚ\s]{8,80})\]", u)
    if m:
        cand = _clean_person_name(m.group(1))
        if cand:
            return cand, "brackets"

    # 2) Linha com label e valor
    m2 = re.search(r"\bNOME\s+E\s+SOBRENOME\b.*?([A-ZÇÃÕÁÉÍÓÚ ]{8,80})", u, flags=re.IGNORECASE)
    if m2:
        cand = _clean_person_name(m2.group(1))
        if cand:
            return cand, "label_line"

    # 3) MRZ estrito (mantido, mas não dependemos)
    mrz_block = _extract_mrz_block_strict(text)
    if mrz_block:
        cands = _mrz_name_candidates(mrz_block)
        best = _choose_best_mrz_name(cands)
        if best:
            return best, "mrz"
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f

    return None, "none"


<<<<<<< HEAD
def _extract_nascimento_cidade_uf(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    u = _upper(text)

    m = re.search(
        r"DATA,\s*LOCAL\s*E\s*UF\s*DE\s*NASCIMENTO.*?(\d{2}/\d{2}/\d{4})\s*,\s*([A-Z ]{3,60})\s*,\s*([A-Z]{2})",
        u,
        flags=re.DOTALL,
    )
    if m:
        nasc = m.group(1)
        city = _title_city(m.group(2))
        uf = m.group(3)
        return nasc, city, uf, "anchored"

    m = re.search(r"(\d{2}/\d{2}/\d{4})\s*,\s*([A-Z ]{3,60})\s*,\s*([A-Z]{2})", u)
    if m:
        nasc = m.group(1)
        city = _title_city(m.group(2))
        uf = m.group(3)
        return nasc, city, uf, "fallback_tuple"

    return None, None, None, "none"


def _extract_validade(text: str) -> Tuple[Optional[str], str]:
    dates = _find_dates_ddmmyyyy(text)
    parsed: List[Tuple[date, str]] = []
    for d in dates:
        dd = _parse_date_ddmmyyyy(d)
        if dd:
            parsed.append((dd, d))

    if not parsed:
        return None, "none"

    parsed.sort(key=lambda x: x[0])
    return parsed[-1][1], "max_date"


def _extract_filiacao(text: str) -> Tuple[List[str], str]:
    u = _upper(text)
    lines = [ln.strip() for ln in u.splitlines() if ln.strip()]

    for i, ln in enumerate(lines):
        if "FILIA" in ln:
            out: List[str] = []
            for j in range(i + 1, min(i + 12, len(lines))):
                cand = _cleanup_name(lines[j])
                if not cand:
                    continue
                if "ASSINATURA" in cand or "OBSERV" in cand or "DOCUMENTO" in cand:
                    continue
                if cand not in out:
                    out.append(cand)
                if len(out) >= 2:
                    break
            return out[:2], "lines_after_label"

    m = re.search(r"FILIA[ÇC]AO(.{0,650})", u, flags=re.DOTALL)
    if m:
        chunk = m.group(1)
        chunk_lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        out: List[str] = []
        for ln in chunk_lines[:12]:
            cand = _cleanup_name(ln)
=======
# ============================================================
# MRZ — estrito: só se houver '<' e '<<'
# ============================================================
def _extract_mrz_block_strict(text: str) -> Optional[str]:
    u = _upper(text)
    if "<" not in u:
        return None

    mrzish = re.sub(r"[^A-Z0-9<\n]", "", u)
    mrzish = re.sub(r"\n{3,}", "\n\n", mrzish).strip()

    lines = [ln for ln in mrzish.splitlines() if ("<<" in ln) and (ln.count("<") >= 8) and (len(ln) >= 25)]
    if not lines:
        return None

    lines = sorted(lines, key=len, reverse=True)[:2]
    block = "\n".join(lines).strip()
    return block if len(block) >= 25 else None

def _mrz_name_candidates(block: str) -> List[str]:
    if not block:
        return []
    cands: List[str] = []
    for m in re.finditer(r"([A-Z<]{3,})<<([A-Z<]{2,})", block):
        left = m.group(1).replace("<", " ").strip()
        right = m.group(2).replace("<", " ").strip()
        full = _norm_spaces(f"{right} {left}")
        full = _clean_person_name(full) or full
        if full and len(full.split()) >= 2:
            cands.append(full)
    out = []
    seen = set()
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

def _choose_best_mrz_name(cands: List[str]) -> Optional[str]:
    if not cands:
        return None
    best = None
    best_score = -1
    for c in cands:
        toks = c.split()
        score = len(toks) * 10 + len(c)
        if set(toks) & _BANNED_HEAD_TOKENS:
            score -= 100
        if score > best_score:
            best_score = score
            best = c
    return best

def _yymmdd_to_ddmmyyyy_birth(yymmdd: str) -> Optional[str]:
    m = re.match(r"^(\d{2})(\d{2})(\d{2})$", (yymmdd or "").strip())
    if not m:
        return None
    yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None

    now = date.today()
    current_yy = now.year % 100
    year = 1900 + yy if yy > current_yy else 2000 + yy
    if year > now.year:
        year = 1900 + yy
    return f"{dd:02d}/{mm:02d}/{year:04d}"

def _mrz_birth_from_block(block: str) -> Optional[str]:
    if not block:
        return None
    nums = re.findall(r"\b\d{6}\b", block)
    if not nums:
        return None

    best = None
    best_dt = None
    for n in nums:
        d = _yymmdd_to_ddmmyyyy_birth(n)
        if not d:
            continue
        dt = _dt_from_ddmmyyyy(d)
        if not dt or dt > date.today():
            continue
        if best_dt is None or dt < best_dt:
            best_dt = dt
            best = d
    return best


# ============================================================
# Nascimento por label (no seu OCR está claro)
# ============================================================
def _extract_nascimento_label(text: str) -> Optional[str]:
    u = _upper(text)
    m = re.search(r"\bDATA.*?\bNASCIMENTO\b.*?(\d{2}/\d{2}/\d{4})", u, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"\b(\d{2}/\d{2}/\d{4})\s*,\s*[A-ZÇÃÕÁÉÍÓÚ ]+\s*,\s*[A-Z]{2}\b", u)
    if m2:
        return m2.group(1).strip()
    return None


# ============================================================
# Filiação (limpa ruído pesado)
# ============================================================
def _extract_filiacao(text: str) -> List[str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln and ln.strip()]
    out: List[str] = []

    idx = None
    for i, ln in enumerate(lines):
        if "FILIA" in _upper(ln):
            idx = i
            break

    if idx is not None:
        for j in range(idx + 1, min(idx + 14, len(lines))):
            cand = _clean_person_name(lines[j])
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
            if cand and cand not in out:
                out.append(cand)
            if len(out) >= 2:
                break
<<<<<<< HEAD
        return out[:2], "regex_block"

    return [], "none"


# ============================================================
# Contrato (mantém exatamente as chaves do golden)
# ============================================================

=======

    if len(out) < 2:
        u = _upper(text)
        m = re.search(r"FILIA[ÇC]AO(.{0,550})", u, flags=re.IGNORECASE | re.DOTALL)
        if m:
            chunk = m.group(1)
            raws = re.findall(r"[A-ZÇÃÕÁÉÍÓÚ ]{10,}", chunk)
            for r in raws:
                cand = _clean_person_name(r)
                if cand and cand not in out:
                    out.append(cand)
                if len(out) >= 2:
                    break

    return out[:2]


# ============================================================
# Resultado / Parser
# ============================================================
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
@dataclass
class CNHResult:
    nome: Optional[str] = None
    cpf: Optional[str] = None
    data_nascimento: Optional[str] = None
    cidade_nascimento: Optional[str] = None
    uf_nascimento: Optional[str] = None
    validade: Optional[str] = None
    filiacao: List[str] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)


class CNHParser:
    def parse_text(self, text: str) -> CNHResult:
        t = text or ""

<<<<<<< HEAD
        nome, nome_src = _extract_nome(t)
        cpf = _extract_cpf(t)

        nasc, city, uf, nasc_src = _extract_nascimento_cidade_uf(t)
        validade, val_src = _extract_validade(t)

        filiacao, fil_src = _extract_filiacao(t)

        dbg = {
            "text_len": len(t),
            "sources": {
                "nome": nome_src,
                "cpf": "sliding_window_checksum_with_anchor",
                "nascimento": nasc_src,
                "validade": val_src,
                "filiacao": fil_src,
            },
=======
        cpf = _extract_cpf(t)
        emissao, validade = _extract_emissao_validade(t)

        cidade, uf = _best_city_uf_from_text(t)
        filiacao = _extract_filiacao(t)

        nome, nome_src = _extract_nome_preferencial(t)

        nasc_label = _extract_nascimento_label(t)
        mrz_block = _extract_mrz_block_strict(t)
        nasc_mrz = _mrz_birth_from_block(mrz_block) if mrz_block else None
        data_nascimento = nasc_label or nasc_mrz

        dbg = {
            "text_len": len(t),
            "found_dates": _find_dates(t),
            "emissao_detectada": emissao,
            "validade_detectada": validade,
            "cidade_uf_detectado": {"cidade": cidade, "uf": uf},
            "filiacao_detectada": filiacao,
            "nome_source": nome_src,
            "mrz_block_detectado": bool(mrz_block),
            "mrz_block_preview": (mrz_block[:120] + "...") if mrz_block and len(mrz_block) > 120 else mrz_block,
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
        }

        return CNHResult(
            nome=nome,
            cpf=cpf,
<<<<<<< HEAD
            data_nascimento=nasc,
            cidade_nascimento=city,
=======
            data_nascimento=data_nascimento,
            cidade_nascimento=(cidade.title() if cidade else None),
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
            uf_nascimento=uf,
            validade=validade,
            filiacao=filiacao,
            debug=dbg,
        )

    def to_dict(self, result: CNHResult) -> Dict[str, Any]:
        d = asdict(result)
        d["debug"] = d.get("debug") or {}
        d["filiacao"] = d.get("filiacao") or []
        return d


<<<<<<< HEAD
def analyze_cnh(
    *,
    raw_text: str,
    filename: Optional[str] = None,
    use_gemini: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
=======
# ============================================================
# Wrapper público (API estável para o app.py)
# ============================================================
def analyze_cnh(*, raw_text: str, filename: Optional[str] = None, use_gemini: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
    parser = CNHParser()
    res = parser.parse_text(raw_text or "")
    d = parser.to_dict(res)
    dbg = d.pop("debug", {}) or {}
    return d, dbg
