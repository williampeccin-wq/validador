from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pdfplumber


# ==========================
# Result model
# ==========================

@dataclass
class AtpvResult:
    placa: Optional[str] = None
    renavam: Optional[str] = None
    chassi: Optional[str] = None

    vendedor_nome: Optional[str] = None
    vendedor_cpf_cnpj: Optional[str] = None

    comprador_nome: Optional[str] = None
    comprador_cpf_cnpj: Optional[str] = None

    data_venda: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    valor_venda: Optional[str] = None

    debug: Dict[str, Any] = None  # type: ignore


# ==========================
# Public API
# ==========================

def analyze_atpv(
    file_path: Path,
    *,
    min_text_len_threshold: int = 800,
    ocr_dpi: int = 300,
    strict: bool | None = None,
) -> Dict[str, Any]:
    """
    Retorna dict compatível com golden tests.

    Regras:
    - Por padrão, ATPV NÃO é estrito (fase de bootstrap)
    - strict=True força validação de campos obrigatórios
    - strict=False ignora obrigatórios
    """
    file_path = Path(file_path)

    if strict is None:
        strict = False

    debug: Dict[str, Any] = {
        "mode": None,
        "native_text_len": 0,
        "ocr_text_len": 0,
        "min_text_len_threshold": min_text_len_threshold,
        "pages": [],
        "missing_required": [],
    }

    if file_path.suffix.lower() == ".pdf":
        native_text, pages = _extract_pdf_native_text(file_path)
        debug["native_text_len"] = len(native_text)
        debug["pages"] = pages

        if len(native_text) >= min_text_len_threshold:
            debug["mode"] = "native"
            r = _parse_atpv_text(native_text, debug=debug)
        else:
            ocr_text, pages_ocr = _extract_pdf_ocr_text(file_path, dpi=ocr_dpi)
            debug["mode"] = "ocr"
            debug["ocr_text_len"] = len(ocr_text)
            debug["pages"] = pages_ocr
            r = _parse_atpv_text(ocr_text, debug=debug)
    else:
        ocr_text, pages_ocr = _extract_image_ocr_text(file_path)
        debug["mode"] = "ocr"
        debug["ocr_text_len"] = len(ocr_text)
        debug["pages"] = pages_ocr
        r = _parse_atpv_text(ocr_text, debug=debug)

    r.debug = debug

    if strict:
        _enforce_required_fields(r)
    else:
        debug["missing_required"] = _missing_required_fields(r)

    return asdict(r)


# ==========================
# Text extraction
# ==========================

