from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Literal

MIN_TEXT_LEN_THRESHOLD_DEFAULT = 700

_PLACA_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")
_RENAVAM_RE = re.compile(r"\b(\d{11})\b")
_ANO_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

_NOISE_RE = re.compile(
    r"(DENATRAN|SENATRAN|QR\s*CODE|DPVAT|GOVERNO|SECRETARIA)",
    re.IGNORECASE,
)


def analyze_detran_sc(
    path: str,
    *,
    consulta: Literal["aberta", "despachante"],
    min_text_len_threshold: int = MIN_TEXT_LEN_THRESHOLD_DEFAULT,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    """
    Parser Detran SC.

    - PDF ou imagem
    - Extração fiel
    - SEM validações
    - SEM inferência de formato
    """

    native_text, pages_native_len = _extract_native_text(path)

    if len(native_text) >= min_text_len_threshold:
        mode = "native"
        ocr_text = ""
        pages_ocr_len = [0 for _ in pages_native_len]
    else:
        mode = "ocr"
        ocr_text, pages_ocr_len = _ocr_to_text(path, dpi=ocr_dpi)

    text = native_text if mode == "native" else ocr_text
    lines = _clean_lines(text)

    proprietario_nome = _extract_owner_name(lines)
    proprietario_nome_ofuscado = consulta == "aberta"

    extracted = _extract_fields(
        lines,
        proprietario_nome,
        proprietario_nome_ofuscado,
    )

    pages = []
    for i in range(max(len(pages_native_len), len(pages_ocr_len))):
        pages.append(
            {
                "page": i + 1,
                "native_len": pages_native_len[i] if i < len(pages_native_len) else 0,
                "ocr_len": pages_ocr_len[i] if i < len(pages_ocr_len) else 0,
            }
        )

    return {
        **extracted,
        "mode": mode,
        "debug": {
            "consulta": consulta,
            "native_text_len": len(native_text),
            "ocr_text_len": len(ocr_text),
            "min_text_len_threshold": min_text_len_threshold,
            "ocr_dpi": ocr_dpi,
            "pages": pages,
            "warnings": [],
        },
    }


# =========================
# Helpers
# =========================
def _extract_native_text(path: str) -> Tuple[str, List[int]]:
    texts, lens = [], []
    if path.lower().endswith(".pdf"):
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                t = p.extract_text() or ""
                texts.append(t)
                lens.append(len(t))
    else:
        lens = [0]
    return "\n".join(texts), lens


def _ocr_to_text(path: str, *, dpi: int) -> Tuple[str, List[int]]:
    from pdf2image import convert_from_path
    from PIL import Image
    import pytesseract

    texts, lens = [], []

    if path.lower().endswith(".pdf"):
        images = convert_from_path(path, dpi=dpi)
    else:
        images = [Image.open(path)]

    for img in images:
        t = pytesseract.image_to_string(img, lang="por") or ""
        texts.append(t)
        lens.append(len(t))
    return "\n".join(texts), lens


def _clean_lines(text: str) -> List[str]:
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l:
            continue
        if _NOISE_RE.search(l):
            continue
        out.append(l)
    return out


def _extract_owner_name(lines: List[str]) -> Optional[str]:
    for l in lines:
        if "PROPRIET" in l.upper():
            return l.split(":", 1)[-1].strip()
    return None


def _extract_fields(
    lines: List[str],
    proprietario_nome: Optional[str],
    proprietario_nome_ofuscado: bool,
) -> Dict[str, Any]:
    blob = " ".join(lines).upper()

    placa = _first(_PLACA_RE, blob)
    renavam = _first(_RENAVAM_RE, blob)

    marca_modelo = _value_after(lines, "MARCA")
    ano_fabricacao, ano_modelo = _extract_years(lines)
    cor = _value_after(lines, "COR")

    situacao_texto = _block_after(lines, "SITUAÇÃO")
    debitos_texto = _block_after(lines, "DÉBITOS")
    multas_texto = _block_after(lines, "MULTAS")

    return {
        "placa": placa,
        "renavam": renavam,
        "marca_modelo": marca_modelo,
        "ano_fabricacao": ano_fabricacao,
        "ano_modelo": ano_modelo,
        "cor": cor,
        "proprietario_nome": proprietario_nome,
        "proprietario_nome_ofuscado": proprietario_nome_ofuscado,
        "situacao_texto": situacao_texto,
        "debitos_texto": debitos_texto,
        "multas_texto": multas_texto,
    }


def _first(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text)
    return m.group(1) if m else None


def _value_after(lines: List[str], label: str) -> Optional[str]:
    for i, l in enumerate(lines):
        if label in l.upper():
            tail = l.split(":", 1)[-1].strip()
            if tail and tail.upper() != label:
                return tail
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    return None


def _extract_years(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    for l in lines:
        if "ANO" in l.upper():
            ys = _ANO_RE.findall(l)
            if len(ys) >= 2:
                return ys[0], ys[1]
            if len(ys) == 1:
                return ys[0], ys[0]
    return None, None


def _block_after(lines: List[str], label: str) -> Optional[str]:
    buf: List[str] = []
    capture = False
    for l in lines:
        if label in l.upper():
            capture = True
            continue
        if capture:
            if re.match(r"^[A-Z\s]{3,}$", l):
                break
            buf.append(l)
    return " ".join(buf).strip() if buf else None
