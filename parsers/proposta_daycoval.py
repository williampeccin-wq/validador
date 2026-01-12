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
<<<<<<< HEAD
    proposta: Optional[str] = None
=======
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
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
<<<<<<< HEAD
    outras_rendas: Optional[str] = None
=======
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
    valor_parcela: Optional[str] = None
    debug: Dict[str, Any] = field(default_factory=dict)


class PropostaDaycovalParser:
<<<<<<< HEAD
=======
    """
    Parser de Proposta Daycoval a partir do TEXTO extraído.

    Este layout (ex.: andersonsantos.pdf) traz:
      - "Naturalidade: <CIDADE> UF Naturalidade: <UF>"  (não existe "Cidade Nat:")
      - Endereço quebrado em linhas (Endereço + linha seguinte + Nº/Compl em outra)
    """

    # aceita N 35 | Nº 35 | N° 35 | NO 35 | Nº.:35 | Nº:35 | Nº. 35 | N.:35 etc
    _REGEX_NUMERO = re.compile(
        r"\b(?:N|Nº|N°|NO)\s*[\.:]{0,3}\s*([0-9]{1,6})\b",
        flags=re.IGNORECASE,
    )

    # marcadores que aparecem na mesma linha do cabeçalho e servem para "cortar"
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
    _LOJA_CUT_MARKERS = re.compile(
        r"\b(VENDEDOR|DIVERSOS|BANCO|AGENTE|AGENT/OPER|CARTEIRA|TELEFONE|DADOS\s+PESSOAIS|GRUPO\s+CLIENTE)\b\s*:?",
        flags=re.IGNORECASE,
    )

<<<<<<< HEAD
    _VALOR_BR_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")

    def parse_text(self, t: str) -> PropostaDaycovalResult:
        res = PropostaDaycovalResult()
        t = t or ""
        res.debug["text_len"] = len(t)

        def find_first(regex: str, flags=re.IGNORECASE) -> Optional[str]:
            m = re.search(regex, t, flags=flags)
            return _norm_spaces(m.group(1)) if m else None

=======
    def parse_text(self, t: str) -> PropostaDaycovalResult:
        res = PropostaDaycovalResult()
        t = t or ""
        lines = [ln.strip() for ln in t.splitlines() if ln and ln.strip()]
        res.debug["text_len"] = len(t)

        # ----------------------------
        # Helpers
        # ----------------------------
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
        def between(a: str, b: str) -> Optional[str]:
            m = re.search(
                re.escape(a) + r"\s*(.*?)\s*" + re.escape(b),
                t,
                flags=re.IGNORECASE | re.DOTALL,
            )
            return _norm_spaces(m.group(1)) if m else None

