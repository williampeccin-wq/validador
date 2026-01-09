import os
import re
import tempfile
import subprocess
from typing import Tuple, Dict, Any, Optional, List
from PIL import Image, ImageOps, ImageEnhance
import pytesseract


def normalize_text(s: str) -> str:
    s = s or ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def diagnose_environment(tesseract_cmd: str, poppler_path: str) -> Dict[str, Any]:
    diag: Dict[str, Any] = {
        "tesseract_cmd": tesseract_cmd,
        "poppler_path": poppler_path,
        "tesseract_version": None,
        "pdfplumber": None,
        "poppler_pdftoppm": None,
        "poppler_version": None,
    }

    # pdfplumber (opcional)
    try:
        import importlib.metadata as _md
        import pdfplumber  # noqa: F401
        diag["pdfplumber"] = f"ok: {_md.version('pdfplumber')}"
    except Exception as e:
        diag["pdfplumber"] = f"ausente/erro: {type(e).__name__}: {e}"

    # tesseract
    try:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        v = subprocess.check_output([tesseract_cmd, "--version"], text=True, stderr=subprocess.STDOUT)
        diag["tesseract_version"] = v.strip()
    except Exception as e:
        diag["tesseract_version"] = f"erro: {type(e).__name__}: {e}"

    # pdftoppm
    try:
        pdftoppm = _find_pdftoppm(poppler_path)
        diag["poppler_pdftoppm"] = pdftoppm
        v = subprocess.check_output([pdftoppm, "-v"], text=True, stderr=subprocess.STDOUT)
        diag["poppler_version"] = v.strip()
    except Exception as e:
        diag["poppler_version"] = f"erro: {type(e).__name__}: {e}"

    return diag


def extract_text_any(
    file_bytes: bytes,
    filename: str,
    tesseract_cmd: str,
    poppler_path: str,
    min_text_len_threshold: int = 800,
    ocr_dpi: int = 350,
) -> Tuple[str, Dict[str, Any]]:
    """
    Retorna (texto, debug).
    - PDF: tenta texto nativo (pdfplumber) e, se insuficiente, OCR do PDF renderizado (pdftoppm + tesseract).
    - Imagem: OCR direto.
    """
    fn = (filename or "").lower()
    dbg: Dict[str, Any] = {
        "debug_src": None,
        "pages": None,
        "text_len": 0,
        "ocr_retry": False,
    }

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    if fn.endswith(".pdf"):
        text, dbg_pdf = _extract_pdf_text(
            pdf_bytes=file_bytes,
            poppler_path=poppler_path,
            min_text_len_threshold=min_text_len_threshold,
            ocr_dpi=ocr_dpi,
        )
        dbg.update(dbg_pdf)
        dbg["text_len"] = len(text or "")
        return normalize_text(text), dbg

    # imagem
    text = _ocr_image_bytes(file_bytes)
    dbg["debug_src"] = "image_ocr"
    dbg["text_len"] = len(text or "")
    return normalize_text(text), dbg


def _extract_pdf_text(
    pdf_bytes: bytes,
    poppler_path: str,
    min_text_len_threshold: int,
    ocr_dpi: int,
) -> Tuple[str, Dict[str, Any]]:
    dbg: Dict[str, Any] = {
        "debug_src": "pdfplumber",
        "pages": None,
        "ocr_retry": False,
        "ocr_variant": None,
    }

    text_plumber = ""
    pages = 0

    # 1) Texto nativo via pdfplumber (se disponível)
    try:
        import io
        import pdfplumber  # import lazy
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = len(pdf.pages)
            out = []
            for p in pdf.pages:
                out.append(p.extract_text() or "")
            text_plumber = "\n".join(out).strip()
    except Exception:
        text_plumber = ""

    dbg["pages"] = pages

    # Heurística para decidir OCR
    needs_ocr = (len(text_plumber) < min_text_len_threshold) or _looks_like_serpro_only(text_plumber)
    if not needs_ocr:
        return text_plumber, dbg

    # 2) OCR do PDF
    dbg["debug_src"] = "pdf_ocr"
    dbg["ocr_retry"] = True

    ocr_text, variant = _ocr_pdf_bytes_multipass(pdf_bytes, poppler_path=poppler_path, dpi=ocr_dpi)
    dbg["ocr_variant"] = variant

    # devolve o melhor disponível
    best = ocr_text or text_plumber
    return best, dbg


