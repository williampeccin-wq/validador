from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, List, Tuple


def _norm_spaces(txt: str) -> str:
    return re.sub(r"\s+", " ", (txt or "").replace("\u00a0", " ")).strip()


def _upper(txt: str) -> str:
    return _norm_spaces(txt).upper()


_UFS_BR = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}


def _split_cidade_uf(cidade_raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Se "cidade_raw" vier como "FLORIANOPOLIS SC", retorna ("FLORIANOPOLIS", "SC").
    Se não detectar UF válida, retorna (cidade_normalizada, None).
    """
    if not cidade_raw:
        return None, None

    s = _upper(cidade_raw)
    s = _norm_spaces(s)

    # Caso comum: último token é UF
    parts = s.split(" ")
    if len(parts) >= 2 and parts[-1] in _UFS_BR:
        uf = parts[-1]
        cidade = " ".join(parts[:-1]).strip(" -/").strip()
        cidade = _norm_spaces(cidade)
        return (cidade or None), uf

    # Fallback: 'CIDADE - UF' / 'CIDADE/UF'
    m = re.match(r"^(?P<cidade>.+?)\s*[-/ ]\s*(?P<uf>[A-Z]{2})$", s)
    if m:
        uf = m.group("uf")
        if uf in _UFS_BR:
            cidade = _norm_spaces(m.group("cidade").strip(" -/").strip())
            return (cidade or None), uf

    return (s or None), None


def _extract_first_match(text: str, pattern: str, flags=re.IGNORECASE) -> Optional[str]:
    m = re.search(pattern, text or "", flags)
    if not m:
        return None
    if m.lastindex:
        return _norm_spaces(m.group(1))
    return _norm_spaces(m.group(0))


def _date_key(d: str) -> Tuple[int, int, int]:
    # d: dd/mm/yyyy
    try:
        dd, mm, yyyy = d.split("/")
        return (int(yyyy), int(mm), int(dd))
    except Exception:
        return (0, 0, 0)


def _clean_endereco(endereco: str) -> str:
    """
    Remove lixo comum que alguns layouts concatenam ao fim do endereço (ex: "Cliente:6969640").
    Mantém o endereço o mais "humano" possível, sem assumir um layout fixo.
    """
    s = _norm_spaces(endereco)

    # 1) padrão mais típico: "... Cliente:6969640"
    s = re.sub(r"\s+CLIENTE\s*:?\s*\d+\b.*$", "", s, flags=re.IGNORECASE).strip()

    # 2) outros identificadores comuns em contas de consumo
    tail_patterns = [
        r"\s+COD(?:IGO)?\s+CLIENTE\s*:?\s*\d+\b.*$",
        r"\s+N[ºO]?\s*CLIENTE\s*:?\s*\d+\b.*$",
        r"\s+UNIDADE\s+CONSUMIDORA\s*:?\s*\d+\b.*$",
        r"\s+UC\s*:?\s*\d+\b.*$",
        r"\s+INSTAL(?:A[CÇ][AÃ]O)?\s*:?\s*\d+\b.*$",
        r"\s+CONTA\s*:?\s*\d+\b.*$",
        r"\s+CONTRATO\s*:?\s*\d+\b.*$",
    ]
    for pat in tail_patterns:
        s2 = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
        if s2 != s:
            s = s2

    # 3) ruídos genéricos ocasionais
    s = re.split(r"\bNOTA\s+FISCAL\b", s, flags=re.IGNORECASE)[0]
    s = re.split(r"https?://", s, flags=re.IGNORECASE)[0]
    s = _norm_spaces(s)

    return s


@dataclass
class ResidenciaResult:
    nome_titular: Optional[str] = None
    endereco: Optional[str] = None
    cep: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    vencimento: Optional[str] = None
    debug: Dict[str, Any] = None


class ResidenciaParser:
    def parse_text(self, text: str) -> ResidenciaResult:
        t = text or ""
        lines = [ln for ln in (t.splitlines() or []) if _norm_spaces(ln)]
        up = _upper(t)

        cep = _extract_first_match(up, r"\b(\d{5}-?\d{3})\b")
        nome = _extract_first_match(
            t, r"(?:NOME(?:\s+DO\s+CONSUMIDOR)?|NOME\s+DO\s+TITULAR)\s*[:\-]?\s*(.+)"
        )
        endereco = _extract_first_match(t, r"(?:ENDERECO|ENDEREÇO)\s*[:\-]?\s*(.+)")
        cidade = _extract_first_match(t, r"(?:CIDADE)\s*[:\-]?\s*(.+)")

        # 1) labels fortes de vencimento
        venc = (
            _extract_first_match(t, r"(?:DATA\s+DE\s+VENCIMENTO)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})")
            or _extract_first_match(t, r"(?:VENCIMENTO|VENC\.)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})")
            or _extract_first_match(t, r"(?:PAGAR\s+ATE|PAGAR\s+ATÉ)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})")
        )

        # 2) procurar em linhas com "VENC" (e sem "EMIS")
        if not venc:
            for ln in lines:
                u = _upper(ln)
                if "VENC" in u and "EMIS" not in u:
                    m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", ln)
                    if m:
                        venc = m.group(1)
                        break

        # 3) fallback: maior data do doc EXCLUINDO linhas com EMISSÃO
        if not venc:
            dates: List[str] = []
            for ln in lines:
                u = _upper(ln)
                if "EMIS" in u:
                    continue
                dates.extend(re.findall(r"\b\d{2}/\d{2}/\d{4}\b", ln))
            if dates:
                venc = sorted(dates, key=_date_key)[-1]

        # limpeza endereço/cidade
        if endereco:
            endereco = _clean_endereco(endereco)

        uf = None
        if cidade:
            cidade = re.split(r"\bGRUPO\b\s*/", cidade, flags=re.IGNORECASE)[0]
            cidade = re.split(r"https?://", cidade, flags=re.IGNORECASE)[0]
            cidade = _norm_spaces(cidade)
            cidade, uf = _split_cidade_uf(cidade)

        return ResidenciaResult(
            nome_titular=_norm_spaces(nome) if nome else None,
            endereco=endereco if endereco else None,
            cep=cep,
            cidade=cidade if cidade else None,
            uf=uf,
            vencimento=venc,
            debug={"text_len": len(t)},
        )

    def to_dict(self, result: ResidenciaResult) -> Dict[str, Any]:
        d = asdict(result)
        if d.get("debug") is None:
            d["debug"] = {}
        return d


# =====================================================================
# API pública para o app.py
# =====================================================================

def analyze_residencia(raw_text: str) -> Dict[str, Any]:
    """Wrapper estável: retorna dict serializável com campos do comprovante de residência."""
    parser = ResidenciaParser()
    result = parser.parse_text(raw_text or "")
    d = parser.to_dict(result)
    # app não precisa de debug por padrão
    d.pop('debug', None)
    return d
