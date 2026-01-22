# parsers/cnh.py

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _upper(s: Optional[str]) -> Optional[str]:
    s = _norm_spaces(s or "")
    return s.upper() if s else None


def _to_ddmmyyyy(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    m = re.search(r"(\d{2})[\/\.\-](\d{2})[\/\.\-](\d{4})", s)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"


def _parse_ddmmyyyy(d: str) -> Optional[date]:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", d or "")
    if not m:
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


_RE_ANY_DATE = re.compile(r"\b(\d{2}[\/\.\-]\d{2}[\/\.\-]\d{4})\b")

_RE_CPF_LABEL = re.compile(r"\bCPF\b[^\d]{0,25}(\d{3}\.?\d{3}\.?\d{3}\-?\d{2})\b", re.IGNORECASE)
_RE_CPF_ANY = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}\-?\d{2})\b")

_RE_NASC_LABEL = re.compile(
    r"\b(?:Data\s+de\s+Nascimento|Data\s+de\s+Nasc\.?)\b[^\d]{0,40}(\d{2}[\/\.\-]\d{2}[\/\.\-]\d{4})",
    re.IGNORECASE,
)

_RE_VALIDADE_LABEL = re.compile(
    r"\b(?:Validade|V[áa]lido\s+at[eé])\b[\s:–\-]*(" + _RE_ANY_DATE.pattern + r")",
    re.IGNORECASE,
)

# IMPORTANTE:
# SENATRAN deve ser detectado por marcadores realmente únicos.
# NÃO use "Nº Registro" como marcador, porque pode aparecer/colar no OCR do CNH Digital.
_RE_SENATRAN_MARKERS = re.compile(
    r"\b(SENATRAN|DETALHAMENTO|NOME\s+CIVIL|N[ÚU]MERO\s+VALIDA[CÇ][AÃ]O\s+CNH|N[ÚU]MERO\s+FORMUL[ÁA]RIO\s+RENACH)\b",
    re.IGNORECASE,
)

_RE_NATURALIDADE_INLINE = re.compile(
    r"\bNaturalidade\b\s*[:\-]?\s*([A-ZÀ-Ü\s]{2,80}?)\s+\b(?:UF\s*Naturalidade|UF)\b\s*[:\-]?\s*([A-Z]{2})\b",
    re.IGNORECASE,
)

_CATEGORIAS_VALIDAS = {"A", "B", "AB", "AC", "AD", "AE", "C", "D", "E"}

# Labels que colam no OCR e contaminam campos
_CUT_LABELS_RE = re.compile(
    r"(?:\bDOC\b|\bDOCUMENTO\b|\bIDENTIDADE\b|\bCPF\b|\bPERMISS(?:A|Ã)O\b|\bACC\b|\bCAT\b|\bHAB\b|"
    r"\bN[ºO]\b|\bN[ÚU]MERO\b|\bREGISTRO\b|\bVALIDADE\b|\bDATA\b|\bEMISS(?:A|Ã)O\b|\bOBSERVA|\bSENATRAN\b|\bDETALHAMENTO\b)",
    re.IGNORECASE,
)


def _extract_cpf(text: str) -> Optional[str]:
    t = text or ""
    m = _RE_CPF_LABEL.search(t)
    if m:
        return _only_digits(m.group(1))
    m2 = _RE_CPF_ANY.search(t)
    return _only_digits(m2.group(1)) if m2 else None


def _extract_nascimento(text: str) -> Optional[str]:
    t = (text or "").replace("\r", "\n")

    m = _RE_NASC_LABEL.search(t)
    if m:
        return _to_ddmmyyyy(m.group(1))

    # SENATRAN: label e data em linhas separadas
    m2 = re.search(
        r"\bData\s+de\s+Nascimento\b\s*[\n]+[\s]*(" + _RE_ANY_DATE.pattern + r")",
        t,
        flags=re.IGNORECASE,
    )
    return _to_ddmmyyyy(m2.group(1)) if m2 else None


def _extract_validade(text: str, nascimento: Optional[str]) -> Optional[str]:
    t = text or ""

    m = _RE_VALIDADE_LABEL.search(t)
    if m:
        return _to_ddmmyyyy(m.group(1))

    # fallback: maior data excluindo nascimento
    all_dates = [_to_ddmmyyyy(x) for x in _RE_ANY_DATE.findall(t)]
    all_dates = [d for d in all_dates if d]

    if not all_dates:
        return None

    nascimento_dt = _parse_ddmmyyyy(nascimento) if nascimento else None

    best: Optional[Tuple[date, str]] = None
    for s in all_dates:
        dt = _parse_ddmmyyyy(s)
        if not dt:
            continue
        if nascimento_dt and dt == nascimento_dt:
            continue
        if best is None or dt > best[0]:
            best = (dt, s)

    return best[1] if best else None


