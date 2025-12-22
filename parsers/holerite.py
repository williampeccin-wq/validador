import re
from typing import Dict, Any


def analyze_holerite(text: str) -> Dict[str, Any]:
    up = (text or "").upper()

    empregador = _find_empregador(text)
    nome = _find_nome_funcionario(text)
    data_admissao = _find_data_admissao(text)
    total_vencimentos = _find_total_vencimentos(text)

    return {
        "nome": nome,
        "empregador": empregador,
        "data_admissao": data_admissao,
        "total_vencimentos": total_vencimentos,
        "debug": {"text_len": len(text or "")},
    }


def _find_empregador(text: str) -> str | None:
    # normalmente o empregador está na primeira linha
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return None
    # pega a primeira linha “forte” antes de “Recibo de Pagamento...”
    for l in lines[:5]:
        if "RECIBO DE PAGAMENTO" in l.upper():
            continue
        if len(l) >= 10:
            return l
    return lines[0]


def _find_nome_funcionario(text: str) -> str | None:
    # tenta após rótulos
    m = re.search(r"NOME DO FUNCION[ÁA]RIO\s+([A-Z\s]+)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # fallback: procura linha com CBO e cargo, e pega a linha seguinte grande
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if "NOME DO FUNCION" in l.upper() and i + 1 < len(lines):
            return lines[i + 1].strip()

    # fallback: maior linha toda caps
    caps = [l for l in lines if re.fullmatch(r"[A-Z\s]+", l) and len(l) >= 10]
    if caps:
        return max(caps, key=len)
    return None


def _find_data_admissao(text: str) -> str | None:
    m = re.search(r"\bADM\.?\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})\b", text, flags=re.IGNORECASE)
    return m.group(1) if m else None


def _find_total_vencimentos(text: str) -> str | None:
    # padrão: "Total de Vencimentos 2.500,00"
    m = re.search(r"TOTAL\s+DE\s+VENCIMENTOS\s*([0-9\.\,]+)", text, flags=re.IGNORECASE)
    if m:
        return _norm_money(m.group(1))

    # fallback: "Vencimentos" e valor grande perto do final
    m = re.search(r"\bVENCIMENTOS\b.*?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return _norm_money(m.group(1))

    return None


def _norm_money(s: str) -> str:
    s = (s or "").strip()
    # mantém 1.234,56
    return s
