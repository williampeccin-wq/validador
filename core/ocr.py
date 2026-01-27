# core/ocr.py
import base64
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageEnhance, ImageOps


def normalize_text(s: str) -> str:
    s = s or ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _resolve_tesseract_cmd(tesseract_cmd: str | None) -> str:
    """
    Nunca retorne string vazia.
    - se vier vazio, tenta shutil.which("tesseract")
    - se não achar, retorna "tesseract" (deixa o SO resolver)
    """
    cmd = (tesseract_cmd or "").strip()
    if cmd:
        return cmd
    found = shutil.which("tesseract")
    return found or "tesseract"


def _ensure_pytesseract_cmd(tesseract_cmd: str | None) -> str:
    """
    Garante que pytesseract esteja apontando para um comando válido.
    Retorna o cmd efetivo.
    """
    cmd = _resolve_tesseract_cmd(tesseract_cmd)
    try:
        import pytesseract  # type: ignore

        # só seta se for algo não-vazio (cmd aqui nunca é vazio)
        pytesseract.pytesseract.tesseract_cmd = cmd
    except Exception:
        # Sem pytesseract, não tem OCR (extract_text_any lida com isso).
        pass
    return cmd


def diagnose_environment(tesseract_cmd: str, poppler_path: str) -> Dict[str, Any]:
    cmd = _ensure_pytesseract_cmd(tesseract_cmd)

    diag: Dict[str, Any] = {
        "tesseract_cmd_effective": cmd,
        "tesseract_cmd_input": tesseract_cmd,
        "poppler_path": poppler_path,
        "tesseract_version": None,
        "pdfplumber": None,
        "poppler_pdftoppm": None,
        "poppler_version": None,
        "pytesseract": None,
    }

    try:
        import importlib.metadata as _md

        import pdfplumber  # noqa: F401

        diag["pdfplumber"] = f"ok: {_md.version('pdfplumber')}"
    except Exception as e:
        diag["pdfplumber"] = f"erro: {type(e).__name__}: {e}"

    try:
        import importlib.metadata as _md

        import pytesseract  # type: ignore

        diag["pytesseract"] = f"ok: {_md.version('pytesseract')}"
        try:
            v = subprocess.check_output([cmd, "--version"], text=True, stderr=subprocess.STDOUT)
            diag["tesseract_version"] = v.strip()
        except Exception as e:
            diag["tesseract_version"] = f"erro: {type(e).__name__}: {e}"
    except Exception as e:
        diag["pytesseract"] = f"erro: {type(e).__name__}: {e}"

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
    - PDF: tenta texto nativo (pdfplumber) e, se insuficiente, OCR (pdftoppm + tesseract).
    - Imagem: OCR direto.
    """
    fn = (filename or "").lower()
    cmd = _ensure_pytesseract_cmd(tesseract_cmd)

    dbg: Dict[str, Any] = {
        "debug_src": None,
        "pages": None,
        "text_len": 0,
        "ocr_retry": False,
        "tesseract_cmd_effective": cmd,
        "poppler_path": poppler_path or "",
    }

    # OCR deps
    try:
        import pytesseract  # noqa: F401
    except Exception as e:
        # Sem OCR, ainda tenta nativo em PDF
        if fn.endswith(".pdf"):
            text, dbg_pdf = _extract_pdf_text(
                pdf_bytes=file_bytes,
                poppler_path=poppler_path,
                min_text_len_threshold=min_text_len_threshold,
                ocr_dpi=ocr_dpi,
                ocr_available=False,
                ocr_unavailable_error=f"{type(e).__name__}: {e}",
            )
            dbg.update(dbg_pdf)
            dbg["text_len"] = len(text or "")
            return normalize_text(text), dbg

        dbg["debug_src"] = "ocr_unavailable"
        dbg["text_len"] = 0
        dbg["ocr_error"] = f"{type(e).__name__}: {e}"
        return "", dbg

    if fn.endswith(".pdf"):
        text, dbg_pdf = _extract_pdf_text(
            pdf_bytes=file_bytes,
            poppler_path=poppler_path,
            min_text_len_threshold=min_text_len_threshold,
            ocr_dpi=ocr_dpi,
            ocr_available=True,
            ocr_unavailable_error=None,
        )
        dbg.update(dbg_pdf)
        dbg["text_len"] = len(text or "")
        return normalize_text(text), dbg

    dbg["debug_src"] = "image_ocr"
    try:
        from io import BytesIO

        img = Image.open(BytesIO(file_bytes))
        text = _ocr_image(img, tesseract_cmd=cmd)
        dbg["text_len"] = len(text or "")
        return normalize_text(text), dbg
    except Exception as e:
        dbg["ocr_error"] = f"{type(e).__name__}: {e}"
        return "", dbg


def _looks_like_serpro_only(text: str) -> bool:
    if not text:
        return True
    t = text.upper()
    hits = 0
    for token in [
        "REPÚBLICA",
        "REPUBLICA",
        "FEDERATIVA",
        "BRASIL",
        "SECRETARIA NACIONAL",
        "SENATRAN",
        "CARTEIRA NACIONAL",
        "TRÂNSITO",
        "TRANSITO",
    ]:
        if token in t:
            hits += 1
    return hits >= 3 and len(t) < 1500


def _extract_pdf_text(
    pdf_bytes: bytes,
    poppler_path: str,
    min_text_len_threshold: int,
    ocr_dpi: int,
    ocr_available: bool,
    ocr_unavailable_error: str | None,
) -> Tuple[str, Dict[str, Any]]:
    dbg: Dict[str, Any] = {
        "debug_src": "pdfplumber",
        "pages": None,
        "ocr_retry": False,
        "ocr_variant": None,
    }

    text_plumber = ""
    pages = 0

    try:
        import io
        import pdfplumber  # type: ignore

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = len(pdf.pages)
            out = []
            for p in pdf.pages:
                out.append(p.extract_text() or "")
            text_plumber = "\n".join(out).strip()
    except Exception:
        text_plumber = ""

    dbg["pages"] = pages

    needs_ocr = (len(text_plumber) < min_text_len_threshold) or _looks_like_serpro_only(text_plumber)
    if not needs_ocr:
        return text_plumber, dbg

    if not ocr_available:
        dbg["debug_src"] = "pdf_native_only"
        dbg["ocr_retry"] = False
        if ocr_unavailable_error:
            dbg["ocr_error"] = ocr_unavailable_error
        return text_plumber, dbg

    dbg["debug_src"] = "pdf_ocr"
    dbg["ocr_retry"] = True

    ocr_text, variant = _ocr_pdf_bytes_multipass(pdf_bytes, poppler_path=poppler_path, dpi=ocr_dpi)
    dbg["ocr_variant"] = variant

    best = ocr_text or text_plumber
    return best, dbg


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img2 = ImageOps.grayscale(img)
    img2 = ImageEnhance.Contrast(img2).enhance(1.6)
    img2 = ImageEnhance.Sharpness(img2).enhance(1.2)
    return img2


def _ocr_image(img: Image.Image, *, tesseract_cmd: str | None = None) -> str:
    """
    OCR com config adequado para documento estruturado.
    """
    _ensure_pytesseract_cmd(tesseract_cmd)
    img2 = _preprocess_for_ocr(img)
    config = "--oem 1 --psm 6"
    import pytesseract  # type: ignore

    return pytesseract.image_to_string(img2, lang="por+eng", config=config)


def _crop_ratio(img: Image.Image, top: float, bottom: float) -> Image.Image:
    w, h = img.size
    y1 = max(0, min(h, int(h * top)))
    y2 = max(0, min(h, int(h * bottom)))
    if y2 <= y1:
        return img
    return img.crop((0, y1, w, y2))


def _merge_texts(texts: List[str]) -> str:
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


def _ocr_pdf_bytes_multipass(pdf_bytes: bytes, poppler_path: str, dpi: int = 350) -> Tuple[str, str]:
    """
    Multipass (full + crops). Importante: garante tesseract_cmd resolvido
    mesmo quando chamada diretamente (sem passar por extract_text_any).
    """
    cmd = _ensure_pytesseract_cmd(os.getenv("TESSERACT_CMD", ""))
    pdftoppm = _find_pdftoppm(poppler_path)

    with tempfile.TemporaryDirectory() as td:
        pdf_path = os.path.join(td, "in.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        out_prefix = os.path.join(td, "page")
        subprocess.check_call([pdftoppm, "-r", str(dpi), "-png", pdf_path, out_prefix])

        imgs = sorted([os.path.join(td, x) for x in os.listdir(td) if x.startswith("page") and x.endswith(".png")])
        texts: List[str] = []
        variant = "full+crop"

        for p in imgs:
            try:
                img = Image.open(p)
            except Exception:
                continue

            t_full = _ocr_image(img, tesseract_cmd=cmd)
            t_top = _ocr_image(_crop_ratio(img, top=0.00, bottom=0.55), tesseract_cmd=cmd)
            t_mid = _ocr_image(_crop_ratio(img, top=0.30, bottom=0.80), tesseract_cmd=cmd)

            texts.append(_merge_texts([t_full, t_top, t_mid]))

        final = "\n".join([t for t in texts if t]).strip()
        return final, variant


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


def _decode_base64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64 or "")
