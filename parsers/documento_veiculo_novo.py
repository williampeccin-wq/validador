# parsers/documento_veiculo_novo.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from parsers.documento_veiculo_base import DocumentoVeiculoBase


class DocumentoVeiculoNovoParser(DocumentoVeiculoBase):
    """
    Parser focado no CRLV-e (modelo novo).

    Estratégia:
      - PDF nativo: prefill via texto nativo (placa/renavam/chassi) + layout por palavras (proprietário).
      - OCR layout: fallback apenas para o que faltar.

    Correção desta versão:
      - Proprietário: quando não existe (ou não é detectável) label PROPRIETARIO/NOME DO PROPRIETARIO,
        usar âncora CPF/CNPJ e capturar nome na linha acima ou imediatamente à esquerda (tanto no PDF nativo
        quanto no OCR).
    """

    OWNER_BLACKLIST_SUBSTR = (
        # genérico/QR/promos
        "VALIDE",
        "CONSULTE",
        "PAGUE",
        "MULTA",
        "MULTAS",
        "INFRAC",
        "DESCONTO",
        "BAIXE",
        "GOV",
        "QR",
        "QRCODE",
        "QR CODE",
        "CARTEIRA",
        "DIGITAL",
        "TRANSIT",
        "SENATRAN",
        "DENATRAN",
        "DETRAN",
        "DEPARTAMENT",
        "MINISTER",
        "REPUBLIC",
        "FEDERAT",
        "BRASIL",
        "CERTIFICAD",
        "LICENCI",
        "REGISTRO",
        "VEICUL",
        "FUNCIONALIDADES",
        "MUITAS",
        "OUTRAS",
        # campos do veículo (comuns no CRLV-e)
        "PASSAGEIRO",
        "AUTOMOVEL",
        "CAMINHONETE",
        "MOTOCICLETA",
        "ONIBUS",
        "CAMINHAO",
        "REBOQUE",
        "SEMIRREBOQUE",
        "CATEGORIA",
        "ESPECIE",
        "TIPO",
        "COMBUSTIVEL",
        "COR",
        "MARCA",
        "MODELO",
        "ANO",
        "POTENCIA",
        "CILINDRADA",
        "CAPACIDADE",
        "CARROCERIA",
        "EIXOS",
    )

    def analyze_layout_ocr(self, file_path: str, documento_hint: Optional[str]) -> Dict[str, Any]:
        import pytesseract  # type: ignore

        out: Dict[str, Any] = {
            "documento": documento_hint or "CRLV",
            "placa": None,
            "renavam": None,
            "chassi": None,
            "ano_fabricacao": None,
            "ano_modelo": None,
            "proprietario": None,
            "debug": {"pages": [], "native_pdf_prefill": {}},
        }

        # 1) Preferência: PDF nativo → prefill
        if file_path.lower().endswith(".pdf"):
            native_prefill = self._prefill_from_native_pdf_layout(file_path)
            out["debug"]["native_pdf_prefill"] = native_prefill

            out["placa"] = native_prefill.get("placa") or out["placa"]
            out["renavam"] = native_prefill.get("renavam") or out["renavam"]
            out["chassi"] = native_prefill.get("chassi") or out["chassi"]
            out["proprietario"] = native_prefill.get("proprietario") or out["proprietario"]

        # 2) OCR layout (fallback/complementação)
        images = self._render_to_images(file_path, dpi=self.ocr_dpi)
        config = "--oem 3 --psm 6"

        for page_idx, img in enumerate(images):
            data = pytesseract.image_to_data(img, lang="por", config=config, output_type=pytesseract.Output.DICT)
            words = self._build_words_from_tesseract(data)
            lines = self._build_lines_from_words(words)
            page_dbg: Dict[str, Any] = {"page": page_idx + 1, "labels_found": {}}

            if not out["placa"]:
                out["placa"] = self._extract_placa(img, words, lines, page_dbg)

            out["renavam"] = out["renavam"] or self._extract_renavam_layout(words, lines, page_dbg)
            out["chassi"] = out["chassi"] or self._extract_chassi_layout(words, lines, page_dbg)

            out["ano_fabricacao"] = out["ano_fabricacao"] or self._coerce_year(
                self._extract_year_layout(words, lines, page_dbg, "fab")
            )
            out["ano_modelo"] = out["ano_modelo"] or self._coerce_year(
                self._extract_year_layout(words, lines, page_dbg, "mod")
            )

            if not out["proprietario"]:
                out["proprietario"] = self._extract_owner(words, lines, page_dbg)

            out["debug"]["pages"].append(page_dbg)

        return self._postprocess_years(out)

    # -------------------------
    # Native PDF prefill por layout (coordenadas)
    # -------------------------

    def _prefill_from_native_pdf_layout(self, file_path: str) -> Dict[str, Optional[str]]:
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return {"placa": None, "renavam": None, "chassi": None, "proprietario": None, "native_len": 0}

        full_text = ""
        proprietario = None

        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        full_text += t + "\n"

                    if not proprietario:
                        proprietario = self._extract_owner_from_pdf_words(page)
        except Exception:
            return {"placa": None, "renavam": None, "chassi": None, "proprietario": None, "native_len": 0}

        norm = self._normalize(full_text)

        return {
            "placa": self._extract_placa_from_text(norm),
            "renavam": self._extract_renavam_from_text(norm),
            "chassi": self._extract_chassi_from_text(norm),
            "proprietario": proprietario,
            "native_len": len(full_text),
        }

    def _extract_owner_from_pdf_words(self, page: Any) -> Optional[str]:
        """
        1) Tenta label direto: "NOME DO PROPRIETARIO" / "PROPRIETARIO" e captura à direita/abaixo.
        2) Fallback robusto: âncora "CPF" / "CPF/CNPJ" e captura nome na linha acima (ou à esquerda).
        """
        try:
            raw_words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
        except Exception:
            return None

        items: List[Dict[str, Any]] = []
        for w in raw_words:
            txt = self._normalize(w.get("text", ""))
            if not txt:
                continue
            items.append(
                {
                    "text": txt,
                    "x0": float(w.get("x0", 0.0)),
                    "x1": float(w.get("x1", 0.0)),
                    "top": float(w.get("top", 0.0)),
                    "bottom": float(w.get("bottom", 0.0)),
                }
            )

        if not items:
            return None

        items.sort(key=lambda d: (d["top"], d["x0"]))

        # agrupa em linhas por top (tolerância)
        lines: List[List[Dict[str, Any]]] = []
        cur: List[Dict[str, Any]] = []
        cur_top: Optional[float] = None
        tol = 3.0

        for it in items:
            if cur_top is None:
                cur = [it]
                cur_top = it["top"]
                continue
            if abs(it["top"] - cur_top) <= tol:
                cur.append(it)
            else:
                cur.sort(key=lambda d: d["x0"])
                lines.append(cur)
                cur = [it]
                cur_top = it["top"]

        if cur:
            cur.sort(key=lambda d: d["x0"])
            lines.append(cur)

        # helper: encontra sequência de tokens exata
        def find_seq(tokens: List[str], seq: List[str]) -> Optional[int]:
            n = len(seq)
            if len(tokens) < n:
                return None
            for i in range(0, len(tokens) - n + 1):
                if tokens[i : i + n] == seq:
                    return i
            return None

        # 1) label direto
        label_variants = [
            ["NOME", "DO", "PROPRIETARIO"],
            ["PROPRIETARIO"],
        ]

        for li, line in enumerate(lines):
            toks = [w["text"] for w in line]
            for lbl in label_variants:
                idx = find_seq(toks, lbl)
                if idx is None:
                    continue

                right_start = idx + len(lbl)
                label_x1 = line[min(right_start - 1, len(line) - 1)]["x1"]
                right_words = [w["text"] for w in line[right_start:] if w["x0"] >= label_x1 - 1]

                cand = self._clean_owner_candidate(" ".join(right_words))
                if cand and self._is_valid_owner(cand):
                    return cand

                # tenta linha abaixo
                if li + 1 < len(lines):
                    below = lines[li + 1]
                    below_text = " ".join(w["text"] for w in below[:7])
                    cand2 = self._clean_owner_candidate(below_text)
                    if cand2 and self._is_valid_owner(cand2):
                        return cand2

        # 2) fallback CPF/CNPJ
        def is_cpf_label(t: str) -> bool:
            t = t.replace(" ", "")
            return t in ("CPF", "CPF/CNPJ", "CPF/CNPJ:", "CPF/CNPJ-", "CNPJ")

        for li, line in enumerate(lines):
            toks = [w["text"] for w in line]
            cpf_idx = None
            for i, tk in enumerate(toks):
                if is_cpf_label(tk):
                    cpf_idx = i
                    break
            if cpf_idx is None:
                continue

            cpf_x0 = line[cpf_idx]["x0"]
            cpf_top = line[cpf_idx]["top"]

            # 2a) nome à esquerda na mesma linha (às vezes "NOME <fulano> CPF ...")
            left_text = " ".join(w["text"] for w in line[:cpf_idx])
            left_text = re.sub(r"\bNOME\b\s*", "", left_text).strip()
            candL = self._clean_owner_candidate(left_text)
            if candL and self._is_valid_owner(candL):
                return candL

            # 2b) nome na linha acima, alinhado na mesma coluna do CPF (muito comum: NOME em cima, CPF embaixo)
            if li - 1 >= 0:
                above = lines[li - 1]
                # pega tokens na linha acima próximos ao x do CPF (ou um pouco à esquerda)
                above_tokens = []
                for w in above:
                    if w["x0"] <= cpf_x0 + 80:  # permite pegar o nome inteiro antes da coluna do CPF
                        above_tokens.append(w["text"])
                above_text = " ".join(above_tokens)
                above_text = re.sub(r"\bNOME\b\s*", "", above_text).strip()

                candA = self._clean_owner_candidate(above_text)
                if candA and self._is_valid_owner(candA):
                    return candA

        return None

    def _extract_placa_from_text(self, norm_text: str) -> Optional[str]:
        m = re.search(r"\bPLACA\b.{0,40}\b([A-Z]{3}\d{4}|[A-Z]{3}\d[A-Z0-9]\d{2})\b", norm_text)
        if m:
            return m.group(1)
        m2 = re.search(r"\b([A-Z]{3}\d{4}|[A-Z]{3}\d[A-Z0-9]\d{2})\b", norm_text)
        return m2.group(1) if m2 else None

    def _extract_renavam_from_text(self, norm_text: str) -> Optional[str]:
        m = re.search(r"\bRENAVAM\b.{0,50}\b(\d{11})\b", norm_text)
        if m:
            return m.group(1)
        m2 = self.RE_RENAVAM_11.search(norm_text)
        return m2.group(0) if m2 else None

    def _extract_chassi_from_text(self, norm_text: str) -> Optional[str]:
        return self._best_chassi_from_text(norm_text)

    # -------------------------
    # PLACA (OCR layout) — mantém como estava
    # -------------------------

    def _extract_placa(
        self,
        img: Any,
        words: List[Dict[str, Any]],
        lines: List[Dict[str, Any]],
        page_dbg: Dict[str, Any],
    ) -> Optional[str]:
        label_bboxes: List[Dict[str, int]] = []
        label_bboxes += self._find_all_label_bboxes(lines, ("PLACA",), page_dbg, key="PLACA")
        label_bboxes += self._find_all_label_bboxes(lines, ("PLACA/UF",), page_dbg, key="PLACA/UF")

        cands: List[Dict[str, Any]] = []
        for ln in lines:
            compact = re.sub(r"[^A-Z0-9]", "", self._normalize(ln["text"]))
            for j in range(0, len(compact) - 7 + 1):
                sub = compact[j : j + 7]
                if self.RE_PLACA.fullmatch(sub):
                    x1, y1, x2, y2 = ln["bbox"]
                    cands.append({"val": sub, "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2})

        for w in words:
            t = re.sub(r"[^A-Z0-9]", "", self._normalize(w["text"]))
            if len(t) == 7 and self.RE_PLACA.fullmatch(t):
                cands.append({"val": t, "cx": w["cx"], "cy": w["cy"]})

        if not cands:
            return None

        uf_words = []
        for w in words:
            t = re.sub(r"[^A-Z]", "", self._normalize(w["text"]))
            if self.RE_UF.fullmatch(t):
                uf_words.append({"cx": w["cx"], "cy": w["cy"]})

        def uf_dist(cx: int, cy: int) -> int:
            best = 10**9
            for u in uf_words:
                dx = abs(u["cx"] - cx)
                dy = abs(u["cy"] - cy)
                if dx <= 350 and dy <= 120:
                    best = min(best, dx + 2 * dy)
            return best

        if label_bboxes:
            lb = sorted(label_bboxes, key=lambda b: (b["y1"], b["x1"]))[0]
            lcy = (lb["y1"] + lb["y2"]) // 2
            lx2 = lb["x2"]

            best_val = None
            best_score = 10**18
            for c in cands:
                cx, cy = c["cx"], c["cy"]
                dx = abs(cx - lx2)
                dy = abs(cy - lcy)
                score = dx + 3 * dy
                score -= max(0, 300 - uf_dist(cx, cy))
                if score < best_score:
                    best_score = score
                    best_val = c["val"]
            return best_val

        cands2 = [c for c in cands if uf_dist(c["cx"], c["cy"]) < 10**9]
        if cands2:
            cands2.sort(key=lambda c: uf_dist(c["cx"], c["cy"]))
            return cands2[0]["val"]

        return cands[0]["val"]

    # -------------------------
    # OWNER (OCR) — label direto ou fallback CPF
    # -------------------------

    def _extract_owner(self, words: List[Dict[str, Any]], lines: List[Dict[str, Any]], page_dbg: Dict[str, Any]) -> Optional[str]:
        # 1) tenta label direto
        bboxes = []
        bboxes += self._find_all_label_bboxes(lines, ("PROPRIETARIO",), page_dbg, key="PROPRIETARIO")
        bboxes += self._find_all_label_bboxes(lines, ("NOME", "DO", "PROPRIETARIO"), page_dbg, key="NOME DO PROPRIETARIO")

        if bboxes:
            lb = sorted(bboxes, key=lambda b: (b["y1"], b["x1"]))[0]
            ly2 = lb["y2"]

            region_lines: List[str] = []
            for ln in lines:
                x1, y1, x2, y2 = ln["bbox"]
                if y1 >= ly2 - 10 and y1 <= ly2 + 280:
                    region_lines.append(ln["text"])

            best = None
            best_score = -10**18
            for raw in region_lines:
                cand = self._clean_owner_candidate(raw)
                if not cand:
                    continue
                if not self._is_valid_owner(cand):
                    continue
                sc = self._owner_score(cand)
                if sc > best_score:
                    best_score = sc
                    best = cand
            if best:
                return best

        # 2) fallback: âncora CPF/CNPJ no OCR e nome na linha acima
        cpf_bboxes = []
        cpf_bboxes += self._find_all_label_bboxes(lines, ("CPF",), page_dbg, key="CPF")
        cpf_bboxes += self._find_all_label_bboxes(lines, ("CPF/CNPJ",), page_dbg, key="CPF/CNPJ")
        cpf_bboxes += self._find_all_label_bboxes(lines, ("CNPJ",), page_dbg, key="CNPJ")

        if not cpf_bboxes:
            return None

        cb = sorted(cpf_bboxes, key=lambda b: (b["y1"], b["x1"]))[0]
        cy1 = cb["y1"]

        # procura linhas imediatamente acima
        above_lines: List[str] = []
        for ln in lines:
            x1, y1, x2, y2 = ln["bbox"]
            # "acima" e próximo verticalmente
            if y2 <= cy1 and (cy1 - y2) <= 120:
                above_lines.append(ln["text"])

        # tenta as mais próximas (últimas)
        for raw in reversed(above_lines[-6:]):
            raw_norm = self._normalize(raw)
            # remove label "NOME" se existir
            raw_norm = re.sub(r"\bNOME\b\s*", "", raw_norm).strip()
            cand = self._clean_owner_candidate(raw_norm)
            if cand and self._is_valid_owner(cand):
                return cand

        return None

    def _clean_owner_candidate(self, raw: str) -> Optional[str]:
        t = self._normalize(raw)
        t = self.RE_CPF.sub(" ", t)

        m = re.search(r"\d", t)
        if m:
            t = t[: m.start()]

        t = re.sub(r"[^A-Z ]", " ", t)
        t = re.sub(r"\s{2,}", " ", t).strip()

        if len(t) < 6:
            return None

        for bad in self.OWNER_BLACKLIST_SUBSTR:
            if bad in t:
                return None

        return t

    def _is_valid_owner(self, t: str) -> bool:
        words = t.split()
        if len(words) < 2 or len(words) > 5:
            return False
        if any(len(w) <= 1 for w in words):
            return False
        if not all(w.isalpha() for w in words):
            return False
        for bad in self.OWNER_BLACKLIST_SUBSTR:
            if bad in t:
                return False
        return True

    def _owner_score(self, t: str) -> int:
        words = t.split()
        letters = sum(1 for c in t if "A" <= c <= "Z")

        bonus = 0
        if len(words) == 2:
            bonus += 28
        elif len(words) == 3:
            bonus += 34
        elif len(words) == 4:
            bonus += 22
        elif len(words) == 5:
            bonus -= 8

        bonus -= max(0, len(t) - 26)
        return letters + bonus
