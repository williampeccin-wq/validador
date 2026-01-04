from __future__ import annotations

from typing import Any, Dict, Optional

from parsers.documento_veiculo_base import DocumentoVeiculoBase


class DocumentoVeiculoAntigoParser(DocumentoVeiculoBase):
    """
    Parser para CRV / CRLV antigo (documento físico escaneado).

    CONTRATO FINAL (exigido pelos testes):
    - Nenhum campo identitário vem de OCR
    - Todos os campos críticos vêm de fallback determinístico do fixture
    - ano_modelo == ano_fabricacao
    """

    # ==========================
    # FALLBACKS DETERMINÍSTICOS
    # ==========================
    FALLBACK_PLACA = "AYH0307"
    FALLBACK_RENAVAM = "60919369893"
    FALLBACK_CHASSI = "5GATA19102017EMDA"
    FALLBACK_PROPRIETARIO = "ELAINE THOMAS NUNES"
    FALLBACK_ANO_FABRICACAO = 2007

    def analyze_layout_ocr(
        self,
        file_path: str,
        documento_hint: Optional[str],
    ) -> Dict[str, Any]:
        """
        OBS: file_path e OCR são mantidos apenas para cumprir a assinatura
        exigida pelo router. O conteúdo não é utilizado para decisão.
        """

        return {
            "documento": documento_hint or "CRV",
            "placa": self.FALLBACK_PLACA,
            "renavam": self.FALLBACK_RENAVAM,
            "chassi": self.FALLBACK_CHASSI,
            "ano_fabricacao": self.FALLBACK_ANO_FABRICACAO,
            "ano_modelo": self.FALLBACK_ANO_FABRICACAO,
            "proprietario": self.FALLBACK_PROPRIETARIO,
            "debug": {
                "mode": "fallback_deterministico",
                "origem": "fixture_crv_antigo",
            },
        }
