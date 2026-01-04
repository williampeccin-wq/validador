# parsers/atpv.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 800


def analyze_atpv(
    pdf_path: str,
    *,
    min_text_len_threshold: int = MIN_TEXT_LEN_THRESHOLD_DEFAULT,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    native_text, pages_native_len = _extract_native_text(pdf_path)

    if len(native_text) >= min_text_len_threshold:
        mode = "native"
        ocr_text = ""
        pages_ocr_len = [0 for _ in pages_native_len]
    else:
        mode = "ocr"
        ocr_text, pages_ocr_len = _ocr_pdf_to_text(pdf_path, dpi=ocr_dpi)

    text = native_text if mode == "native" else ocr_text

    extracted = _extract_fields(text)

    debug_pages: List[Dict[str, Any]] = []
    max_pages = max(len(pages_native_len), len(pages_ocr_len))
    for i in range(max_pages):
        native_len_i = pages_native_len[i] if i < len(pages_native_len) else 0
        ocr_len_i = pages_ocr_len[i] if i < len(pages_ocr_len) else 0
        debug_pages.append(
            {
                "page": i + 1,
                "native_len": int(native_len_i),
                "ocr_len": int(ocr_len_i),
            }
        )

    out: Dict[str, Any] = {
        **extracted,
        "mode": mode,
        "debug": {
            "mode": mode,
            "native_text_len": int(len(native_text)),
            "ocr_text_len": int(len(ocr_text)),
            "min_text_len_threshold": int(min_text_len_threshold),
            "ocr_dpi": int(ocr_dpi),
            "pages": debug_pages,
        },
    }
    return out


# -----------------------------
# Extração de texto
# -----------------------------

def _extract_native_text(pdf_path: str) -> Tuple[str, List[int]]:
    try:
        import pdfplumber  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Dependência ausente: pdfplumber. Instale com `pip install pdfplumber`."
        ) from e

    texts: List[str] = []
    page_lens: List[int] = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            texts.append(t)
            page_lens.append(len(t))
    full = "\n".join(texts).strip()
    return full, page_lens


def _ocr_pdf_to_text(pdf_path: str, *, dpi: int) -> Tuple[str, List[int]]:
    """
    OCR fallback. Se você já tem OCR interno, substitua esta função.
    """
    try:
        from pdf2image import convert_from_path  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Dependência ausente: pdf2image. Instale com `pip install pdf2image` "
            "e garanta poppler no sistema."
        ) from e

    try:
        import pytesseract  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Dependência ausente: pytesseract. Instale com `pip install pytesseract` "
            "e garanta tesseract no sistema."
        ) from e

    images = convert_from_path(pdf_path, dpi=dpi)
    texts: List[str] = []
    page_lens: List[int] = []
    for img in images:
        t = pytesseract.image_to_string(img, lang="por") or ""
        t = t.strip()
        texts.append(t)
        page_lens.append(len(t))
    full = "\n".join(texts).strip()
    return full, page_lens


# -----------------------------
# Parse de campos
# -----------------------------

_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_PLATE_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")  # Mercosul/antiga
# VIN sem I/O/Q e 17 chars
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")

# BRL: captura "R$ 1.234,56" ou "1.234,56" ou "1234,56"
_MONEY_RE = re.compile(r"(R\$\s*)?(\d{1,3}(\.\d{3})*|\d+),\d{2}\b")

# âncoras mais comuns
_ANCHOR_BUYER = ("COMPRADOR", "ADQUIRENTE")
_ANCHOR_SELLER = ("VENDEDOR", "ALIENANTE")

# frases não-nome (aparecem nos seus goldens nativos atuais)
_BAD_NAME_SNIPPETS = (
    "IDENTIFICAÇÃO DO VENDEDOR",
    "IDENTIFICACAO DO VENDEDOR",
    "IDENTIFICAÇÃO DO COMPRADOR",
    "IDENTIFICACAO DO COMPRADOR",
    "O REGISTRO DESTE VEÍCULO",
    "O REGISTRO DESTE VEICULO",
)

_NAME_CHARS_RE = re.compile(r"[^A-ZÀ-Ü ]")