def _looks_like_serpro_only(text: str) -> bool:
    up = (text or "").upper()
    if not up:
        return True
    serpro_hits = any(k in up for k in ["ASSINADOR SERPRO", "MEDIDA PROVISÓRIA Nº 2200-2/2001", "SENATRAN", "QR-CODE"])
    field_hits = any(k in up for k in ["CPF", "NOME", "FILIA", "VALIDADE", "NASC", "CATEGORIA", "REGISTRO", "CNH"])
    return serpro_hits and (not field_hits)


def _ocr_pdf_bytes_multipass(pdf_bytes: bytes, poppler_path: str, dpi: int = 350) -> Tuple[str, str]:
    """
    Faz OCR com multipass:
      - pass 1: página inteira
      - pass 2: recorte superior (onde geralmente estão Nome / Nascimento)
      - pass 3: recorte central (fallback)
    Junta tudo removendo duplicatas de linhas.

    Retorna (texto, variant_label).
    """
    pdftoppm = _find_pdftoppm(poppler_path)

    with tempfile.TemporaryDirectory() as td:
        pdf_path = os.path.join(td, "in.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        out_prefix = os.path.join(td, "page")
        cmd = [pdftoppm, "-r", str(dpi), "-png", pdf_path, out_prefix]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        imgs = sorted([os.path.join(td, x) for x in os.listdir(td) if x.startswith("page") and x.endswith(".png")])
        texts: List[str] = []
        variant = "full+crop"

        for p in imgs:
            try:
                img = Image.open(p)
            except Exception:
                continue

            # Pass 1: full
            t_full = _ocr_image(img)
            # Pass 2: top crop
            t_top = _ocr_image(_crop_ratio(img, top=0.00, bottom=0.55))
            # Pass 3: middle crop
            t_mid = _ocr_image(_crop_ratio(img, top=0.30, bottom=0.80))

            merged = _merge_texts([t_full, t_top, t_mid])
            texts.append(merged)

        final = "\n".join([t for t in texts if t]).strip()
        return final, variant


def _crop_ratio(img: Image.Image, top: float, bottom: float) -> Image.Image:
    """
    Recorta verticalmente por proporção.
    top/bottom em [0..1].
    """
    w, h = img.size
    y1 = max(0, min(h, int(h * top)))
    y2 = max(0, min(h, int(h * bottom)))
    if y2 <= y1:
        return img
    return img.crop((0, y1, w, y2))


def _merge_texts(texts: List[str]) -> str:
    """
    Mescla textos removendo duplicações grosseiras por linha.
    Mantém ordem: full -> top -> mid.
    """
    seen = set()
    out_lines: List[str] = []

    for t in texts:
        if not t:
            continue
        for ln in t.splitlines():
            s = ln.strip()
            if not s:
                continue
            key = re.sub(r"\s+", " ", s).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out_lines.append(s)

    return "\n".join(out_lines).strip()


def _ocr_image_bytes(img_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tf:
        tf.write(img_bytes)
        tf.flush()
        img = Image.open(tf.name)
        return _ocr_image(img)


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """
    Pré-processamento leve e robusto (sem OpenCV):
    - grayscale
    - autocontrast
    - upscale 2x
    - sharpen leve
    - threshold simples
    """
    img = img.convert("L")
    img = ImageOps.autocontrast(img)

    # upscale
    w, h = img.size
    img = img.resize((w * 2, h * 2))

    # contraste + nitidez
    img = ImageEnhance.Contrast(img).enhance(1.6)
    img = ImageEnhance.Sharpness(img).enhance(1.4)

    # threshold
    img = img.point(lambda p: 255 if p > 170 else 0)

    return img


def _ocr_image(img: Image.Image) -> str:
    """
    OCR com config mais adequado para documento estruturado.
    """
    img2 = _preprocess_for_ocr(img)

    # Config: psm 6 (blocos) funciona melhor em CNH digital do que default
    config = "--oem 1 --psm 6"

    # por+eng para pegar PT + rótulos em inglês
    return pytesseract.image_to_string(img2, lang="por+eng", config=config)


def _find_pdftoppm(poppler_path: str) -> str:
    if poppler_path and os.path.isdir(poppler_path):
        candidate = os.path.join(poppler_path, "pdftoppm")
        if os.path.exists(candidate):
            return candidate

    for p in os.getenv("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, "pdftoppm")
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError("pdftoppm não encontrado. Ajuste POPPLER_PATH para a pasta que contém o binário.")
