# parsers/proposta_daycoval.py

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


@dataclass
class PropostaDaycovalResult:
    proposta: Optional[str] = None
    nome_financiado: Optional[str] = None
    nome_loja: Optional[str] = None
    cpf: Optional[str] = None
    data_nascimento: Optional[str] = None
    cidade_nascimento: Optional[str] = None
    uf: Optional[str] = None
    nome_mae: Optional[str] = None
    endereco: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    empresa: Optional[str] = None
    data_admissao: Optional[str] = None
    salario: Optional[str] = None
    outras_rendas: Optional[str] = None
    valor_parcela: Optional[str] = None

    # NOVO: Vlr. Compra (valor FIPE do carro no momento da proposta)
    valor_compra: Optional[str] = None

    debug: Dict[str, Any] = field(default_factory=dict)


class PropostaDaycovalParser:
    _LOJA_CUT_MARKERS = re.compile(
        r"\b(VENDEDOR|DIVERSOS|BANCO|AGENTE|AGENT/OPER|CARTEIRA|TELEFONE|DADOS\s+PESSOAIS|GRUPO\s+CLIENTE)\b\s*:?",
        flags=re.IGNORECASE,
    )

    _VALOR_BR_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")

    # Endereço: separadores típicos de número / complemento (tolerante a "Nº.:35", "Nº:35", "Nº . : 35", etc.)
    _END_NUM_SPLIT_RE = re.compile(
        r"(?is)\bN[ºo]\s*\.?\s*(?:\.\s*)?:?\s*(?:\d{1,6})\b"
    )
    _END_COMP_LABEL_RE = re.compile(r"(?is)\bCompl\.?\s*:")

    # Mãe: captura tolerante a quebra de linha e sobrenome na linha seguinte
    _MAE_RE = re.compile(
        r"(?is)\bFil\.?\s*M[ãa]e\s*:\s*(?P<nome>.+?)\s+(?=Qtde\b)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def parse_text(self, t: str) -> PropostaDaycovalResult:
        res = PropostaDaycovalResult()
        t = t or ""
        res.debug["text_len"] = len(t)

        def find_first(regex: str, flags=re.IGNORECASE) -> Optional[str]:
            m = re.search(regex, t, flags=flags)
            return _norm_spaces(m.group(1)) if m else None

        def between(a: str, b: str) -> Optional[str]:
            m = re.search(
                re.escape(a) + r"\s*(.*?)\s*" + re.escape(b),
                t,
                flags=re.IGNORECASE | re.DOTALL,
            )
            return _norm_spaces(m.group(1)) if m else None

        # Proposta
        m_prop = re.search(r"\bProposta\s*:\s*(\d{4,})\b", t, flags=re.IGNORECASE)
        if m_prop:
            res.proposta = _only_digits(m_prop.group(1))

        # Nome + CPF (FINANCIADO)
        m_fin = re.search(
            r"\bFINANCIADO\s*:\s*([A-ZÀ-Ü\s]+?)\s*\(([\d\.\-]+)\w?\)",
            t,
            flags=re.IGNORECASE,
        )
        if m_fin:
            res.nome_financiado = _norm_spaces(m_fin.group(1)).upper()
            res.cpf = _only_digits(m_fin.group(2))

        # LOJA
        m_loja = re.search(r"\bLOJA\s*:\s*(.+)", t, flags=re.IGNORECASE)
        if m_loja:
            loja_line = _norm_spaces(m_loja.group(1))
            loja_line = re.split(self._LOJA_CUT_MARKERS, loja_line, maxsplit=1)[0]
            res.nome_loja = _norm_spaces(loja_line).upper()

        # CPF (fallback)
        if not res.cpf:
            cpf = find_first(r"\bCPF\s*:\s*([\d\.\-]{11,})")
            if cpf:
                res.cpf = _only_digits(cpf)

        # Nascimento
        nasc = find_first(r"\bData\s+de\s+Nasc\.?\s*:\s*(\d{2}/\d{2}/\d{4})")
        if nasc:
            res.data_nascimento = nasc

        # Naturalidade: <CIDADE> UF Naturalidade: <UF>
        m_nat = re.search(
            r"\bNaturalidade\s*:\s*([A-ZÀ-Ü\s]+?)\s+UF\s+Naturalidade\s*:\s*([A-Z]{2})",
            t,
            flags=re.IGNORECASE,
        )
        if m_nat:
            res.cidade_nascimento = _norm_spaces(m_nat.group(1)).upper()
            res.uf = _norm_spaces(m_nat.group(2)).upper()

        # Nome da mãe (robusto para multiline)
        m_mae = self._MAE_RE.search(t)
        if m_mae:
            mae = _norm_spaces(m_mae.group("nome"))
            if mae:
                res.nome_mae = mae.upper()

        # Endereço: ... Cep:
        end = find_first(
            r"\bEndere[cç]o\s*:\s*(.+?)\s+Cep\s*:",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if end:
            res.endereco = _norm_spaces(end)

        # Número e complemento no endereço
        if res.endereco:
            # Número (tolerante a "Nº.:35")
            m_num = re.search(
                r"(?is)\bN[ºo]\s*\.?\s*(?:\.\s*)?:?\s*(\d{1,6})\b",
                res.endereco,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if m_num:
                res.numero = m_num.group(1)

            # Complemento (mantém comportamento atual, mas tolera espaços)
            m_comp = re.search(
                r"(?is)\bCompl\.?\s*:\s*([A-Z0-9\-\s]+)$",
                res.endereco,
                flags=re.IGNORECASE,
            )
            if m_comp:
                res.complemento = _norm_spaces(m_comp.group(1)).upper()

            # FIX: endereco deve ser SOMENTE logradouro (sem Nº / Compl)
            cleaned = res.endereco

            # Corta primeiro pelo marcador de número, se existir
            if self._END_NUM_SPLIT_RE.search(cleaned):
                cleaned = self._END_NUM_SPLIT_RE.split(cleaned, maxsplit=1)[0]
            else:
                # Sem número, mas pode haver "Compl.:"
                if self._END_COMP_LABEL_RE.search(cleaned):
                    cleaned = self._END_COMP_LABEL_RE.split(cleaned, maxsplit=1)[0]

            cleaned = _norm_spaces(cleaned)
            if cleaned:
                res.endereco = cleaned
            else:
                # se por algum motivo ficar vazio, mantém o valor original
                res.endereco = _norm_spaces(res.endereco)

        # Atividade profissional
        res.empresa = between("Empresa:", "C.N.P.J")
        res.data_admissao = between("Data Adm.:", "Cargo")

        # Salário
        res.salario = between("Salário:", "Outras Rendas:")

        # Outras Rendas
        outras = find_first(r"\bOutras\s+Rendas\s*:\s*(" + self._VALOR_BR_RE.pattern + r")\b")
        if outras:
            res.outras_rendas = outras
        else:
            outras_fb = between("Outras Rendas:", "Vlr. Parcela:")
            if outras_fb:
                m_val = re.search(self._VALOR_BR_RE, outras_fb)
                res.outras_rendas = m_val.group(0) if m_val else None

        # Valor parcela (financiamento) - obrigatório no seu contrato
        m_parcela = re.search(
            r"\b(?:Vlr\.?|Valor)\s*(?:da\s*)?(?:Parcela|Prest(?:a[cç][aã]o)?|Presta[cç][aã]o)\b\s*[:\-]?\s*(?:R\$\s*)?("
            + self._VALOR_BR_RE.pattern
            + r")\b",
            t,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_parcela:
            res.valor_parcela = _norm_spaces(m_parcela.group(1))
        else:
            # fallback: tenta capturar 'Parcela' próximo do valor (evita pegar salário/outras rendas)
            m_parcela2 = re.search(
                r"\bParcela\b[^\d\n]{0,40}(?:R\$\s*)?(" + self._VALOR_BR_RE.pattern + r")\b",
                t,
                flags=re.IGNORECASE,
            )
            res.valor_parcela = _norm_spaces(m_parcela2.group(1)) if m_parcela2 else None

        # NOVO: Valor compra (FIPE) - label "Vlr. Compra"
        m_compra = re.search(
            r"\bVlr\.?\s*Compra\b\s*[:\-]?\s*(?:R\$\s*)?(" + self._VALOR_BR_RE.pattern + r")\b",
            t,
            flags=re.IGNORECASE | re.DOTALL,
        )
        res.valor_compra = _norm_spaces(m_compra.group(1)) if m_compra else None

        return res

    def to_dict(self, result: PropostaDaycovalResult) -> Dict[str, Any]:
        d = asdict(result)
        d["debug"] = d.get("debug") or {}
        return d


def analyze_proposta_daycoval(
    raw_text: str,
    filename: Optional[str] = None,
    return_debug: bool = False,
):
    """
    API pública estável para o app e para testes.

    - return_debug=False -> retorna dict(fields) (com debug embutido)
    - return_debug=True  -> retorna (fields_sem_debug, debug)
    """
    _ = filename  # reservado para rastreabilidade futura
    parser = PropostaDaycovalParser()
    res = parser.parse_text(raw_text or "")
    fields = parser.to_dict(res)

    if return_debug:
        dbg = fields.pop("debug", {}) if isinstance(fields, dict) else {}
        return fields, dbg

    return fields
