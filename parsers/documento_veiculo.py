from __future__ import annotations

from parsers.documento_veiculo_base import DocumentoVeiculoResult
from parsers.documento_veiculo_antigo import DocumentoVeiculoAntigoParser
from parsers.documento_veiculo_novo import DocumentoVeiculoNovoParser


class DocumentoVeiculoParser:
    def __init__(self, min_text_len_threshold: int = 800, ocr_dpi: int = 300) -> None:
        self.min_text_len_threshold = min_text_len_threshold
        self.ocr_dpi = ocr_dpi

    def analyze(self, file_path: str) -> DocumentoVeiculoResult:
        novo = DocumentoVeiculoNovoParser(
            min_text_len_threshold=self.min_text_len_threshold,
            ocr_dpi=self.ocr_dpi,
        )

        # tentativa 1: API moderna
        if hasattr(novo, "analyze"):
            try:
                res_novo = novo.analyze(file_path)
                if res_novo.placa or res_novo.renavam or res_novo.chassi:
                    return res_novo
            except Exception:
                pass

        # tentativa 2: API legada (dict) -> converte
        try:
            out = novo.analyze_layout_ocr(file_path, documento_hint="CRLV")
            from parsers.documento_veiculo_base import FonteExtracao

            fonte_dict = (out.get("debug") or {}).get("fonte") or {}
            fonte = FonteExtracao(
                mode=str(fonte_dict.get("mode") or "native"),
                native_text_len=int(fonte_dict.get("native_text_len") or 0),
                ocr_text_len=int(fonte_dict.get("ocr_text_len") or 0),
                pages=list(fonte_dict.get("pages") or []),
            )
            return DocumentoVeiculoResult(
                documento=out.get("documento"),
                placa=out.get("placa"),
                renavam=out.get("renavam"),
                chassi=out.get("chassi"),
                ano_fabricacao=out.get("ano_fabricacao"),
                ano_modelo=out.get("ano_modelo"),
                proprietario=out.get("proprietario"),
                fonte=fonte,
                debug=out.get("debug") or {},
            )
        except Exception:
            pass

        # fallback: parser antigo
        antigo = DocumentoVeiculoAntigoParser(
            min_text_len_threshold=self.min_text_len_threshold,
            ocr_dpi=self.ocr_dpi,
        )
        return antigo.analyze(file_path)
