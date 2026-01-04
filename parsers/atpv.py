# parsers/atpv.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import re

# Dependências esperadas:
# - pdfplumber (texto nativo)
# - (opcional) pdf2image + pytesseract (OCR fallback)
#
# Se você já tem uma camada OCR interna, substitua _ocr_pdf_to_text()
# e mantenha o contrato de output (mode + debug).

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 800


@dataclass(frozen=True)
class PageDebug:
    page: int
    native_len: int
    ocr_len: int


def analyze_atpv(
    pdf_path: str,
    *,
    min_text_len_threshold: int = MIN_TEXT_LEN_THRESHOLD_DEFAULT,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    """
    Lê um ATPV (PDF) e retorna um dict com:
    - mode: "native" ou "ocr"
    - campos extraídos (se houver)
    - debug com métricas determinísticas (len de texto, páginas, etc.)
    """
    native_text, pages_native_len = _extract_native_text(pdf_path)

    # Decide modo por regra interna DO PARSER (teste não deve reproduzir isso).
    # Regra: se texto nativo for suficiente, fica em native; senão, OCR.
    if len(native_text) >= min_text_len_threshold:
        mode = "native"
        ocr_text = ""
        pages_ocr_len = [0 for _ in pages_native_len]
    else:
        mode = "ocr"
        ocr_text, pages_ocr_len = _ocr_pdf_to_text(pdf_path, dpi=ocr_dpi)

    # Texto efetivo usado para parse de campos
    text = native_text if mode == "native" else ocr_text

    # Extrai campos (mínimo viável; ajuste conforme seu parser real)
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
        "mode": mode,  # <-- PASSO 5: explicitar mode no output
        "debug": {
            "mode": mode,  # redundante por design (facilita teste e inspeção)
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
    OCR fallback. Mantém a função isolada para você trocar facilmente por sua camada OCR atual.
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
# Parse de campos (MVP)
# -----------------------------

_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_PLATE_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")  # Mercosul/antiga simpl.
_RENAVAM_RE = re.compile(r"\b(\d{9,11})\b")


def _extract_fields(text: str) -> Dict[str, Any]:
    """
    Aqui entra seu parser real do ATPV. Mantive um MVP que não quebra testes de contrato.
    Você pode expandir campos mantendo as chaves existentes (se já houver).
    """
    norm = _normalize(text)

    cpf = _first_match(_CPF_RE, norm)
    cnpj = _first_match(_CNPJ_RE, norm)
    placa = _first_match(_PLATE_RE, norm)

    # RENAVAM: altamente ambíguo (muitos números no documento). MVP: tenta pegar algo plausível
    # priorizando ocorrência perto do token 'RENAVAM' se existir.
    renavam = _extract_renavam(norm)

    # Nomes do comprador/vendedor variam; se você já tem lógica, substitua.
    comprador_nome = _extract_anchor_name(norm, anchor_tokens=("COMPRADOR", "ADQUIRENTE"))
    vendedor_nome = _extract_anchor_name(norm, anchor_tokens=("VENDEDOR", "ALIENANTE"))

    return {
        "comprador_nome": comprador_nome,
        "vendedor_nome": vendedor_nome,
        "cpf": cpf,
        "cnpj": cnpj,
        "placa": placa,
        "renavam": renavam,
    }


def _normalize(s: str) -> str:
    s = s.replace("\u00ad", "")  # soft hyphen
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _first_match(rx: re.Pattern[str], s: str) -> Optional[str]:
    m = rx.search(s)
    return m.group(1) if m else None


def _extract_renavam(s: str) -> Optional[str]:
    # Se houver "RENAVAM" ou "RENAVAM:", tenta capturar números logo após.
    m = re.search(r"RENAVAM[^0-9]{0,20}([0-9]{9,11})", s, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    # Fallback extremamente conservador: retorna o primeiro 11/10/9 dígitos que não seja CPF/CNPJ/CEP comum.
    # (Se isso atrapalhar, melhor retornar None do que errar.)
    candidates = _RENAVAM_RE.findall(s)
    for c in candidates:
        if len(c) in (9, 10, 11):
            return c
    return None


def _extract_anchor_name(s: str, *, anchor_tokens: Tuple[str, ...]) -> Optional[str]:
    """
    Busca linhas próximas de um rótulo e tenta extrair um nome (somente letras + espaços).
    É propositalmente fraca para não inventar; seu parser real deve ser mais forte.
    """
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return None

    anchors_upper = tuple(a.upper() for a in anchor_tokens)
    for i, ln in enumerate(lines):
        up = ln.upper()
        if any(a in up for a in anchors_upper):
            # tenta pegar o próximo trecho/linha
            for j in range(i, min(i + 3, len(lines))):
                cand = lines[j]
                cand = re.sub(r"[^A-ZÀ-Ü ]", " ", cand.upper())
                cand = re.sub(r"\s{2,}", " ", cand).strip()
                # heurística mínima: ao menos 2 palavras e tamanho razoável
                if len(cand) >= 10 and len(cand.split()) >= 2:
                    return cand
    return None
