# parsers/atpv.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MIN_NATIVE_TEXT_LEN = 800  # ajuste fino após os primeiros exemplos


@dataclass
class AtpvResult:
    placa: Optional[str] = None
    renavam: Optional[str] = None
    chassi: Optional[str] = None

    vendedor_nome: Optional[str] = None
    vendedor_cpf_cnpj: Optional[str] = None

    comprador_nome: Optional[str] = None
    comprador_cpf_cnpj: Optional[str] = None

    data_venda: Optional[str] = None  # dd/mm/aaaa
    municipio: Optional[str] = None
    uf: Optional[str] = None
    valor_venda: Optional[str] = None  # "12345,67" (BR)

    debug: Optional[Dict[str, Any]] = None


def analyze_atpv(path: str | Path, *, strict: bool = True) -> Dict[str, Any]:
    """
    Ponto de entrada público.
    strict=True (default): levanta ValueError se faltar campo obrigatório.
    strict=False: retorna melhor esforço e lista missing em debug (para gerar golden e iterar).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")

    mode, native_text, ocr_text, pages = _extract_text_hybrid(p)

    base_text = native_text if mode == "native" else ocr_text
    norm = _normalize(base_text)

    debug: Dict[str, Any] = {
        "mode": mode,
        "native_text_len": len(native_text),
        "ocr_text_len": len(ocr_text),
        "pages": pages,
        "min_text_len_threshold": MIN_NATIVE_TEXT_LEN,
    }

    result = AtpvResult(
        placa=_extract_placa(norm),
        renavam=_extract_renavam(norm),
        chassi=_extract_chassi(norm),
        vendedor_nome=None,
        vendedor_cpf_cnpj=None,
        comprador_nome=None,
        comprador_cpf_cnpj=None,
        data_venda=_extract_data_venda(norm),
        municipio=None,
        uf=None,
        valor_venda=_extract_valor_venda(norm),
        debug=debug,
    )

    vendedor_nome, vendedor_doc, comprador_nome, comprador_doc = _extract_partes(norm)
    result.vendedor_nome = vendedor_nome
    result.vendedor_cpf_cnpj = vendedor_doc
    result.comprador_nome = comprador_nome
    result.comprador_cpf_cnpj = comprador_doc

    municipio, uf = _extract_municipio_uf(norm)
    result.municipio = municipio
    result.uf = uf

    missing = _enforce_required_fields(result, strict=strict)
    if missing:
        if result.debug is None:
            result.debug = {}
        result.debug["missing_required"] = missing

    return asdict(result)


# --------------------------------------------------------------------------------------
# Extração híbrida (PDF nativo vs OCR)
# --------------------------------------------------------------------------------------

def _extract_text_hybrid(path: Path) -> Tuple[str, str, str, List[Dict[str, Any]]]:
    """
    Retorna (mode, native_text, ocr_text, pages_debug)
    mode ∈ {"native", "ocr"}
    """
    suffix = path.suffix.lower()
    pages_debug: List[Dict[str, Any]] = []

    native_text = ""
    ocr_text = ""

    if suffix == ".pdf":
        native_text, native_pages = _extract_pdf_native_text(path)
        pages_debug.extend(native_pages)

        if len(native_text) >= MIN_NATIVE_TEXT_LEN:
            return "native", native_text, "", pages_debug

        ocr_text, ocr_pages = _extract_pdf_ocr_text(path)
        pages_debug = ocr_pages
        return "ocr", native_text, ocr_text, pages_debug

    ocr_text, ocr_pages = _extract_image_ocr_text(path)
    pages_debug.extend(ocr_pages)
    return "ocr", "", ocr_text, pages_debug


def _extract_pdf_native_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    try:
        import pdfplumber  # type: ignore
    except Exception as e:
        raise RuntimeError("pdfplumber não disponível. Instale/importe no seu ambiente.") from e

    pages_debug: List[Dict[str, Any]] = []
    texts: List[str] = []

    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            texts.append(txt)
            pages_debug.append({"page": i + 1, "native_len": len(txt)})

    return "\n".join(texts), pages_debug


def _extract_pdf_ocr_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Rasteriza páginas e roda OCR.
    Você pode substituir por uma pipeline sua (p.ex. pdf2image + preprocess).
    """
    try:
        from pdf2image import convert_from_path  # type: ignore
    except Exception as e:
        raise RuntimeError("pdf2image não disponível (necessário para OCR em PDF escaneado).") from e

    try:
        import pytesseract  # type: ignore
    except Exception as e:
        raise RuntimeError("pytesseract não disponível. Instale/importe no seu ambiente.") from e

    pages_debug: List[Dict[str, Any]] = []
    texts: List[str] = []

    images = convert_from_path(str(path), dpi=300)
    for idx, img in enumerate(images):
        txt = pytesseract.image_to_string(img, lang="por") or ""
        texts.append(txt)
        pages_debug.append({"page": idx + 1, "ocr_len": len(txt)})

    return "\n".join(texts), pages_debug