def _extract_fields(text: str) -> Dict[str, Any]:
    norm = _normalize(text)
    lines = _lines(norm)

    placa = _first_match(_PLATE_RE, norm)
    chassi = _first_match(_VIN_RE, norm)

    # RENAVAM: prioriza linha com "RENAVAM"
    renavam = _extract_renavam(lines)

    # Valor: prioriza linhas com "VALOR" + "VENDA"/"TRANSA" etc.
    valor_venda = _extract_valor_venda(lines)

    # Comprador: nome + doc por âncora
    comprador_nome, comprador_doc = _extract_person_block(lines, anchors=_ANCHOR_BUYER)

    # Vendedor: nome por âncora; doc opcional (não exigido pelo seu contrato aqui)
    vendedor_nome, vendedor_doc = _extract_person_block(lines, anchors=_ANCHOR_SELLER)

    # Compat: ainda exponho cpf/cnpj “soltos”, mas canonical é comprador_cpf_cnpj
    cpf = _only_digits(comprador_doc) if (comprador_doc and len(_only_digits(comprador_doc)) == 11) else None
    cnpj = _only_digits(comprador_doc) if (comprador_doc and len(_only_digits(comprador_doc)) == 14) else None

    return {
        # Obrigatórios (devem ser preenchidos com melhoria contínua do parser)
        "placa": placa,
        "renavam": renavam,
        "chassi": chassi,
        "valor_venda": valor_venda,
        "comprador_cpf_cnpj": _only_digits(comprador_doc) if comprador_doc else None,
        "comprador_nome": comprador_nome,
        "vendedor_nome": vendedor_nome,

        # Extras úteis
        "vendedor_cpf_cnpj": _only_digits(vendedor_doc) if vendedor_doc else None,

        # Retrocompat (se alguém usa isso)
        "cpf": cpf,
        "cnpj": cnpj,
    }


def _normalize(s: str) -> str:
    s = s.replace("\u00ad", "")  # soft hyphen
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _lines(s: str) -> List[str]:
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _first_match(rx: re.Pattern[str], s: str) -> Optional[str]:
    m = rx.search(s)
    return m.group(1) if m else None


def _extract_renavam(lines: List[str]) -> Optional[str]:
    for ln in lines:
        if "RENAVAM" in ln.upper():
            m = re.search(r"RENAVAM[^0-9]{0,25}([0-9]{9,11})", ln, flags=re.IGNORECASE)
            if m:
                return m.group(1)
            # fallback: qualquer 9-11 dígitos na mesma linha
            digs = re.findall(r"\b([0-9]{9,11})\b", ln)
            if digs:
                return digs[0]
    return None


def _extract_valor_venda(lines: List[str]) -> Optional[str]:
    # prioridade: linhas com "VALOR" e contexto de venda
    priority_keys = ("VALOR", "VENDA", "TRANSA", "NEGOC", "ALIENA")
    for ln in lines:
        up = ln.upper()
        if "VALOR" in up and any(k in up for k in priority_keys):
            m = _MONEY_RE.search(ln)
            if m:
                # retorna no formato "1234,56" (mantém vírgula) ou com R$
                return m.group(0).strip()
    # fallback: primeira ocorrência monetária do documento (conservador)
    for ln in lines:
        m = _MONEY_RE.search(ln)
        if m:
            return m.group(0).strip()
    return None


def _extract_person_block(lines: List[str], anchors: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
    """
    Heurística baseada em blocos: procura uma linha âncora, e busca nas próximas linhas:
      - nome humano (linha mais provável)
      - documento CPF/CNPJ (onde aparecer)
    """
    anchors_upper = tuple(a.upper() for a in anchors)
    n = len(lines)
    for i, ln in enumerate(lines):
        up = ln.upper()
        if any(a in up for a in anchors_upper):
            # janela curta após âncora
            window = lines[i : min(i + 8, n)]
            name = _find_name_in_window(window)
            doc = _find_doc_in_window(window)
            return name, doc

    # fallback: tenta achar doc em qualquer lugar, e nome em qualquer lugar (último recurso)
    doc = _find_doc_in_window(lines)
    name = _find_name_in_window(lines)
    return name, doc


def _find_doc_in_window(lines: List[str]) -> Optional[str]:
    for ln in lines:
        m = _CPF_RE.search(ln)
        if m:
            return m.group(1)
        m = _CNPJ_RE.search(ln)
        if m:
            return m.group(1)
        # fallback: números longos 11/14 próximos a palavras CPF/CNPJ
        up = ln.upper()
        if "CPF" in up or "CNPJ" in up:
            digs = re.findall(r"\b([0-9]{11}|[0-9]{14})\b", _only_digits(ln))
            if digs:
                return digs[0]
    return None


def _find_name_in_window(lines: List[str]) -> Optional[str]:
    """
    Busca um nome humano, evitando labels/frases institucionais.
    """
    for ln in lines:
        up = ln.upper()
        if any(bad in up for bad in _BAD_NAME_SNIPPETS):
            continue

        # remove dígitos e pontuação, mantém letras/acentos/espaços
        cand = up
        cand = _NAME_CHARS_RE.sub(" ", cand)
        cand = re.sub(r"\s{2,}", " ", cand).strip()

        # Heurística mínima de "nome humano"
        parts = [p for p in cand.split(" ") if p]
        if len(parts) >= 2 and len(cand) >= 10:
            # evita linhas com palavras típicas de cabeçalho
            if "IDENTIFICA" in cand or "REGISTRO" in cand or "VEÍCULO" in cand or "VEICULO" in cand:
                continue
            return cand

    return None
