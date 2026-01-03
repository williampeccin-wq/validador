# parsers/atpv.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MIN_NATIVE_TEXT_LEN = 800


# =============================================================================
# Data model
# =============================================================================

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

    debug: Optional[Dict[str, Any]] = None


# =============================================================================
# API pública
# =============================================================================

def analyze_atpv(path: str | Path, *, strict: bool = True) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    mode, native_text, ocr_text, pages, decision = _extract_text_hybrid(p)
    base_text = native_text if mode == "native" else ocr_text
    norm = _normalize(base_text)

    debug = {
        "mode": mode,
        "native_text_len": len(native_text),
        "ocr_text_len": len(ocr_text),
        "pages": pages,
        "min_text_len_threshold": MIN_NATIVE_TEXT_LEN,
        "mode_decision": decision,  # explica por que escolheu native/ocr
    }

    r = AtpvResult(debug=debug)

    if mode == "native":
        _parse_native(norm, r)
    else:
        _parse_ocr(norm, r)

    missing = _enforce_required_fields(r, strict=strict)
    if missing:
        r.debug["missing_required"] = missing

    return asdict(r)


# =============================================================================
# Extração híbrida (PDF nativo vs OCR) com checagem de qualidade
# =============================================================================

def _extract_text_hybrid(path: Path) -> Tuple[str, str, str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Retorna:
      (mode, native_text, ocr_text, pages_debug, decision_debug)
    """
    decision: Dict[str, Any] = {}
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        native_text, native_pages = _extract_pdf_native_text(path)
        decision["native_len"] = len(native_text)
        decision["native_quality_ok"] = _native_text_quality_ok(native_text)

        # Critério híbrido:
        # - se texto nativo curto -> OCR
        # - se texto nativo longo mas "lixo" -> OCR
        # - só usa native se for longo E de qualidade aceitável
        if len(native_text) >= MIN_NATIVE_TEXT_LEN and decision["native_quality_ok"]:
            decision["chosen"] = "native"
            decision["reason"] = "native_len>=threshold and native_quality_ok"
            return "native", native_text, "", native_pages, decision

        # fallback OCR
        ocr_text, ocr_pages = _extract_pdf_ocr_text(path)
        decision["chosen"] = "ocr"
        if len(native_text) < MIN_NATIVE_TEXT_LEN:
            decision["reason"] = "native_len<threshold"
        else:
            decision["reason"] = "native_quality_bad_forced_ocr"
        return "ocr", native_text, ocr_text, ocr_pages, decision

    # Imagem: sempre OCR
    ocr_text, ocr_pages = _extract_image_ocr_text(path)
    decision["chosen"] = "ocr"
    decision["reason"] = "image_input"
    return "ocr", "", ocr_text, ocr_pages, decision


def _native_text_quality_ok(text: str) -> bool:
    """
    Heurística para detectar 'texto nativo lixo':
    - muito token de 1 caractere
    - poucas palavras de tamanho >= 3
    - aparência de texto 'desmontado' (muitas letras isoladas)
    """
    if not text:
        return False

    # Normaliza para analisar
    t = _strip_accents(text).upper()
    # Tokens por whitespace
    toks = [x for x in re.split(r"\s+", t) if x]
    if len(toks) < 30:
        # pouco texto: não confiável
        return False

    one_char = sum(1 for x in toks if len(x) == 1)
    longish = sum(1 for x in toks if len(x) >= 3)

    one_char_ratio = one_char / max(1, len(toks))
    longish_ratio = longish / max(1, len(toks))

    # Outra heurística: quantos tokens parecem "só letras isoladas" (A, B, C, ...)
    alpha_one_char = sum(1 for x in toks if len(x) == 1 and x.isalpha())
    alpha_one_char_ratio = alpha_one_char / max(1, len(toks))

    # Limiares calibrados para o seu caso (texto cheio de caracteres soltos)
    # - se > 35% tokens de 1 char, quase certamente lixo
    # - se < 18% tokens >= 3 chars, quase certamente lixo
    # - se muitos 1-char alfabéticos, sinal forte de desmontado
    if one_char_ratio > 0.35:
        return False
    if longish_ratio < 0.18:
        return False
    if alpha_one_char_ratio > 0.20:
        return False

    return True


def _extract_pdf_native_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    try:
        import pdfplumber  # type: ignore
    except ImportError as e:
        raise RuntimeError("pdfplumber não instalado") from e

    texts: List[str] = []
    pages: List[Dict[str, Any]] = []

    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            texts.append(txt)
            pages.append({"page": i + 1, "native_len": len(txt)})

    return "\n".join(texts), pages


def _extract_pdf_ocr_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    try:
        from pdf2image import convert_from_path  # type: ignore
        import pytesseract  # type: ignore
    except ImportError as e:
        raise RuntimeError("pdf2image / pytesseract não instalado") from e

    texts: List[str] = []
    pages: List[Dict[str, Any]] = []

    images = convert_from_path(str(path), dpi=300)
    for i, img in enumerate(images):
        txt = pytesseract.image_to_string(img, lang="por") or ""
        texts.append(txt)
        pages.append({"page": i + 1, "ocr_len": len(txt)})

    return "\n".join(texts), pages


def _extract_image_ocr_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except ImportError as e:
        raise RuntimeError("Pillow / pytesseract não instalado") from e

    img = Image.open(str(path))
    txt = pytesseract.image_to_string(img, lang="por") or ""
    return txt, [{"page": 1, "ocr_len": len(txt)}]


# =============================================================================
# Native PDF parsing (mantido; só será usado quando native_quality_ok=True)
# =============================================================================

def _parse_native(text: str, r: AtpvResult) -> None:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    upper = [l.upper() for l in lines]

    def after(label: str) -> Optional[str]:
        for i, l in enumerate(upper):
            if label in l and i + 1 < len(lines):
                return lines[i + 1]
        return None

    r.placa = after("PLACA")
    r.renavam = after("RENAVAM")
    r.chassi = _find_vin(lines)
    r.data_venda = after("DATA DECLARADA DA VENDA")
    r.valor_venda = _regex(text, r"VALOR\s+DECLARADO\s+NA\s+VENDA:\s*R\$\s*([0-9\.\s]+,[0-9]{2})")

    _parse_partes_native(lines, r)


def _parse_partes_native(lines: List[str], r: AtpvResult) -> None:
    def block(title: str) -> List[str]:
        for i, l in enumerate(lines):
            if title in l.upper():
                return lines[i:i + 18]
        return []

    comp = block("IDENTIFICAÇÃO DO COMPRADOR")
    vend = block("IDENTIFICAÇÃO DO VENDEDOR")

    r.comprador_nome = _after_in_block(comp, "NOME")
    r.comprador_cpf_cnpj = _first_doc(comp)

    r.vendedor_nome = _after_in_block(vend, "NOME")
    r.vendedor_cpf_cnpj = _first_doc(vend)

    mun, uf = _municipio_uf_from_block(comp)
    if not (mun or uf):
        mun, uf = _municipio_uf_from_block(vend)
    r.municipio, r.uf = mun, uf


# =============================================================================
# OCR parsing (é aqui que o PDF do exemplo vai cair após a correção)
# =============================================================================

_UF_ALL = r"(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)"


def _parse_ocr(text: str, r: AtpvResult) -> None:
    u = _strip_accents(text).upper()

    # Placa
    r.placa = _regex(u, r"\b([A-Z]{3}\d[A-Z0-9]\d{2})\b") or _regex(u, r"\b([A-Z]{3}\d{4})\b")

    # Renavam (normalmente vem como 11 dígitos)
    ren = _regex(u, r"\bRENAVAM\b\s*[:\-]?\s*([0-9\.\-\s]{9,15})")
    if ren:
        ren_d = _only_digits(ren)
        if 9 <= len(ren_d) <= 11:
            r.renavam = ren_d
    if not r.renavam:
        cand = re.search(r"\b(\d{11})\b", u)
        r.renavam = cand.group(1) if cand else None

    # Chassi (VIN)
    r.chassi = _regex(u, r"\b([A-HJ-NPR-Z0-9]{17})\b")

    # Data venda
    r.data_venda = _regex(u, r"\b([0-3]?\d/[01]?\d/\d{4})\b")

    # Valor venda (preferir o "Valor declarado na venda")
    r.valor_venda = (
        _regex(u, r"VALOR\s+DECLARADO\s+NA\s+VENDA\s*:\s*R\$\s*([0-9\.\s]+,[0-9]{2})")
        or _regex(u, r"R\$\s*([0-9\.\s]+,[0-9]{2})")
    )
    if r.valor_venda:
        r.valor_venda = r.valor_venda.replace(" ", "")

    # Documentos: pega os dois primeiros (vendedor, comprador) — melhora depois quando tivermos OCR do PDF
    docs = re.findall(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", u)
    if len(docs) >= 2:
        r.vendedor_cpf_cnpj = _only_digits(docs[0])
        r.comprador_cpf_cnpj = _only_digits(docs[1])

    # Nomes (mínimo viável; refinamos com OCR do PDF)
    r.vendedor_nome = _extract_nome_after_section(u, "IDENTIFICACAO DO VENDEDOR")
    r.comprador_nome = _extract_nome_after_section(u, "IDENTIFICACAO DO COMPRADOR")

    # Município/UF
    r.municipio, r.uf = _extract_municipio_uf(u)


def _extract_nome_after_section(u: str, section: str) -> Optional[str]:
    """
    No OCR, costuma existir:
      IDENTIFICAÇÃO DO VENDEDOR
      NOME
      <nome...>
    então buscamos o valor imediatamente após 'NOME' dentro de uma janela.
    """
    idx = u.find(section)
    if idx < 0:
        return None
    window = u[idx: idx + 600]

    # padrão: NOME \n <NOME>
    m = re.search(r"\bNOME\b\s*\n?\s*([A-Z][A-Z ]{5,})", window)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        # corta se vier juntando outro rótulo
        name = re.split(r"\b(CPF|CNPJ|E-MAIL|EMAIL|MUNICIPIO|ENDERECO|ASSINATURA)\b", name)[0].strip()
        return name or None
    return None


def _extract_municipio_uf(text_upper: str) -> Tuple[Optional[str], Optional[str]]:
    """
    OCR típico:
      MUNICIPIO DE DOMICILIO OU RESIDENCIA UF
      PORTO BELO - SC
    ou
      DETRAN - sc
    """
    t = text_upper

    # caso "CIDADE - UF" ou "CIDADE/UF"
    m = re.search(r"\b([A-Z]{3,}(?:\s+[A-Z]{2,})*)\s*[-/]\s*%s\b" % _UF_ALL, t)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # UF: XX
    m = re.search(r"\bUF\b\s*[:\-]?\s*(%s)\b" % _UF_ALL, t)
    uf = m.group(1).strip() if m else None

    # tenta achar qualquer ocorrência de UF no doc (ex.: "DETRAN - SC")
    if not uf:
        m = re.search(r"[-/]\s*(%s)\b" % _UF_ALL, t)
        uf = m.group(1).strip() if m else None

    # Município: tenta extrair uma linha pós "MUNICIPIO ..."
    m = re.search(r"\bMUNICIPIO\b.*?\bRESIDENCIA\b.*?\bUF\b", t)
    if m:
        # janela após o rótulo (OCR costuma colocar o valor na linha seguinte)
        tail = t[m.end(): m.end() + 300]
        m2 = re.search(r"\b([A-Z]{3,}(?:\s+[A-Z]{2,})*)\s*[-/]\s*(%s)\b" % _UF_ALL, tail)
        if m2:
            return m2.group(1).strip(), m2.group(2).strip()

        # se não achou cidade, pelo menos mantém UF (se tiver)
        return None, uf

    return None, uf


# =============================================================================
# Helpers gerais
# =============================================================================

def _regex(text: str, pat: str, flags=0) -> Optional[str]:
    m = re.search(pat, text, flags)
    return m.group(1).strip() if m else None


def _find_vin(lines: List[str]) -> Optional[str]:
    for l in lines:
        m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", l)
        if m:
            return m.group(1)
    return None


def _after_in_block(block: List[str], label: str) -> Optional[str]:
    for i, l in enumerate(block):
        if label in l.upper() and i + 1 < len(block):
            return block[i + 1]
    return None


def _first_doc(block: List[str]) -> Optional[str]:
    for l in block:
        d = _only_digits(l)
        if len(d) in (11, 14):
            return d
    return None


def _municipio_uf_from_block(block: List[str]) -> Tuple[Optional[str], Optional[str]]:
    for i, l in enumerate(block):
        if "MUNIC" in l.upper() and i + 1 < len(block):
            parts = block[i + 1].split()
            if len(parts) >= 2:
                maybe_uf = parts[-1].upper()
                if re.fullmatch(_UF_ALL, maybe_uf):
                    return " ".join(parts[:-1]), maybe_uf
    return None, None


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def _normalize(t: str) -> str:
    # mantém quebras de linha para OCR/native parsing por blocos
    t = t.replace("\u00a0", " ")
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def _enforce_required_fields(r: AtpvResult, *, strict: bool) -> List[str]:
    fields = [
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

    missing = [k for k, v in fields if v is None or (isinstance(v, str) and not v.strip())]

    if missing and strict:
        raise ValueError(f"ATPV: campos obrigatórios ausentes: {missing}")

    return missing
