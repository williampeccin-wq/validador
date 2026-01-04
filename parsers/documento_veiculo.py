# parsers/documento_veiculo.py
from __future__ import annotations

from typing import Any, Dict, Optional

from parsers.documento_veiculo_base import DocumentoVeiculoBase, DocumentoVeiculoResult, FonteExtracao
from parsers.documento_veiculo_novo import DocumentoVeiculoNovoParser
from parsers.documento_veiculo_antigo import DocumentoVeiculoAntigoParser


class DocumentoVeiculoParser(DocumentoVeiculoBase):
    """
    Fachada estável (API do app):
      - decide qual parser usar (novo vs antigo)
      - compõe resultado final no mesmo formato de antes
    """

    def analyze(self, file_path: str) -> DocumentoVeiculoResult:
        raw_text, fonte = self._extract_text_hybrid(file_path)
        txt = self._normalize(raw_text)
        doc_hint = self._infer_doc_type(txt)

        debug: Dict[str, Any] = {"doc_type_signals": self._doc_type_signals(txt), "chosen_parser": None, "parser_debug": {}}

        # Heurística de roteamento:
        # - se tem sinais claros de CRLV-e moderno, manda para "novo"
        # - caso contrário, "antigo"
        signals = debug["doc_type_signals"]
        is_moderno = bool(signals.get("crlve_hits")) or ("CARTEIRA DIGITAL" in txt) or ("ASSINADO DIGITALMENTE" in txt)

        if is_moderno:
            parser = DocumentoVeiculoNovoParser(min_text_len_threshold=self.min_text_len_threshold, ocr_dpi=self.ocr_dpi)
            debug["chosen_parser"] = "novo"
        else:
            parser = DocumentoVeiculoAntigoParser(min_text_len_threshold=self.min_text_len_threshold, ocr_dpi=self.ocr_dpi)
            debug["chosen_parser"] = "antigo"

        # roda OCR layout (mesmo se fonte=native, porque os campos são posicionais)
        out = parser.analyze_layout_ocr(file_path, documento_hint=doc_hint)

        debug["parser_debug"] = out.get("debug", {})

        return DocumentoVeiculoResult(
            documento=out.get("documento") or doc_hint,
            placa=out.get("placa"),
            renavam=out.get("renavam"),
            chassi=out.get("chassi"),
            ano_fabricacao=out.get("ano_fabricacao"),
            ano_modelo=out.get("ano_modelo"),
            proprietario=out.get("proprietario"),
            fonte=fonte,
            debug=debug,
        )


__all__ = ["DocumentoVeiculoParser", "DocumentoVeiculoResult", "FonteExtracao"]
