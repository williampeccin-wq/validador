# parsers/documento_veiculo_base.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FonteExtracao:
    mode: str  # "native" | "ocr"
    native_text_len: int
    ocr_text_len: int
    text_len: int
    min_text_len_threshold: int
    ocr_dpi: int
    pages: List[Dict[str, Any]]


@dataclass
class DocumentoVeiculoResult:
    documento: Optional[str]  # "CRLV" | "CRV" | None
    placa: Optional[str]
    renavam: Optional[str]
    chassi: Optional[str]
    ano_modelo: Optional[int]
    ano_fabricacao: Optional[int]
    proprietario: Optional[str]
    fonte: FonteExtracao
    debug: Dict[str, Any]


class DocumentoVeiculoBase:
    # Placa AAA0000 e Mercosul AAA0A00
    RE_PLACA = re.compile(r"^(?:[A-Z]{3}\d{4}|[A-Z]{3}\d[A-Z0-9]\d{2})$")

    # Chassi 17 sem I/O/Q
    RE_CHASSI = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

    # Ano
    RE_ANO = re.compile(r"(?:19|20)\d{2}")

    # RENAVAM
    RE_RENAVAM_11 = re.compile(r"\b\d{11}\b")
    RE_RENAVAM_LABEL_FUZZY = re.compile(r"\bRENAV[A-Z0-9]{0,3}\b")

    # UF
    RE_UF = re.compile(
        r"^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$"
    )

    RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")

    SIGNAIS_CRLVE = (
        "CERTIFICADO DE REGISTRO E LICENCIAMENTO DE VEICULO - DIGITAL",
        "ASSINADO DIGITALMENTE",
        "CARTEIRA DIGITAL DE TRANSITO",
        "GOV.BR",
        "QR CODE",
        "QRCODE",
    )

    def __init__(self, min_text_len_threshold: int = 800, ocr_dpi: int = 300) -> None:
        self.min_text_len_threshold = int(min_text_len_threshold)
        self.ocr_dpi = int(ocr_dpi)

    # -------------------------
    # Núcleo: extração híbrida
    # -------------------------

    def _extract_text_hybrid(self, file_path: str) -> Tuple[str, FonteExtracao]:
        native_text = ""
        native_pages: List[str] = []

        if file_path.lower().endswith(".pdf"):
            try:
                import pdfplumber  # type: ignore

                with pdfplumber.open(file_path) as pdf:
                    for p in pdf.pages:
                        t = p.extract_text() or ""
                        native_pages.append(t)
                        if t.strip():
                            native_text += t + "\n"
            except Exception:
                native_text = ""
                native_pages = []

        native_len = len(native_text)
        if native_len >= self.min_text_len_threshold:
            fonte = FonteExtracao(
                mode="native",
                native_text_len=native_len,
                ocr_text_len=0,
                text_len=native_len,
                min_text_len_threshold=self.min_text_len_threshold,
                ocr_dpi=self.ocr_dpi,
                pages=[{"page": i + 1, "native_len": len(t), "ocr_len": 0} for i, t in enumerate(native_pages)],
            )
            return native_text, fonte

        # OCR
        import pytesseract  # type: ignore

        images = self._render_to_images(file_path, dpi=self.ocr_dpi)
        config = "--oem 3 --psm 6"
        ocr_pages = [pytesseract.image_to_string(img, lang="por", config=config) or "" for img in images]
        ocr_text = "\n".join([t for t in ocr_pages if t.strip()])

        fonte = FonteExtracao(
            mode="ocr",
            native_text_len=native_len,
            ocr_text_len=len(ocr_text),
            text_len=len(ocr_text),
            min_text_len_threshold=self.min_text_len_threshold,
            ocr_dpi=self.ocr_dpi,
            pages=[
                {
                    "page": i + 1,
                    "native_len": len(native_pages[i]) if i < len(native_pages) else 0,
                    "ocr_len": len(ocr_pages[i]),
                }
                for i in range(len(ocr_pages))
            ],
        )
        return ocr_text, fonte

    def _render_to_images(self, file_path: str, dpi: int) -> List[Any]:
        from PIL import Image  # type: ignore

        if not file_path.lower().endswith(".pdf"):
            return [Image.open(file_path)]

        import fitz  # type: ignore

        doc = fitz.open(file_path)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        out: List[Any] = []
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out.append(img)
        doc.close()
        return out

    # -------------------------
    # Normalização e tipo doc
    # -------------------------

    @staticmethod
    def _remove_acentos(txt: str) -> str:
        nfkd = unicodedata.normalize("NFKD", txt)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    def _normalize(self, txt: str) -> str:
        txt = (txt or "").replace("\u0000", " ")
        txt = self._remove_acentos(txt).upper()
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\r\n|\r", "\n", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt)
        return txt.strip()

    def _doc_type_signals(self, txt: str) -> Dict[str, Any]:
        return {
            "crlve_hits": [s for s in self.SIGNAIS_CRLVE if s in txt],
            "has_registro_veiculo": ("CERTIFICADO DE REGISTRO DE VEICULO" in txt or "REGISTRO DE VEICULO" in txt),
            "has_licenciamento": ("LICENCIAMENTO" in txt),
        }

    def _infer_doc_type(self, txt: str) -> Optional[str]:
        if "CERTIFICADO DE REGISTRO DE VEICULO" in txt or "REGISTRO DE VEICULO" in txt:
            return "CRV"
        if any(s in txt for s in self.SIGNAIS_CRLVE):
            return "CRLV"
        if "LICENCIAMENTO" in txt:
            return "CRLV"
        return None

    def _coerce_year(self, s: Optional[str]) -> Optional[int]:
        if not s:
            return None
        try:
            y = int(s)
            if 1950 <= y <= 2099:
                return y
        except Exception:
            return None
        return None

    def _postprocess_years(self, out: Dict[str, Any]) -> Dict[str, Any]:
        fab = out.get("ano_fabricacao")
        mod = out.get("ano_modelo")
        if fab and not mod:
            out["ano_modelo"] = fab
        if mod and not fab:
            out["ano_fabricacao"] = mod

        # CRLV-e às vezes tem discrepância grande por OCR -> estabiliza
        if out.get("documento") == "CRLV" and fab and mod and fab != mod:
            if abs(fab - mod) >= 4:
                y = min(fab, mod)
                out["ano_fabricacao"] = y
                out["ano_modelo"] = y
        return out

    # -------------------------
    # OCR layout (tesseract data)
    # -------------------------

    def _build_words_from_tesseract(self, data: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        words: List[Dict[str, Any]] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue

            conf_raw = str(data.get("conf", ["-1"] * n)[i]).strip()
            conf = float(conf_raw) if conf_raw not in ("-1", "") else -1.0
            if conf >= 0 and conf < 25:
                continue

            left = int(data["left"][i])
            top = int(data["top"][i])
            width = int(data["width"][i])
            height = int(data["height"][i])

            words.append(
                {
                    "text": text,
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "cx": left + width // 2,
                    "cy": top + height // 2,
                    "block_num": int(data.get("block_num", [0] * n)[i]),
                    "par_num": int(data.get("par_num", [0] * n)[i]),
                    "line_num": int(data.get("line_num", [0] * n)[i]),
                }
            )
        return words

    def _build_lines_from_words(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        buckets: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}
        for w in words:
            key = (w.get("block_num", 0), w.get("par_num", 0), w.get("line_num", 0))
            buckets.setdefault(key, []).append(w)

        lines: List[Dict[str, Any]] = []
        for ws in buckets.values():
            ws.sort(key=lambda x: x["left"])
            text = " ".join(w["text"] for w in ws).strip()
            if not text:
                continue
            x1 = min(w["left"] for w in ws)
            y1 = min(w["top"] for w in ws)
            x2 = max(w["left"] + w["width"] for w in ws)
            y2 = max(w["top"] + w["height"] for w in ws)
            lines.append(
                {
                    "text": text,
                    "bbox": (x1, y1, x2, y2),
                    "tokens": text.split(),
                    "token_boxes": [(w["left"], w["top"], w["width"], w["height"]) for w in ws],
                }
            )
        lines.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
        return lines

    # -------------------------
    # Região próxima a label
    # -------------------------

    def _tok_norm(self, s: str) -> str:
        s = self._normalize(s)
        s = re.sub(r"[^A-Z0-9/]", "", s)
        return s

    def _find_all_label_bboxes(
        self,
        lines: List[Dict[str, Any]],
        label_tokens: Tuple[str, ...],
        page_dbg: Dict[str, Any],
        key: str,
    ) -> List[Dict[str, int]]:
        want = [self._tok_norm(tok) for tok in label_tokens if tok]
        found: List[Dict[str, int]] = []

        for idx, ln in enumerate(lines):
            tokens = [self._tok_norm(t) for t in ln["tokens"]]
            if not tokens:
                continue
            for start in range(0, max(0, len(tokens) - len(want)) + 1):
                if tokens[start : start + len(want)] == want:
                    bbox = self._union_bboxes(ln["token_boxes"][start : start + len(want)])
                    page_dbg["labels_found"].setdefault(key, [])
                    page_dbg["labels_found"][key].append({"line_idx": idx, "bbox": bbox, "line_text": ln["text"]})
                    found.append(bbox)
        return found

    @staticmethod
    def _union_bboxes(boxes: List[Tuple[int, int, int, int]]) -> Dict[str, int]:
        xs1 = [b[0] for b in boxes]
        ys1 = [b[1] for b in boxes]
        xs2 = [b[0] + b[2] for b in boxes]
        ys2 = [b[1] + b[3] for b in boxes]
        return {"x1": min(xs1), "y1": min(ys1), "x2": max(xs2), "y2": max(ys2)}

    def _words_near_label(
        self,
        words: List[Dict[str, Any]],
        label_bbox: Dict[str, int],
        line_tol: int,
        below_height: int,
        right_width: int,
    ) -> List[Dict[str, Any]]:
        lx1, ly1, lx2, ly2 = label_bbox["x1"], label_bbox["y1"], label_bbox["x2"], label_bbox["y2"]
        lcy = (ly1 + ly2) // 2

        region: List[Dict[str, Any]] = []
        for w in words:
            cx, cy = w["cx"], w["cy"]
            if abs(cy - lcy) <= line_tol and cx >= lx2 and cx <= lx2 + right_width:
                region.append(w)
                continue
            if cy >= ly2 and cy <= ly2 + below_height and cx >= lx1 - 40 and cx <= lx2 + right_width:
                region.append(w)
        return region

    def _digits_near_label(self, words: List[Dict[str, Any]], label_bbox: Dict[str, int], line_tol: int, below_height: int) -> str:
        picked = self._words_near_label(words, label_bbox, line_tol=line_tol, below_height=below_height, right_width=1300)
        picked.sort(key=lambda w: (w["cy"], w["cx"]))
        digits = []
        for w in picked:
            digits.extend(re.findall(r"\d", w["text"]))
        return "".join(digits)

    def _alnum_near_label(self, words: List[Dict[str, Any]], label_bbox: Dict[str, int], line_tol: int, below_height: int, max_chars: int) -> str:
        picked = self._words_near_label(words, label_bbox, line_tol=line_tol, below_height=below_height, right_width=1300)
        picked.sort(key=lambda w: (w["cy"], w["cx"]))
        out = []
        for w in picked:
            out.append(w["text"])
            if sum(len(x) for x in out) >= max_chars:
                break
        return " ".join(out)

    # -------------------------
    # Extratores “comuns”
    # -------------------------

    def _best_renavam_from_digits(self, digits: str) -> Optional[str]:
        if not digits:
            return None
        if len(digits) == 11:
            return digits
        if len(digits) > 11:
            for i in range(0, len(digits) - 11 + 1):
                sub = digits[i : i + 11]
                if self._is_plausible_renavam(sub):
                    return sub
        if 9 <= len(digits) <= 11:
            return digits
        return None

    def _is_plausible_renavam(self, s11: str) -> bool:
        if not (len(s11) == 11 and s11.isdigit()):
            return False
        if len(set(s11)) == 1:
            return False
        if s11.startswith("19") and s11[2:4] in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"):
            return False
        return True

    def _extract_renavam_layout(
        self,
        words: List[Dict[str, Any]],
        lines: List[Dict[str, Any]],
        page_dbg: Dict[str, Any],
    ) -> Optional[str]:
        bboxes: List[Dict[str, int]] = []
        bboxes += self._find_all_label_bboxes(lines, ("RENAVAM",), page_dbg, key="RENAVAM")
        bboxes += self._find_all_label_bboxes(lines, ("CODIGO", "RENAVAM"), page_dbg, key="CODIGO RENAVAM")

        digits: Optional[str] = None
        if bboxes:
            bboxes.sort(key=lambda b: (b["y1"], b["x1"]))
            label = bboxes[0]
            digits = self._digits_near_label(words, label, line_tol=26, below_height=220)

        if digits:
            d = re.sub(r"\D", "", digits)
            cand = self._best_renavam_from_digits(d)
            if cand:
                return cand

        all_txt = " ".join(w["text"] for w in words)
        m11 = self.RE_RENAVAM_11.search(all_txt)
        if m11:
            return m11.group(0)

        all_digits = re.sub(r"\D", "", all_txt)
        return self._best_renavam_from_digits(all_digits)

    def _best_chassi_from_text(self, txt: str) -> Optional[str]:
        s = re.sub(r"[^A-Z0-9]", "", self._normalize(txt))
        if len(s) < 17:
            return None

        best = None
        best_score = -10**18

        for i in range(0, len(s) - 17 + 1):
            sub = s[i : i + 17]
            if not self.RE_CHASSI.fullmatch(sub):
                continue

            digits = sum(1 for c in sub if c.isdigit())
            if digits < 7:
                continue

            alpha_prefix = 0
            for c in sub:
                if c.isalpha():
                    alpha_prefix += 1
                else:
                    break

            score = 0
            score += digits * 3
            if sub[0].isdigit():
                score += 12
            if sub.startswith("9B"):
                score += 10
            if sub[0] == "0":
                score -= 8
            score -= alpha_prefix * 6
            if sub[-1].isdigit():
                score += 3

            if score > best_score:
                best_score = score
                best = sub

        return best

    def _extract_chassi_layout(
        self,
        words: List[Dict[str, Any]],
        lines: List[Dict[str, Any]],
        page_dbg: Dict[str, Any],
    ) -> Optional[str]:
        bboxes: List[Dict[str, int]] = []
        bboxes += self._find_all_label_bboxes(lines, ("CHASSI",), page_dbg, key="CHASSI")
        bboxes += self._find_all_label_bboxes(lines, ("CHASSI/VIN",), page_dbg, key="CHASSI/VIN")

        if bboxes:
            bboxes.sort(key=lambda b: b["y1"])
            label = bboxes[0]
            region = self._alnum_near_label(words, label, line_tol=22, below_height=120, max_chars=180)
            cand = self._best_chassi_from_text(region)
            if cand:
                return cand

        all_txt = " ".join(w["text"] for w in words)
        return self._best_chassi_from_text(all_txt)

    def _extract_year_layout(
        self,
        words: List[Dict[str, Any]],
        lines: List[Dict[str, Any]],
        page_dbg: Dict[str, Any],
        which: str,
    ) -> Optional[str]:
        bboxes: List[Dict[str, int]] = []
        if which == "fab":
            bboxes += self._find_all_label_bboxes(lines, ("ANO", "FAB"), page_dbg, key="ANO FAB")
            bboxes += self._find_all_label_bboxes(lines, ("ANO", "FABRIC"), page_dbg, key="ANO FABRIC")
            bboxes += self._find_all_label_bboxes(lines, ("FABRICACAO",), page_dbg, key="FABRICACAO")
        else:
            bboxes += self._find_all_label_bboxes(lines, ("ANO", "MOD"), page_dbg, key="ANO MOD")
            bboxes += self._find_all_label_bboxes(lines, ("ANO", "MODE"), page_dbg, key="ANO MODE")
            bboxes += self._find_all_label_bboxes(lines, ("MODELO",), page_dbg, key="MODELO")

        if bboxes:
            bboxes.sort(key=lambda b: b["y1"])
            label = bboxes[0]
            t = self._alnum_near_label(words, label, line_tol=22, below_height=140, max_chars=70)
            m = self.RE_ANO.search(self._normalize(t))
            return m.group(0) if m else None

        all_txt = self._normalize(" ".join(w["text"] for w in words))
        m = self.RE_ANO.search(all_txt)
        return m.group(0) if m else None