<<<<<<< HEAD
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

        # Nome da mãe
        mae = find_first(r"\bFil\.?\s*M[ãa]e\s*:\s*([A-ZÀ-Ü\s]+?)\s+Qtde\b")
        if mae:
            res.nome_mae = _norm_spaces(mae).upper()

        # Endereço: ... Cep:
        end = find_first(
            r"\bEndere[cç]o\s*:\s*(.+?)\s+Cep\s*:",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if end:
            res.endereco = _norm_spaces(end)

        # Número e complemento no endereço
        if res.endereco:
            m_num = re.search(r"\bN[ºo]\.?\s*:\s*(\d+)", res.endereco, flags=re.IGNORECASE)
            if m_num:
                res.numero = m_num.group(1)
            m_comp = re.search(
                r"\bCompl\.?\s*:\s*([A-Z0-9\-\s]+)$",
                res.endereco,
                flags=re.IGNORECASE,
            )
            if m_comp:
                res.complemento = _norm_spaces(m_comp.group(1)).upper()

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

        # Valor parcela (precisa existir no fixture)
        # FIX: não pode depender de between("Vlr. Parcela:", "Taxa Nominal") porque o texto varia.
        # Captura robusta por label (aceita variações e quebras de linha):
        # - Vlr. Parcela / Vlr Parcela
        # - Valor da Parcela
        # - Prestação / Prestacao
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
=======
        def find_first(regex: str, flags=re.IGNORECASE) -> Optional[str]:
            m = re.search(regex, t, flags=flags)
            return _norm_spaces(m.group(1)) if m else None

        # ----------------------------
        # CPF
        # (no seu PDF vem na linha: "Grupo Cliente: ... CPF: 057.750.729-01 Data de Nasc.: ...")
        # ----------------------------
        cpf_raw = find_first(r"\bCPF\s*:\s*([0-9\.\-]{11,14})\b")
        if cpf_raw:
            cpf = _only_digits(cpf_raw)
            res.cpf = cpf if len(cpf) == 11 else None

        # ----------------------------
        # Nome financiado
        # (no seu PDF vem: "DADOS PESSOAIS 1º FINANCIADO:ANDERSON ...")
        # ----------------------------
        nome = find_first(
            r"(?:\b1[ºo]\s*FINANCIADO\b|\bFINANCIADO\b)\s*:?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{8,})"
        )
        if nome:
            nome = re.split(
                r"\b(GRUPO\s+CLIENTE|DADOS\s+PROPOSTA|CPF\s*:|DATA\s+DE\s+NASC|DT\s+NASC|LOJA\s*:)\b",
                nome,
                flags=re.IGNORECASE,
            )[0]
            nome = _norm_spaces(nome)
            res.nome_financiado = nome or None

        if not res.nome_financiado:
            nome2 = between("Nome:", "Loja:")
            if nome2:
                nome2 = re.split(r"\b(CPF\s*:|DT\s+NASC|DADOS\s+PESSOAIS)\b", nome2, flags=re.IGNORECASE)[0]
                res.nome_financiado = _norm_spaces(nome2) or None

        # ----------------------------
        # Loja
        # (no seu PDF vem: "LOJA: 036305 - HACK MULTIM VENDEDOR: ...")
        # ----------------------------
        loja_line = None
        for ln in lines:
            if re.search(r"\bLOJA\b\s*:?", ln, flags=re.IGNORECASE):
                loja_line = ln
                break

        if loja_line:
            m = re.search(r"\bLOJA\b\s*:?\s*(.+)$", loja_line, flags=re.IGNORECASE)
            rest = _norm_spaces(m.group(1)) if m else ""
            parts = self._LOJA_CUT_MARKERS.split(rest, maxsplit=1)
            loja_clean = _norm_spaces(parts[0]) if parts else None
            if loja_clean and len(loja_clean) <= 80:
                res.nome_loja = loja_clean
            else:
                m2 = re.search(
                    r"\bLOJA\b\s*:?\s*([0-9]{3,6}\s*-\s*.+?)\s+\bVENDEDOR\b\s*:",
                    loja_line,
                    flags=re.IGNORECASE,
                )
                if m2:
                    res.nome_loja = _norm_spaces(m2.group(1)) or None

        # ----------------------------
        # Data nascimento
        # (no seu PDF vem: "Data de Nasc.: 12/07/1987")
        # ----------------------------
        res.data_nascimento = (
            find_first(r"\bDt\s*Nasc\s*:\s*(\d{2}/\d{2}/\d{4})\b")
            or find_first(r"\bData\s+de\s+Nasc\.\s*:\s*(\d{2}/\d{2}/\d{4})\b")
        )

        # ----------------------------
        # Cidade nascimento + UF (NATURALIDADE)
        # Seu PDF: "Naturalidade: FLORIANOPOLIS UF Naturalidade: SC"
        # ----------------------------
        cidade_nat = find_first(
            r"\bNaturalidade\s*:\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ ]+?)\s+\bUF\s+Naturalidade\b"
        )
        if not cidade_nat:
            # fallback para layout antigo (se existir)
            cidade_nat = find_first(r"\bCidade\s+Nat\s*:\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{3,})\b")
        res.cidade_nascimento = cidade_nat or None

        uf_raw = find_first(r"\bUF\s+Naturalidade\s*:?\s*([A-Z]{2})\b")
        res.uf = uf_raw.upper() if uf_raw else None

        # ----------------------------
        # Nome mãe
        # ----------------------------
        res.nome_mae = between("Fil.Mãe:", "Qtde Dependentes:")

        # ----------------------------
        # Endereço / Número / Complemento
        # (no seu PDF o endereço está quebrado em 2 linhas e o Nº/Compl em outra)
        # Endereço:SERVIDAO HERMINIO JOSE
        # MONTEIRO
        # Nº.:35 Compl.: AP 101
        # ----------------------------
        end_idx = None
        for i, ln in enumerate(lines):
            if re.search(r"Endere[cç]o\s*:", ln, flags=re.IGNORECASE):
                end_idx = i
                break

        if end_idx is not None:
            # pega 3 linhas (endereço pode quebrar)
            chunk = " ".join(lines[end_idx : min(end_idx + 4, len(lines))])
            # tira o prefixo "Endereço:"
            chunk = re.sub(r"^.*?Endere[cç]o\s*:\s*", "", chunk, flags=re.IGNORECASE).strip()
            chunk = _norm_spaces(chunk)

            # número
            m_num = self._REGEX_NUMERO.search(chunk)
            if m_num:
                n = _norm_spaces(m_num.group(1))
                res.numero = n if (n.isdigit() and len(n) <= 6) else None

            # complemento
            m_comp = re.search(r"Compl\.\s*:\s*(.+?)(?:\s+\bCep\b\s*:|$)", chunk, flags=re.IGNORECASE)
            if m_comp:
                res.complemento = _norm_spaces(m_comp.group(1)) or None

            # endereço: mantém até antes de Compl/Cep
            addr = re.split(r"\bCompl\.\s*:\b", chunk, flags=re.IGNORECASE)[0]
            addr = re.split(r"\bCep\b\s*:", addr, flags=re.IGNORECASE)[0]
            res.endereco = _norm_spaces(addr) or None
        else:
            # fallback amplo
            res.endereco = between("Endereço:", "Compl.:") or between("Endereço:", "Cep:")
            m_num2 = self._REGEX_NUMERO.search(t)
            if m_num2:
                n = _norm_spaces(m_num2.group(1))
                res.numero = n if (n.isdigit() and len(n) <= 6) else None
            res.complemento = between("Compl.:", "Cep:")

        # ----------------------------
        # Restante (como já funcionava)
        # ----------------------------
        res.empresa = between("Empresa:", "C.N.P.J")
        res.data_admissao = between("Data Adm.:", "Cargo")
        res.salario = between("Salário:", "Outras rendas:")
        res.valor_parcela = between("Vlr. Parcela:", "Taxa Nominal")
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f

        return res

    def to_dict(self, result: PropostaDaycovalResult) -> Dict[str, Any]:
        d = asdict(result)
<<<<<<< HEAD
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


__all__ = ["analyze_proposta_daycoval", "PropostaDaycovalParser", "PropostaDaycovalResult"]
=======
        if d.get("debug") is None:
            d["debug"] = {}
        return d


# ============================================================
# WRAPPER PÚBLICO (API ESTÁVEL PARA O app.py)
# ============================================================
def analyze_proposta_daycoval(raw_text: str) -> Dict[str, Any]:
    """
    Função pública esperada pelo app.py.

    Recebe o texto extraído (OCR/native) e devolve um dict serializável.
    """
    parser = PropostaDaycovalParser()
    res = parser.parse_text(raw_text or "")
    return parser.to_dict(res)
>>>>>>> 08ffa31f3ec46c99c271b518ff134ff2edb9a28f