def _cleanup_name(s: str) -> Optional[str]:
    n = _upper(s) or ""
    if not n:
        return None

    # corta no primeiro label “grudado”
    n = _CUT_LABELS_RE.split(n, maxsplit=1)[0].strip(" -:;,.")
    n = _norm_spaces(n)

    # remove caracteres bizarros mantendo letras/acentos/espaço
    n = re.sub(r"[^A-ZÀ-Ü\s]", " ", n)
    n = _norm_spaces(n)

    # rejeita lixo típico
    if len(n) < 5:
        return None
    if re.search(r"\b(REPUBLICA|FEDERATIVA|BRASIL)\b", n):
        return None

    # precisa ter pelo menos 2 tokens “de nome”
    tokens = [t for t in n.split() if t]
    if len(tokens) < 2:
        return None

    # rejeita se tokens forem quase todos 1-char
    if sum(1 for t in tokens if len(t) <= 1) >= 2:
        return None

    return " ".join(tokens).upper()


def _extract_categoria(text: str) -> Optional[str]:
    t = text or ""

    m = re.search(r"\bCat\.?\s*Hab\.?\b\s*[:\-]?\s*([A-Z]{1,2})\b", t, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"\bCat\.?\s*Hab\.?\b\s*[\r\n]+[\s]*([A-Z]{1,2})\b", t, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"\bCategoria\b\s*[:\-]?\s*([A-Z]{1,2})\b", t, flags=re.IGNORECASE)
    if not m:
        return None

    cat = re.sub(r"[^A-Z]", "", (m.group(1) or "").upper())
    return cat if cat in _CATEGORIAS_VALIDAS else None


# ----------------------------
# SENATRAN
# ----------------------------

def _extract_nome_senatran(text: str) -> Optional[str]:
    t = (text or "").replace("\r", "\n")

    m = re.search(r"\bNome\s+Civil\b[\s:]*([\s\S]{0,120})", t, flags=re.IGNORECASE)
    if not m:
        return None

    chunk = m.group(1) or ""
    lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
    if not lines:
        return None

    return _cleanup_name(lines[0])


def _extract_local_uf_senatran(text: str) -> Tuple[Optional[str], Optional[str]]:
    t = (text or "").replace("\r", "\n")

    # "Local\nFLORIANOPOLIS\nUF\nSC" ou inline
    m_loc = re.search(r"\bLocal\b\s*[:\-]?\s*([A-ZÀ-Ü\s]{2,80})", t, flags=re.IGNORECASE)
    cidade = _upper(m_loc.group(1)) if m_loc else None

    # tenta UF por label com quebra
    m_uf = re.search(r"\bUF\b\s*[:\-]?\s*([A-Z]{2})\b", t, flags=re.IGNORECASE)
    if not m_uf:
        m_uf = re.search(r"\bUF\b\s*[\n]+[\s]*([A-Z]{2})\b", t, flags=re.IGNORECASE)
    uf = _upper(m_uf.group(1)) if m_uf else None

    # saneamento: se cidade ou UF ficaram “suspeitas” (ex.: UF=DE por causa de texto “DE ...”)
    if uf and uf not in {
        "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
    }:
        uf = None

    if cidade:
        cidade = re.split(r"\bUF\b|\bDATA\b|\bEMISS", cidade, maxsplit=1)[0].strip()
        cidade = _upper(cidade)

    return cidade, uf


def _extract_filiacao_senatran(text: str) -> List[str]:
    t = (text or "").replace("\r", "\n")
    out: List[str] = []

    def grab(label_pat: str) -> Optional[str]:
        # pega até ~3 linhas após o label
        m = re.search(rf"\b{label_pat}\b\s*[:\-]?\s*([\s\S]{{0,220}})", t, flags=re.IGNORECASE)
        if not m:
            return None
        chunk = m.group(1) or ""
        lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]

        # escolhe primeira linha que pareça nome (>=2 tokens alfabéticos)
        for ln in lines[:4]:
            cand = _CUT_LABELS_RE.split(ln, maxsplit=1)[0].strip(" -:;,.")
            cand = _cleanup_name(cand)
            if cand:
                return cand
        return None

    pai = grab(r"Filia[cç][aã]o\s*Pai")
    mae = grab(r"Filia[cç][aã]o\s*M[ãa]e")

    if pai:
        out.append(pai)
    if mae:
        out.append(mae)

    # dedup
    seen = set()
    cleaned: List[str] = []
    for x in out:
        x = _norm_spaces(x).upper()
        if not x or x in seen:
            continue
        seen.add(x)
        cleaned.append(x)

    return cleaned


# ----------------------------
# DIGITAL
# ----------------------------

