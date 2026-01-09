from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from parsers.documento_veiculo_base import DocumentoVeiculoBase, DocumentoVeiculoResult, FonteExtracao


class DocumentoVeiculoNovoParser(DocumentoVeiculoBase):
    """
    CRLV-e novo.
    Requisito de testes:
      - método analyze_layout_ocr(file_path, documento_hint) -> dict
      - método analyze(file_path) -> DocumentoVeiculoResult
    """

    def analyze_layout_ocr(self, file_path: str, documento_hint: Optional[str]) -> Dict[str, Any]:
        raw_text, fonte, dbg = self._extract_text_hybrid(file_path)
        norm = self._normalize(raw_text)

        placa = self._extract_placa_robust(norm)
        renavam = self._extract_renavam_robust(norm)
        chassi = self._extract_chassi_robust(norm)
        ano_fabricacao, ano_modelo, years_snippet = self._extract_years(norm)
        proprietario = self._extract_owner_simple(norm)

        return {
            "documento": documento_hint or "CRLV",
            "placa": placa,
            "renavam": renavam,
            "chassi": chassi,
            "ano_fabricacao": ano_fabricacao,
            "ano_modelo": ano_modelo,
            "proprietario": proprietario,
            "debug": {
                "extract": dbg,
                "years_snippet": years_snippet,
                "fonte": {
                    "mode": fonte.mode,
                    "native_text_len": fonte.native_text_len,
                    "ocr_text_len": fonte.ocr_text_len,
                    "pages": fonte.pages,
                },
            },
        }

    def analyze(self, file_path: str) -> DocumentoVeiculoResult:
        legacy = self.analyze_layout_ocr(file_path, documento_hint="CRLV")
        fonte_dict = (legacy.get("debug") or {}).get("fonte") or {}

        fonte = FonteExtracao(
            mode=str(fonte_dict.get("mode") or "native"),
            native_text_len=int(fonte_dict.get("native_text_len") or 0),
            ocr_text_len=int(fonte_dict.get("ocr_text_len") or 0),
            pages=list(fonte_dict.get("pages") or []),
        )

        return DocumentoVeiculoResult(
            documento=legacy.get("documento"),
            placa=legacy.get("placa"),
            renavam=legacy.get("renavam"),
            chassi=legacy.get("chassi"),
            ano_fabricacao=legacy.get("ano_fabricacao"),
            ano_modelo=legacy.get("ano_modelo"),
            proprietario=legacy.get("proprietario"),
            fonte=fonte,
            debug=legacy.get("debug") or {},
        )

    # ---------------------------
    # Extratores robustos
    # ---------------------------
    @staticmethod
    def _extract_placa_robust(norm: str) -> Optional[str]:
        m = re.search(r"\b([A-Z]{3}\d[A-Z0-9]\d{2}|[A-Z]{3}\d{4})\b", norm or "")
        return m.group(1) if m else None

    @staticmethod
    def _extract_renavam_robust(norm: str) -> Optional[str]:
        # RENAVAM geralmente 9-11 dígitos; seu golden é 11.
        m = re.search(r"\b(\d{9,11})\b", norm or "")
        return m.group(1) if m else None

    @staticmethod
    def _extract_chassi_robust(norm: str) -> Optional[str]:
        m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", norm or "")
        return m.group(1) if m else None

    @staticmethod
    def _extract_years(norm: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
        """
        Estratégia (ordem):
          1) Procurar explicitamente "ANO ... FAB ... MODELO" e extrair 2 anos no trecho.
          2) Procurar uma *janela* de texto ao redor de âncoras (ANO/FAB/MOD) e extrair anos só dessa janela.
          3) Procurar padrões compactos "FAB/MOD 2009/2009" com variações de separadores.
          4) Fallback global (último recurso): primeiros 2 anos distintos do documento.
        """
        s = norm or ""

        # Helper: extrai anos de um trecho pequeno, preservando a ordem de aparição
        def years_in(text: str) -> list[int]:
            ys = [int(x) for x in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
            ys = [y for y in ys if 1900 <= y <= 2100]
            return ys

        # 1) "ANO FABRICACAO/MODELO: 2009/2009" com tolerância alta a espaços e separadores
        m = re.search(
            r"ANO\s*(?:FAB(?:RICACAO)?|FABRICA[ÇC]AO)?\s*/?\s*MODELO\s*[:\-]?\s*(19\d{2}|20\d{2})\s*[/\-\s]\s*(19\d{2}|20\d{2})",
            s,
        )
        if m:
            snippet = m.group(0)
            return int(m.group(1)), int(m.group(2)), snippet

        # 2) Janela ancorada: encontre a palavra ANO e FAB/MOD próximo e recorte um trecho curto
        #    (isso resolve OCR quebrando linhas, removendo '/', etc.)
        anchor = re.search(r"\bANO\b.{0,80}\b(FAB|FABRICACAO|FABRICA[ÇC]AO)\b.{0,120}\b(MOD|MODELO)\b", s)
        if anchor:
            start = max(0, anchor.start() - 40)
            end = min(len(s), anchor.end() + 80)
            window = s[start:end]
            ys = years_in(window)
            # Remova duplicatas preservando ordem
            dedup: list[int] = []
            for y in ys:
                if y not in dedup:
                    dedup.append(y)

            if len(dedup) >= 2:
                return dedup[0], dedup[1], window
            if len(dedup) == 1:
                return dedup[0], dedup[0], window

            return None, None, window

        # 3) Padrões compactos alternativos (ex.: "ANO FAB MOD: 2009 2009" ou "ANO FAB/MOD 2009/2009")
        m2 = re.search(
            r"\b(?:ANO\s*)?(?:FAB|FABRICACAO|FABRICA[ÇC]AO)\s*(?:/|\s)?\s*(?:MOD|MODELO)\s*[:\-]?\s*(19\d{2}|20\d{2})\s*(?:/|\-|\s)\s*(19\d{2}|20\d{2})\b",
            s,
        )
        if m2:
            snippet = m2.group(0)
            return int(m2.group(1)), int(m2.group(2)), snippet

        # 4) Fallback global (último recurso) — pode puxar “2017” de outra seção, por isso é o último
        ys_all = years_in(s)
        dedup_all: list[int] = []
        for y in ys_all:
            if y not in dedup_all:
                dedup_all.append(y)

        if len(dedup_all) >= 2:
            return dedup_all[0], dedup_all[1], None
        if len(dedup_all) == 1:
            return dedup_all[0], dedup_all[0], None
        return None, None, None

    @staticmethod
    def _extract_owner_simple(norm: str) -> Optional[str]:
        # Heurística simples por âncoras comuns
        m = re.search(r"\bNOME\b\s+([A-Z ]{5,})\s+\bCPF\b", norm or "")
        if m:
            cand = re.sub(r"\s{2,}", " ", m.group(1).strip())
            return cand
        return None