def _extract_image_ocr_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError("Pillow (PIL) não disponível.") from e

    try:
        import pytesseract  # type: ignore
    except Exception as e:
        raise RuntimeError("pytesseract não disponível. Instale/importe no seu ambiente.") from e

    img = Image.open(str(path))
    txt = pytesseract.image_to_string(img, lang="por") or ""
    return txt, [{"page": 1, "ocr_len": len(txt)}]


# --------------------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------------------

def _normalize(text: str) -> str:
    t = text.replace("\u00a0", " ")
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _cleanup_doc(doc: Optional[str]) -> Optional[str]:
    if not doc:
        return None
    d = _only_digits(doc)
    if len(d) in (11, 14):
        return d
    return None


# --------------------------------------------------------------------------------------
# Extratores de campos “simples”
# --------------------------------------------------------------------------------------

def _extract_placa(text: str) -> Optional[str]:
    # Placa BR: AAA0A00 (Mercosul) ou AAA0000
    patterns = [
        r"\b([A-Z]{3}\d[A-Z0-9]\d{2})\b",  # Mercosul
        r"\b([A-Z]{3}\d{4})\b",            # Antiga
    ]
    upper = _strip_accents(text).upper()
    for pat in patterns:
        m = re.search(pat, upper)
        if m:
            return m.group(1)
    return None


def _extract_renavam(text: str) -> Optional[str]:
    # Preferir âncora "RENAVAM"
    upper = _strip_accents(text).upper()

    anchored = re.search(r"RENAVAM[:\s]*([0-9\.\- ]{9,15})", upper)
    if anchored:
        d = _only_digits(anchored.group(1))
        if 9 <= len(d) <= 11:
            return d

    # fallback: sequência 11 dígitos
    cand = re.search(r"\b(\d{11})\b", upper)
    return cand.group(1) if cand else None


def _extract_chassi(text: str) -> Optional[str]:
    upper = _strip_accents(text).upper()

    anchored = re.search(r"CHASSI[:\s]*([A-HJ-NPR-Z0-9]{17})", upper)
    if anchored:
        return anchored.group(1)

    cand = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", upper)
    return cand.group(1) if cand else None


def _extract_data_venda(text: str) -> Optional[str]:
    upper = _strip_accents(text).upper()

    candidates: List[str] = []
    for pat in [
        r"DATA\s+DA\s+VENDA[:\s]*([0-3]?\d/[01]?\d/\d{4})",
        r"DATA\s+DA\s+TRANSFERENCIA[:\s]*([0-3]?\d/[01]?\d/\d{4})",
        r"DATA[:\s]*([0-3]?\d/[01]?\d/\d{4})",
    ]:
        for m in re.finditer(pat, upper):
            candidates.append(m.group(1))

    if candidates:
        return candidates[0]

    m = re.search(r"\b([0-3]?\d/[01]?\d/\d{4})\b", upper)
    return m.group(1) if m else None


def _extract_valor_venda(text: str) -> Optional[str]:
    upper = _strip_accents(text).upper()

    anchored = re.search(
        r"(VALOR\s+(DA\s+)?VENDA|PRECO)\s*[:\s]*R?\$?\s*([0-9\.\s]+,[0-9]{2})",
        upper,
    )
    if anchored:
        return anchored.group(3).replace(" ", "")

    m = re.search(r"R\$\s*([0-9\.\s]+,[0-9]{2})", upper)
    return m.group(1).replace(" ", "") if m else None


# --------------------------------------------------------------------------------------
# Partes (vendedor/comprador)
# --------------------------------------------------------------------------------------