def _extract_nome_digital(text: str) -> Optional[str]:
    t = (text or "").replace("\r", "\n")

    # 1) "NOME: ..."
    m = re.search(r"\bNOME\b\s*[:\-]\s*([A-ZÀ-Ü][A-ZÀ-Ü\s]{5,100})", t, flags=re.IGNORECASE)
    if m:
        name = _cleanup_name(m.group(1))
        if name:
            return name

    # 2) vizinhança do CPF: melhor linha antes do CPF
    mcpf = _RE_CPF_LABEL.search(t) or _RE_CPF_ANY.search(t)
    if mcpf:
        idx = mcpf.start()
        window = t[max(0, idx - 350) : idx]
        lines = [ln.strip() for ln in window.split("\n") if ln.strip()]
        for ln in reversed(lines[-10:]):
            cand = _cleanup_name(ln)
            if cand:
                return cand

    return None


def _extract_naturalidade_digital(text: str) -> Tuple[Optional[str], Optional[str]]:
    t = (text or "").replace("\r", "\n")

    m = _RE_NATURALIDADE_INLINE.search(t)
    if m:
        return _upper(m.group(1)), _upper(m.group(2))

    m2 = re.search(r"\bNaturalidade\b\s*[:\-]?\s*([A-ZÀ-Ü\s]{2,80}?)\s+([A-Z]{2})\b", t, flags=re.IGNORECASE)
    if m2:
        uf = _upper(m2.group(2))
        # valida UF pra não cair em "DE"
        if uf and uf not in {
            "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
        }:
            return None, None
        return _upper(m2.group(1)), uf

    return None, None


def _extract_filiacao_digital(text: str) -> List[str]:
    t = (text or "").replace("\r", "\n")
    out: List[str] = []

    m = re.search(
        r"\bFil\.?\s*Pai\b\s*:\s*([A-ZÀ-Ü\s]+?)\s+\bFil\.?\s*M[ãa]e\b\s*:\s*([A-ZÀ-Ü\s]+?)\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        pai = _cleanup_name(m.group(1))
        mae = _cleanup_name(m.group(2))
        if pai:
            out.append(pai)
        if mae:
            out.append(mae)

    # dedup
    seen = set()
    cleaned: List[str] = []
    for x in out:
        x = _norm_spaces(x).upper()
        if not x or x in seen:
            continue
        seen.add(x)
        cleaned.append(x)

    return cleaned


@dataclass
class CNHResult:
    nome: Optional[str] = None
    cpf: Optional[str] = None
    categoria: Optional[str] = None
    data_nascimento: Optional[str] = None
    validade: Optional[str] = None
    cidade_nascimento: Optional[str] = None
    uf_nascimento: Optional[str] = None
    filiacao: List[str] = None  # type: ignore[assignment]
    debug: Dict[str, Any] = None  # type: ignore[assignment]


class CNHParser:
    def parse_text(self, text: str) -> CNHResult:
        t = text or ""
        is_senatran = bool(_RE_SENATRAN_MARKERS.search(t))

        cpf = _extract_cpf(t)
        data_nascimento = _extract_nascimento(t)
        validade = _extract_validade(t, nascimento=data_nascimento)
        categoria = _extract_categoria(t)

        if is_senatran:
            nome = _extract_nome_senatran(t) or _extract_nome_digital(t)
            cidade, uf = _extract_local_uf_senatran(t)
            filiacao = _extract_filiacao_senatran(t)
            mode = "senatran"
        else:
            nome = _extract_nome_digital(t)
            cidade, uf = _extract_naturalidade_digital(t)
            filiacao = _extract_filiacao_digital(t)
            mode = "digital"

        dbg = {
            "mode": mode,
            "text_len": len(t),
            "found_dates": sorted(set(_to_ddmmyyyy(x) or x for x in _RE_ANY_DATE.findall(t))),
            "validade_detectada": validade,
            "cidade_uf_detectado": {"cidade": cidade, "uf": uf},
            "filiacao_detectada": filiacao,
            "categoria_detectada": categoria,
            "nome_detectado": nome,
        }

        return CNHResult(
            nome=nome,
            cpf=cpf,
            categoria=categoria,
            data_nascimento=data_nascimento,
            validade=validade,
            cidade_nascimento=cidade,
            uf_nascimento=uf,
            filiacao=filiacao or [],
            debug=dbg,
        )

    def to_dict(self, result: CNHResult) -> Dict[str, Any]:
        d = asdict(result)
        d["filiacao"] = d.get("filiacao") or []
        d["debug"] = d.get("debug") or {}
        return d


def analyze_cnh(*, raw_text: str, filename: Optional[str] = None, use_gemini: bool = True):
    """
    API pública do documento CNH.
    Retorna (fields, debug).
    """
    _ = filename
    _ = use_gemini
    parser = CNHParser()
    res = parser.parse_text(raw_text or "")
    fields = parser.to_dict(res)
    dbg = fields.pop("debug", {})
    return fields, dbg
