import re
from typing import Dict, Any, List


def analyze_extrato(text: str) -> Dict[str, Any]:
    """
    Extrai lançamentos no formato:
    [{"data":"09/07/2024","descricao":"PIX ...","valor":"-2.657,37"}, ...]
    """
    up = (text or "").upper()

    banco = _detect_banco(up)
    lancamentos = _parse_lancamentos(text)

    return {
        "banco_detectado": banco,
        "lancamentos": lancamentos,
        "possui_pix": ("PIX" in up),
        "debug": {"text_len": len(text or ""), "qtd_lancamentos": len(lancamentos)},
    }


def _detect_banco(up: str) -> str | None:
    if "ITAÚ" in up or "ITAU" in up:
        return "Itau"
    if "CAIXA" in up:
        return "Caixa"
    if "BANCO DO BRASIL" in up:
        return "Banco do Brasil"
    if "SANTANDER" in up:
        return "Santander"
    if "BRADESCO" in up:
        return "Bradesco"
    return None


def _parse_lancamentos(text: str) -> List[Dict[str, Any]]:
    lines = [l.rstrip() for l in (text or "").splitlines() if l.strip()]
    out: List[Dict[str, Any]] = []

    # Exemplo típico:
    # 08/07/2024 PIX TRANSF ... -2.657,37
    # 09/07/2024 SALDO DO DIA 0,00
    pat = re.compile(
        r"^\s*(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*$"
    )

    for l in lines:
        m = pat.match(l)
        if not m:
            continue
        data = m.group(1)
        desc = m.group(2).strip()
        val = m.group(3).strip()
        out.append({"data": data, "descricao": desc, "valor": val})

    return out