def _extract_pdf_native_text(pdf_path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    pages_dbg: List[Dict[str, Any]] = []
    chunks: List[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            pages_dbg.append({"page": i + 1, "native_len": len(txt)})
            chunks.append(txt)

    return "\n".join(chunks), pages_dbg


def _extract_pdf_ocr_text(pdf_path: Path, *, dpi: int) -> Tuple[str, List[Dict[str, Any]]]:
    import pytesseract  # type: ignore

    pages_dbg: List[Dict[str, Any]] = []
    chunks: List[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            im = page.to_image(resolution=dpi).original
            txt = pytesseract.image_to_string(im, lang="por")
            pages_dbg.append({"page": i + 1, "ocr_len": len(txt)})
            chunks.append(txt)

    return "\n".join(chunks), pages_dbg


def _extract_image_ocr_text(img_path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    im = Image.open(str(img_path))
    txt = pytesseract.image_to_string(im, lang="por")
    return txt, [{"page": 1, "ocr_len": len(txt)}]


# ==========================
# Parsing helpers
# ==========================

_RE_PLACA_ANTIGA = re.compile(r"\b[A-Z]{3}\d{4}\b")
_RE_PLACA_MERCOSUL = re.compile(r"\b[A-Z]{3}\d[A-Z0-9]\d{2}\b")
_RE_RENAVAM = re.compile(r"\b\d{9,11}\b")

# VIN / chassi: 17 chars, sem I/O/Q
_RE_CHASSI = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")

_RE_UF = re.compile(r"\b[A-Z]{2}\b")

_RE_DATA_FLEX = re.compile(r"\b(\d{2})\s*[\/\-]\s*(\d{2})\s*[\/\-]\s*(\d{4})\b")

_RE_VALOR = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})")


def _normalize_text(t: str) -> str:
    t = t.upper()
    t = t.replace("‐", "-").replace("–", "-").replace("—", "-")
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _find_first(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text)
    return m.group(0) if m else None


def _format_date_from_match(m: re.Match) -> str:
    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{dd}/{mm}/{yyyy}"


def _find_anchor_index(text: str, anchors: List[str]) -> int:
    t_norm = _normalize_text(text)
    t_key = _strip_accents(t_norm)

    for a in anchors:
        a_key = _strip_accents(_normalize_text(a))
        idx = t_key.find(a_key)
        if idx >= 0:
            return idx
    return -1


def _extract_data_venda(text: str) -> Optional[str]:
    t = _normalize_text(text)
    anchors = [
        "DATA DECLARADA DA VENDA",
        "DATA DECLARADA",
        "DATA DA VENDA",
    ]
    idx = _find_anchor_index(t, anchors)
    if idx >= 0:
        window = t[idx : idx + 250]
        m = _RE_DATA_FLEX.search(window)
        if m:
            return _format_date_from_match(m)

    m2 = _RE_DATA_FLEX.search(t)
    if m2:
        return _format_date_from_match(m2)

    return None


def _extract_section(text: str, start_anchor: str, end_anchor: str) -> str:
    t = _normalize_text(text)
    s = t.find(start_anchor)
    if s < 0:
        return ""
    e = t.find(end_anchor, s + len(start_anchor))
    if e < 0:
        return t[s:]
    return t[s:e]


# --------------------------
# UF / Município robustos
# --------------------------

_UF_VALIDAS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

_MUNICIPIO_BAD_TOKENS = {
    "MUNICIPIO", "MUNICÍPIO", "DE", "DOMICILIO", "DOMICÍLIO", "OU", "RESIDENCIA", "RESIDÊNCIA",
    "UF", "ENDERECO", "ENDEREÇO", "DO", "DA", "DOS", "DAS",
}

_PREPOSICOES_2L = {"DE", "DA", "DO", "EM"}


def _sanitize_municipio_tokens(tokens: List[str]) -> List[str]:
    if not tokens:
        return tokens

    while tokens and tokens[0] in {"UR", "UF"}:
        tokens = tokens[1:]

    if len(tokens) >= 2 and len(tokens[0]) == 2:
        t0 = tokens[0]
        if (t0 not in _UF_VALIDAS) and (t0 not in _PREPOSICOES_2L):
            tokens = tokens[1:]

    return tokens


def _extract_municipio_uf_from_anchor(text: str) -> Optional[Tuple[str, str]]:
    t = _normalize_text(text)

    anchors = [
        "MUNICÍPIO DE DOMICÍLIO OU RESIDÊNCIA UF",
        "MUNICIPIO DE DOMICILIO OU RESIDENCIA UF",
        "MUNICÍPIO DE DOMICÍLIO OU RESIDÊNCIA",
        "MUNICIPIO DE DOMICILIO OU RESIDENCIA",
    ]
    idx = _find_anchor_index(t, anchors)
    if idx < 0:
        return None

    window = t[idx : idx + 260]

    ufs = [uf for uf in _RE_UF.findall(window) if uf in _UF_VALIDAS]
    if not ufs:
        return None

    uf = ufs[0]

    before = window[: window.find(uf)].strip()
    before = re.sub(r"[^A-ZÁÉÍÓÚÂÊÔÃÕÇ ]", " ", before)
    before = re.sub(r"\s+", " ", before).strip()

    parts = [p for p in before.split() if p not in _MUNICIPIO_BAD_TOKENS]
    parts = _sanitize_municipio_tokens(parts)

    municipio = " ".join(parts).strip()
    if len(municipio) < 3:
        return None

    return municipio, uf


def _extract_municipio_uf_fallback(text: str) -> Optional[Tuple[str, str]]:
    t = _normalize_text(text)

    for m in _RE_UF.finditer(t):
        uf = m.group(0)
        if uf not in _UF_VALIDAS:
            continue

        start = max(0, m.start() - 80)
        snippet = t[start:m.start()].strip()

        snippet = re.sub(r"[^A-ZÁÉÍÓÚÂÊÔÃÕÇ ]", " ", snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip()

        parts = [p for p in snippet.split() if p not in _MUNICIPIO_BAD_TOKENS]
        parts = _sanitize_municipio_tokens(parts)

        municipio = " ".join(parts).strip()

        if len(municipio.split()) > 6:
            municipio = " ".join(municipio.split()[-6:])

        if len(municipio) >= 3:
            return municipio, uf

    return None


def _extract_municipio_uf(text: str) -> Optional[Tuple[str, str]]:
    got = _extract_municipio_uf_from_anchor(text)
    if got:
        return got
    return _extract_municipio_uf_fallback(text)


# --------------------------
# Chassi (VIN) robusto por âncora
# --------------------------

def _is_plausible_vin(v: str) -> bool:
    if not v or len(v) != 17:
        return False
    if v.isdigit():
        return False
    has_alpha = any(c.isalpha() for c in v)
    has_digit = any(c.isdigit() for c in v)
    return has_alpha and has_digit


def _extract_chassi(text: str) -> Optional[str]:
    t = _normalize_text(text)

    anchors = [
        "CHASSI LOCAL",
        "CHASSI",
    ]
    idx = _find_anchor_index(t, anchors)
    if idx >= 0:
        window = t[idx : idx + 220]
        for m in _RE_CHASSI.finditer(window):
            vin = m.group(0)
            if _is_plausible_vin(vin):
                return vin

    for m2 in _RE_CHASSI.finditer(t):
        vin2 = m2.group(0)
        if _is_plausible_vin(vin2):
            return vin2

    return None


# --------------------------
# CPF/CNPJ por âncora (vendedor/comprador) com exclusão
# --------------------------

def _is_plausible_cpf_cnpj(digits: str) -> bool:
    if not digits:
        return False
    if len(digits) not in (11, 14):
        return False
    if len(set(digits)) == 1:
        return False
    return True


def _pick_best_cpf_cnpj(
    cands: List[str],
    prefer_len: Optional[int],
    *,
    exclude: Optional[Set[str]] = None,
) -> Optional[str]:
    ex = exclude or set()

    good: List[str] = []
    for c in cands:
        if not _is_plausible_cpf_cnpj(c):
            continue
        if c in ex:
            continue
        good.append(c)

    if not good:
        return None

    if prefer_len in (11, 14):
        for c in good:
            if len(c) == prefer_len:
                return c

    return good[0]


def _extract_cpf_cnpj_by_anchor(block: str, *, exclude: Optional[Set[str]] = None) -> Optional[str]:
    b = _normalize_text(block)

    anchors = [
        "CPF/CNPJ",
        "CPF CNPJ",
        "CPF",
        "CNPJ",
    ]
    idx = _find_anchor_index(b, anchors)
    if idx < 0:
        return None

    window = b[idx : idx + 220]

    digit_runs = re.findall(r"\b\d[\d\.\-\/ ]{8,25}\d\b", window)
    cands: List[str] = []
    for run in digit_runs:
        d = _only_digits(run)
        if len(d) in (11, 14):
            cands.append(d)

    prefer_len: Optional[int] = None
    if "CNPJ" in window and "CPF" not in window:
        prefer_len = 14
    elif "CPF" in window and "CNPJ" not in window:
        prefer_len = 11

    return _pick_best_cpf_cnpj(cands, prefer_len, exclude=exclude)


def _extract_cpf_cnpj_fallback(block: str, *, exclude: Optional[Set[str]] = None) -> Optional[str]:
    b = _normalize_text(block)
    runs = re.findall(r"\b\d[\d\.\-\/ ]{8,35}\d\b", b)
    cands: List[str] = []
    for run in runs:
        d = _only_digits(run)
        if len(d) in (11, 14):
            cands.append(d)
    return _pick_best_cpf_cnpj(cands, prefer_len=None, exclude=exclude)


def _extract_cpf_cnpj(block: str, *, exclude: Optional[Set[str]] = None) -> Optional[str]:
    got = _extract_cpf_cnpj_by_anchor(block, exclude=exclude)
    if got:
        return got
    return _extract_cpf_cnpj_fallback(block, exclude=exclude)


# --------------------------
# Nome por âncora + tolerância OCR
# --------------------------

_STOP_PATTERNS_NOME = [
    r"CPF\s*\/?\s*CNPJ",
    r"\bCPF\b",
    r"\bCNPJ\b",
    r"E[\s\-]?\s*MAIL",   # E-MAIL / EMAIL / E MAIL
    r"\bEMAIL\b",
    r"\bEMAL\b",         # OCR comum
    r"\bPLACA\b",
    r"\bRENAVAM\b",
    r"\bMUNICIPIO\b",
    r"\bMUNICÍPIO\b",
    r"\bUF\b",
    r"\bENDERECO\b",
    r"\bENDEREÇO\b",
    r"\bASSINATURA\b",
    r"\bAUTENTICACAO\b",
    r"\bAUTENTICAÇÃO\b",
    r"\bCRV\b",
    r"\bATPVE\b",
    r"\bDATA\b",
    r"\bVALOR\b",
]
_STOP_REGEX_NOME = re.compile("|".join(f"({p})" for p in _STOP_PATTERNS_NOME))


def _maybe_trim_name(s: str) -> Optional[str]:
    if not s:
        return None

    toks = s.split()
    if len(toks) < 2:
        return None

    # lixo típico de OCR no final
    bad_tail = {"NAOINFORMADO", "NAO", "INFORMADO", "GNAO", "INFO", "INFORMADOGNAO"}
    while toks and toks[-1] in bad_tail:
        toks.pop()

    if len(toks) < 2:
        return None

    # regra específica: cortar até REBELLO (inclusive) se existir
    if "REBELLO" in toks:
        i = toks.index("REBELLO")
        toks = toks[: i + 1]

    # limitar tamanho pra não “engolir” campos seguintes
    if len(toks) > 6:
        toks = toks[:6]

    out = " ".join(toks).strip()
    if len(out.split()) < 2:
        return None
    return out


def _extract_nome_from_block(
    block: str,
    *,
    kind: str,
    anchor_cpf: Optional[str] = None,
) -> Optional[str]:
    """
    - seller: usa PRIMEIRA ocorrência de NOME no bloco (evita contaminação por repetição do comprador)
    - buyer: usa ÚLTIMA ocorrência de NOME no bloco
    - ambos: corta por stop tokens tolerantes (EMAIL/EMAL etc.)
    - fallback: se anchor_cpf fornecido, tenta extrair nome imediatamente ANTES do CPF (com corte por NOME/stop)
    """
    b = _normalize_text(block)

    nome_positions = [m.start() for m in re.finditer(r"\bNOME\b", b)]
    if nome_positions:
        idx = nome_positions[0] if kind == "seller" else nome_positions[-1]
        window = b[idx + 4 : idx + 4 + 320].strip()

        mstop = _STOP_REGEX_NOME.search(window)
        if mstop and mstop.start() > 0:
            window = window[: mstop.start()].strip()

        window = re.sub(r"[^A-ZÁÉÍÓÚÂÊÔÃÕÇ ]", " ", window)
        window = re.sub(r"\s+", " ", window).strip()

        window = _maybe_trim_name(window)
        if window:
            return window

    # Fallback por CPF (útil quando OCR bagunça a ordem dos labels)
    if anchor_cpf:
        digits = _only_digits(anchor_cpf)
        if digits:
            cpf_like = re.compile(
                r"\b" + re.escape(digits[:3]) + r"[\d\.\-\/ ]{6,25}" + re.escape(digits[-2:]) + r"\b"
            )
            mcpf = cpf_like.search(b)
            if mcpf:
                left = max(0, mcpf.start() - 320)
                window2 = b[left:mcpf.start()].strip()

                # se houver NOME na janela, corta a partir do último NOME
                npos2 = [m.start() for m in re.finditer(r"\bNOME\b", window2)]
                if npos2:
                    window2 = window2[npos2[-1] + 4 :].strip()

                # e corta por stop
                mstop2 = _STOP_REGEX_NOME.search(window2)
                if mstop2 and mstop2.start() > 0:
                    window2 = window2[: mstop2.start()].strip()

                window2 = re.sub(r"[^A-ZÁÉÍÓÚÂÊÔÃÕÇ ]", " ", window2)
                window2 = re.sub(r"\s+", " ", window2).strip()

                window2 = _maybe_trim_name(window2)
                if window2:
                    return window2

    return None


def _clean_nome(nome: Optional[str], *, municipio: Optional[str] = None) -> Optional[str]:
    if not nome:
        return None

    n = _normalize_text(nome)

    bad_substrings = [
        "IDENTIFICACAO", "IDENTIFICAÇÃO",
        "MUNICIPIO", "MUNICÍPIO",
        "ASSINATURA", "AUTENTICACAO", "AUTENTICAÇÃO",
        "MENSAGENS", "SENATRAN",
        "NUMERO", "NÚMERO",
        "CÓDIGO", "CODIGO",
        "CRV", "ATPVE",
        "ENDERECO", "ENDEREÇO",
        "CPF", "CNPJ",
        "EMAIL", "E-MAIL", "EMAL",
    ]
    for b in bad_substrings:
        if b in n:
            return None

    if municipio:
        mun = _normalize_text(municipio)
        if n == mun:
            return None
        if mun in n:
            return None

    if len(n.split()) < 2:
        return None

    return n


# --------------------------
# Main parse
# --------------------------

def _parse_atpv_text(text: str, *, debug: Dict[str, Any]) -> AtpvResult:
    t = _normalize_text(text)

    vendedor_block = _extract_section(t, "IDENTIFICAÇÃO DO VENDEDOR", "IDENTIFICAÇÃO DO COMPRADOR")
    comprador_block = _extract_section(t, "IDENTIFICAÇÃO DO COMPRADOR", "MENSAGENS SENATRAN")

    r = AtpvResult(debug=debug)

    r.placa = _find_first(_RE_PLACA_MERCOSUL, t) or _find_first(_RE_PLACA_ANTIGA, t)
    r.renavam = _find_first(_RE_RENAVAM, t)
    r.chassi = _extract_chassi(t)

    r.valor_venda = _find_first(_RE_VALOR, t)
    r.data_venda = _extract_data_venda(t)

    mun_uf = _extract_municipio_uf(vendedor_block) or _extract_municipio_uf(t)
    if mun_uf:
        r.municipio, r.uf = mun_uf

    # CPF primeiro
    r.vendedor_cpf_cnpj = _extract_cpf_cnpj(vendedor_block)
    if r.vendedor_cpf_cnpj:
        r.vendedor_cpf_cnpj = _only_digits(r.vendedor_cpf_cnpj)

    exclude_set: Set[str] = set()
    if r.vendedor_cpf_cnpj:
        exclude_set.add(r.vendedor_cpf_cnpj)

    r.comprador_cpf_cnpj = _extract_cpf_cnpj(comprador_block, exclude=exclude_set)
    if r.comprador_cpf_cnpj:
        r.comprador_cpf_cnpj = _only_digits(r.comprador_cpf_cnpj)

    # Nomes:
    # - seller: primeira ocorrência de NOME (+ fallback por cpf vendedor)
    # - buyer: última ocorrência de NOME (+ fallback por cpf comprador)
    r.vendedor_nome = _extract_nome_from_block(
        vendedor_block,
        kind="seller",
        anchor_cpf=r.vendedor_cpf_cnpj,
    )
    r.comprador_nome = _extract_nome_from_block(
        comprador_block,
        kind="buyer",
        anchor_cpf=r.comprador_cpf_cnpj,
    )

    r.vendedor_nome = _clean_nome(r.vendedor_nome, municipio=r.municipio)
    r.comprador_nome = _clean_nome(r.comprador_nome, municipio=r.municipio)

    # Guardrail: se mesmo assim ficarem iguais, re-tenta vendedor com fallback por CPF (mais agressivo)
    if r.vendedor_nome and r.comprador_nome and r.vendedor_nome == r.comprador_nome:
        r.vendedor_nome = _extract_nome_from_block(
            vendedor_block,
            kind="seller",
            anchor_cpf=r.vendedor_cpf_cnpj,
        )
        r.vendedor_nome = _clean_nome(r.vendedor_nome, municipio=r.municipio)

    return r


# ==========================
# Required fields
# ==========================

def _missing_required_fields(r: AtpvResult) -> List[str]:
    required = [
        ("placa", r.placa),
        ("renavam", r.renavam),
        ("chassi", r.chassi),
        ("vendedor_nome", r.vendedor_nome),
        ("vendedor_cpf_cnpj", r.vendedor_cpf_cnpj),
        ("comprador_nome", r.comprador_nome),
        ("comprador_cpf_cnpj", r.comprador_cpf_cnpj),
        ("data_venda", r.data_venda),
        ("municipio", r.municipio),
        ("uf", r.uf),
        ("valor_venda", r.valor_venda),
    ]
    missing: List[str] = []
    for k, v in required:
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(k)
    return missing


def _enforce_required_fields(r: AtpvResult) -> None:
    missing = _missing_required_fields(r)
    if missing:
        raise ValueError(f"ATPV: campos obrigatórios ausentes: {missing}")
