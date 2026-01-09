from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FonteExtracao:
    mode: str
    native_text_len: int
    ocr_text_len: int
    pages: List[Dict[str, Any]]


@dataclass
class DocumentoVeiculoResult:
    documento: Optional[str]
    placa: Optional[str]
    renavam: Optional[str]
    chassi: Optional[str]
    ano_fabricacao: Optional[int]
    ano_modelo: Optional[int]
    proprietario: Optional[str]
    fonte: FonteExtracao
    debug: Dict[str, Any]


class DocumentoVeiculoBase:
    def __init__(self, min_text_len_threshold: int = 800, ocr_dpi: int = 300):
        self.min_text_len_threshold = min_text_len_threshold
        self.ocr_dpi = ocr_dpi

    @staticmethod
    def _remover_acentos(txt: str) -> str:
        nfkd = unicodedata.normalize("NFKD", txt)
        return "".join([c for c in nfkd if not unicodedata.combining(c)])

    def _normalize(self, txt: str) -> str:
        txt = (txt or "").upper()
        txt = self._remover_acentos(txt)
        txt = re.sub(r"[^\w\s/:\-\.]", " ", txt)
        txt = re.sub(r"\s{2,}", " ", txt).strip()
        return txt

    def _extract_text_hybrid(self, file_path: str) -> Tuple[str, FonteExtracao, Dict[str, Any]]:
        """
        Estratégia:
          - tenta texto nativo via pdfplumber
          - se for curto, tenta OCR (se render funcionar)
        """
        import pdfplumber  # type: ignore

        debug: Dict[str, Any] = {
            "min_text_len_threshold": self.min_text_len_threshold,
            "ocr_dpi": self.ocr_dpi,
            "native": {"pages": []},
            "ocr": {"pages": []},
            "render": {},
        }

        native_text_parts: List[str] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    t = page.extract_text() or ""
                    native_text_parts.append(t)
                    debug["native"]["pages"].append({"page": i + 1, "len": len(t)})
        except Exception as e:
            debug["native"]["error"] = f"{type(e).__name__}: {e}"

        native_text = "\n".join(native_text_parts).strip()
        native_len = len(native_text)

        fonte = FonteExtracao(
            mode="native",
            native_text_len=native_len,
            ocr_text_len=0,
            pages=[{"page": i + 1, "native_len": p["len"], "ocr_len": 0} for i, p in enumerate(debug["native"]["pages"])],
        )

        if native_len >= self.min_text_len_threshold:
            return native_text, fonte, debug

        # tenta OCR (sem quebrar se não houver backend de render)
        ocr_text_parts: List[str] = []
        images = self._render_to_images_soft(file_path, dpi=self.ocr_dpi, debug=debug)
        if not images:
            # sem OCR possível
            return native_text, fonte, debug

        try:
            import pytesseract  # type: ignore

            for i, img in enumerate(images):
                o = pytesseract.image_to_string(img, lang="por")
                ocr_text_parts.append(o)
                debug["ocr"]["pages"].append({"page": i + 1, "len": len(o)})
        except Exception as e:
            debug["ocr"]["error"] = f"{type(e).__name__}: {e}"

        ocr_text = "\n".join(ocr_text_parts).strip()
        ocr_len = len(ocr_text)

        fonte = FonteExtracao(
            mode="ocr" if ocr_len > native_len else "native",
            native_text_len=native_len,
            ocr_text_len=ocr_len,
            pages=[
                {
                    "page": i + 1,
                    "native_len": (debug["native"]["pages"][i]["len"] if i < len(debug["native"]["pages"]) else 0),
                    "ocr_len": (debug["ocr"]["pages"][i]["len"] if i < len(debug["ocr"]["pages"]) else 0),
                }
                for i in range(max(len(debug["native"]["pages"]), len(debug["ocr"]["pages"])))
            ],
        )

        # retorna o melhor texto (normalmente OCR quando nativo é curto)
        if ocr_len > native_len:
            return ocr_text, fonte, debug
        return native_text, fonte, debug

    def _render_to_images_soft(self, file_path: str, dpi: int, debug: Optional[Dict[str, Any]] = None) -> List[Any]:
        """
        Renderiza PDF para imagens.
        Tenta PyMuPDF (fitz) primeiro. Se não existir, tenta pdf2image.
        Retorna [] se não conseguir, sem lançar exceção.
        """
        if debug is None:
            debug = {}
        debug.setdefault("render", {})
        debug["render"]["dpi"] = dpi

        # 1) PyMuPDF
        try:
            import fitz  # type: ignore
            from PIL import Image  # type: ignore
            import io

            doc = fitz.open(file_path)
            images = []
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)

            for i in range(len(doc)):
                pix = doc.load_page(i).get_pixmap(matrix=mat, alpha=False)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                images.append(img)

            debug["render"]["backend"] = "fitz"
            debug["render"]["pages"] = len(images)
            return images
        except Exception as e:
            debug["render"]["fitz_error"] = f"{type(e).__name__}: {e}"

        # 2) pdf2image (precisa poppler no mac)
        try:
            from pdf2image import convert_from_path  # type: ignore

            images = convert_from_path(file_path, dpi=dpi)
            debug["render"]["backend"] = "pdf2image"
            debug["render"]["pages"] = len(images)
            return images
        except Exception as e:
            debug["render"]["error"] = f"pdf2image_failed: {e}"
            return []

    def _render_to_images(self, file_path: str, dpi: int) -> List[Any]:
        """
        Compat shim.

        Código legado (ex.: parser de documento antigo) chamava `_render_to_images()`.
        A implementação atual centraliza em `_render_to_images_soft()` com debug.
        """
        return self._render_to_images_soft(file_path, dpi=dpi, debug={})