def _extract_partes(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    upper = _strip_accents(text).upper()

    vendedor_block = _extract_labeled_block(upper, ["VENDEDOR", "PROPRIETARIO", "ALIENANTE"])
    comprador_block = _extract_labeled_block(upper, ["COMPRADOR", "ADQUIRENTE", "COMPRADOR(A)"])

    v_nome, v_doc = _extract_nome_e_doc_from_block(vendedor_block) if vendedor_block else (None, None)
    c_nome, c_doc = _extract_nome_e_doc_from_block(comprador_block) if comprador_block else (None, None)

    # Fallback por documentos
    if not (v_doc and c_doc):
        docs = _find_all_docs(upper)
        uniq_docs: List[str] = []
        for d in docs:
            if d not in uniq_docs:
                uniq_docs.append(d)

        if len(uniq_docs) >= 2:
            if not v_doc:
                v_doc = uniq_docs[0]
                v_nome = v_nome or _infer_name_near_doc(upper, v_doc)
            if not c_doc:
                c_doc = uniq_docs[1]
                c_nome = c_nome or _infer_name_near_doc(upper, c_doc)

    return v_nome, _cleanup_doc(v_doc), c_nome, _cleanup_doc(c_doc)


def _extract_labeled_block(text_upper: str, labels: List[str]) -> Optional[str]:
    lines = [ln.strip() for ln in text_upper.splitlines()]
    label_set = set(labels)

    stop_words = {"COMPRADOR", "ADQUIRENTE", "VENDEDOR", "ALIENANTE", "PROPRIETARIO", "VEICULO", "DADOS DO VEICULO"}

    for i, ln in enumerate(lines):
        for lab in label_set:
            if re.search(rf"\b{re.escape(lab)}\b", ln):
                chunk_lines: List[str] = []
                for j in range(i, min(i + 12, len(lines))):
                    if j > i and any(re.search(rf"\b{w}\b", lines[j]) for w in stop_words):
                        break
                    chunk_lines.append(lines[j])
                block = "\n".join(chunk_lines).strip()
                return block if block else None
    return None


def _extract_nome_e_doc_from_block(block_upper: str) -> Tuple[Optional[str], Optional[str]]:
    doc = None
    m = re.search(r"(CPF|CNPJ)\s*[:\s]*([0-9\.\-\/ ]{11,20})", block_upper)
    if m:
        doc = _only_digits(m.group(2))
    else:
        docs = _find_all_docs(block_upper)
        doc = docs[0] if docs else None

    nome = _infer_name_from_block(block_upper)
    return nome, doc


def _find_all_docs(text_upper: str) -> List[str]:
    found: List[str] = []

    for m in re.finditer(r"\b(\d{3}\.?\d{3}\.?\d{3}\-?\d{2})\b", text_upper):
        found.append(_only_digits(m.group(1)))
    for m in re.finditer(r"\b(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}\-?\d{2})\b", text_upper):
        found.append(_only_digits(m.group(1)))

    for m in re.finditer(r"\b(\d{11})\b", text_upper):
        found.append(m.group(1))
    for m in re.finditer(r"\b(\d{14})\b", text_upper):
        found.append(m.group(1))

    return [d for d in found if len(d) in (11, 14)]


def _infer_name_from_block(block_upper: str) -> Optional[str]:
    stop = {
        "VENDEDOR", "COMPRADOR", "ADQUIRENTE", "ALIENANTE", "PROPRIETARIO",
        "CPF", "CNPJ", "RG", "DOCUMENTO", "ENDERECO", "CEP", "MUNICIPIO", "UF",
        "VEICULO", "CHASSI", "RENAVAM", "PLACA", "DATA", "VALOR"
    }

    lines = [ln.strip() for ln in block_upper.splitlines() if ln.strip()]
    candidates: List[str] = []

    for ln in lines:
        ln2 = re.sub(r"[^A-Z0-9 \-]", " ", ln)
        ln2 = re.sub(r"\s+", " ", ln2).strip()

        digit_ratio = (sum(ch.isdigit() for ch in ln2) / max(1, len(ln2)))
        if digit_ratio > 0.20:
            continue

        toks = ln2.split()
        if len(toks) < 2:
            continue

        stop_hits = sum(1 for t in toks if t in stop)
        if stop_hits >= max(1, len(toks) // 2):
            continue

        candidates.append(ln2)

    if not candidates:
        return None

    candidates.sort(key=len, reverse=True)
    return candidates[0].strip() or None


def _infer_name_near_doc(text_upper: str, doc_digits: str) -> Optional[str]:
    lines = text_upper.splitlines()
    for i, ln in enumerate(lines):
        if doc_digits and doc_digits in _only_digits(ln):
            start = max(0, i - 3)
            end = min(len(lines), i + 4)
            block = "\n".join(lines[start:end])
            return _infer_name_from_block(block)
    return None


# --------------------------------------------------------------------------------------
# Município/UF  (CORRIGIDO: nunca retornar tupla aninhada)
# --------------------------------------------------------------------------------------

def _extract_municipio_uf(text: str) -> Tuple[Optional[str], Optional[str]]:
    upper = _strip_accents(text).upper()

    m = re.search(r"MUNICIPIO\s*[:\s]*([A-Z ]+)\s+UF\s*[:\s]*([A-Z]{2})\b", upper)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    m = re.search(r"(MUNICIPIO|CIDADE)\s*[:\s]*([A-Z ]+)\b", upper)
    if m:
        municipio = m.group(2).strip()
        tail = upper[m.end(): m.end() + 200]
        ufm = re.search(r"\bUF\s*[:\s]*([A-Z]{2})\b", tail)
        uf = ufm.group(1).strip() if ufm else None
        return municipio, uf

    m = re.search(r"\b([A-Z]{3,}(?:\s+[A-Z]{2,})*)\s*[-/]\s*([A-Z]{2})\b", upper)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    return None, None


# --------------------------------------------------------------------------------------
# Regras de obrigatoriedade
# --------------------------------------------------------------------------------------

def _enforce_required_fields(r: AtpvResult, *, strict: bool) -> List[str]:
    missing: List[str] = []

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

    for k, v in required:
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(k)

    if missing and strict:
        raise ValueError(f"ATPV: campos obrigatórios ausentes: {missing}")

    return missing
