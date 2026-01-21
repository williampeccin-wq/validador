from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _upper(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    out = _norm_spaces(s).upper()
    return out if out else None


def _between(text: str, start_label: str, end_label: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(
        re.escape(start_label) + r"\s*(.*?)\s*" + re.escape(end_label),
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    out = _norm_spaces(m.group(1))
    return out if out else None


def _extract_first(text: str, pattern: str, flags: int = re.IGNORECASE | re.DOTALL) -> Optional[str]:
    if not text:
        return None
    m = re.search(pattern, text, flags=flags)
    if not m:
        return None
    out = _norm_spaces(m.group(1))
    return out if out else None


def _split_endereco(endereco_raw: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Split address into (logradouro, numero, complemento).

    Inputs often look like:
      - 'RUA X Nº.:530 Compl.: CASA'
      - 'SERVIDAO Y N°:35 Compl.: AP 101'
      - '... Compl.:' (blank complemento)

    Contract we want:
      - endereco = logradouro only (without Nº/Compl fragments)
      - numero = digits (str) or None
      - complemento = cleaned text or None
    """
    if not endereco_raw:
        return None, None, None

    raw = _norm_spaces(endereco_raw)

    # Normalize common variants (keep the user's original content otherwise).
    raw = (
        raw.replace("Nº.", "N°")
        .replace("Nº:", "N°:")
        .replace("Nº", "N°")
        .replace("No.", "N°")
        .replace("N.o", "N°")
    )
    up = raw.upper()

    complemento: Optional[str] = None

    # 1) Pull complemento if it is explicitly labeled (Compl./Complemento), tolerant to missing spaces.
    m_comp = re.search(r"\bCOMPL(?:EMENTO)?\.?\s*:?\s*(?P<comp>.*)\s*$", up, flags=re.IGNORECASE)
    if m_comp:
        comp_raw = m_comp.group("comp") or ""
        comp_out = _norm_spaces(comp_raw).upper()
        if comp_out in ("", "<NONE>", "NONE"):
            complemento = None
        else:
            complemento = comp_out
        # Remove complemento segment from the address string before extracting the number.
        up = _norm_spaces(up[: m_comp.start()].rstrip(" ,;-"))

    # 2) Extract numero (supports "N°.:530", "Nº: 530", "NUMERO 530", etc.)
    num_pattern = r"\b(?:N[°ºO]|N[°º]|NRO|NÚMERO|NUMERO|NÚM|NUM)\s*\.?\s*:?\s*(?P<num>\d{1,6})\b"
    m_num = re.search(num_pattern, up, flags=re.IGNORECASE)
    if m_num:
        num = _norm_spaces(m_num.group("num")) or None
        log_raw = _norm_spaces(up[: m_num.start()].rstrip(" ,;-"))
        log = log_raw.upper() if log_raw else None
        return log, num, complemento

    # 3) Fallback: LOGRADOURO N°:123 (no complemento)
    m2 = re.search(
        r"^(?P<log>.+?)\s*(?:N[°ºO]|N[°º]|NRO|NÚMERO|NUMERO|NÚM|NUM)\s*\.?\s*:?\s*(?P<num>\d{1,6})\s*$",
        up,
        flags=re.IGNORECASE,
    )
    if m2:
        log = _norm_spaces(m2.group("log")).upper() or None
        num = _norm_spaces(m2.group("num")) or None
        return log, num, complemento

    # 4) Very last fallback: if it ends with digits (no explicit N°/Número marker), split cautiously.
    m3 = re.search(r"^(?P<log>.+?)\s*[,\-]?\s*(?P<num>\d{1,6})\s*$", up, flags=re.IGNORECASE)
    if m3:
        log_candidate = _norm_spaces(m3.group("log"))
        # Avoid false positives (e.g., short strings / non-address).
        if len(re.sub(r"[^A-ZÀ-Ü]", "", log_candidate.upper())) >= 5:
            log = log_candidate.upper() or None
            num = _norm_spaces(m3.group("num")) or None
            return log, num, complemento

    # If we couldn't split, keep everything as logradouro.
    return _upper(raw), None, complemento


def _extract_nome_mae_multiline(text: str) -> Optional[str]:
    """Extract 'Fil. Mãe' robustly, supporting wrapped surnames on the next line.

    Observed extracted-text layout:
      - 'Fil. Pai: ... Fil.Mãe: FRANCISCA ACIZA DANTAS'
        'LIMA'
        'Qtde Dependentes: ...'

    Strategy:
      1) find a line that contains FIL + MÃE/MAE and a ':' marker
      2) extract the substring after the MÃE/MAE label (preferred) or after the last ':'
      3) append subsequent lines that look like a continuation of a person's name
      4) stop on section labels (Qtde Dependentes, Endereço, Bairro, CEP, etc.)
    """
    if not text:
        return None

    def _is_section_label(line_up: str) -> bool:
        return bool(re.search(r"\bQTDE\b|\bDEPENDENT\w*\b|\bENDERE[CÇ]O\b|\bBAIRRO\b|\bCEP\b", line_up))

    def _looks_like_name_continuation(line: str) -> bool:
        # No digits or obvious field separators.
        if re.search(r"\d", line) or ":" in line:
            return False

        s = _norm_spaces(line)
        if not s:
            return False

        # Allow letters, spaces and common name punctuation.
        if not re.fullmatch(r"[A-ZÀ-Ü \-\.'’]{2,}", s.upper()):
            return False

        # Must contain at least 2 alphabetic characters and be reasonably short.
        if len(re.sub(r"[^A-ZÀ-Ü]", "", s.upper())) < 2:
            return False
        if len(s) > 80:
            return False

        return True

    lines = [l.rstrip() for l in text.splitlines()]
    idx = None
    for i, l in enumerate(lines):
        up = l.upper()
        if "FIL" in up and (("MÃE" in up) or ("MAE" in up)) and ":" in up:
            idx = i
            break

    if idx is None:
        return None

    line = lines[idx]
    line_up = line.upper()

    # Prefer extracting after the MÃE/MAE label on the same line (handles "Fil. Pai: ... Fil.Mãe: <NOME>").
    m = re.search(r"(?i)M[ÃA]E\s*:?\s*(?P<nome>.+)$", line)
    if m:
        first = m.group("nome")
    else:
        # Fallback: take after the last ':'.
        first = line.split(":")[-1]

    first_up = _norm_spaces(first).upper()
    if _is_section_label(first_up):
        return None

    # Remove anything that might have been glued after the name by layout extraction.
    first_up = re.split(r"\bQTDE\b|\bDEPENDENT\w*\b", first_up)[0].strip()
    parts = [first_up] if first_up else []

    # Append continuation lines (wrapped surname, second surname, etc.).
    for j in range(idx + 1, len(lines)):
        nxt = _norm_spaces(lines[j])
        if not nxt:
            continue

        nxt_up = nxt.upper()

        if _is_section_label(nxt_up):
            break

        if _looks_like_name_continuation(nxt):
            parts.append(nxt_up)
            continue

        break

    nome = _norm_spaces(" ".join(parts)).upper()
    return nome if nome else None


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
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    cep: Optional[str] = None
    telefone: Optional[str] = None
    data_admissao: Optional[str] = None
    empresa: Optional[str] = None
    cargo: Optional[str] = None
    salario: Optional[str] = None
    outras_rendas: Optional[str] = None
    valor_parcela: Optional[str] = None
    valor_compra: Optional[str] = None
    debug: Dict[str, Any] = field(default_factory=dict)


def parse_proposta_daycoval(text: str, *, return_debug: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Parse a Daycoval proposal extracted-text into a canonical JSON dict.

    This parser is intentionally conservative and relies on common labels.
    Returned fields are uppercase normalized where appropriate.

    Known contracts:
      - endereco is logradouro-only; numero/complemento separate
      - nome_mae supports wrapped surnames on the next line
    """
    res = PropostaDaycovalResult()

    # proposta number
    res.proposta = _extract_first(text, r"\bProposta\s*:?\s*(\d{6,})\b")

    # nome financiado
    res.nome_financiado = _extract_first(
        text,
        r"Nome\s*do\s*Financiado\s*:?\s*([A-ZÀ-Ü\s]{3,})\b",
    )

    # nome loja
    res.nome_loja = _extract_first(
        text,
        r"Nome\s*da\s*Loja\s*:?\s*([\w\s\-\.]{3,})\b",
    )

    # cpf
    cpf = _extract_first(text, r"\bCPF\s*:?\s*([\d\.\-]{11,})\b")
    res.cpf = _only_digits(cpf) if cpf else None

    # data nascimento
    res.data_nascimento = _extract_first(
        text,
        r"Data\s*de\s*Nascimento\s*:?\s*(\d{2}/\d{2}/\d{4})\b",
    )

    # cidade/uf nascimento
    cidade = _extract_first(text, r"Cidade\s*de\s*Nascimento\s*:?\s*([A-ZÀ-Ü\s]{2,})\b")
    res.cidade_nascimento = cidade
    uf = _extract_first(text, r"\bUF\s*:?\s*([A-Z]{2})\b")
    res.uf = uf

    # nome mae (robust multiline)
    res.nome_mae = _extract_nome_mae_multiline(text)

    # endereco then split
    endereco_raw = _between(text, "Endereço:", "Bairro") or _between(text, "Endereco:", "Bairro")
    end, num, comp = _split_endereco(endereco_raw)
    res.endereco = end
    res.numero = num
    res.complemento = comp

    # bairro/cidade/cep/telefone
    res.bairro = _extract_first(text, r"\bBairro\s*:?\s*([A-ZÀ-Ü\s]{2,})\b")
    res.cidade = _extract_first(text, r"\bCidade\s*:?\s*([A-ZÀ-Ü\s]{2,})\b")
    cep = _extract_first(text, r"\bCEP\s*:?\s*([\d\.\-]{8,})\b")
    res.cep = _only_digits(cep) if cep else None
    tel = _extract_first(text, r"\bTelefone\s*:?\s*([\d\(\)\s\-]{8,})\b")
    res.telefone = _only_digits(tel) if tel else None

    # empresa/cargo/admissao
    res.empresa = _extract_first(text, r"\bEmpresa\s*:?\s*([A-ZÀ-Ü0-9\s\.\-]{2,})\b")
    res.cargo = _extract_first(text, r"\bCargo\s*:?\s*([A-ZÀ-Ü0-9\s\.\-]{2,})\b")
    res.data_admissao = _extract_first(text, r"\bData\s*de\s*Admiss[aã]o\s*:?\s*(\d{2}/\d{2}/\d{4})\b")

    # renda/valores
    res.salario = _extract_first(text, r"\bSal[aá]rio\s*:?\s*(R?\$?\s*[\d\.\,]+)")
    res.outras_rendas = _extract_first(text, r"\bOutras\s*Rendas\s*:?\s*(R?\$?\s*[\d\.\,]+)")
    res.valor_parcela = _extract_first(text, r"\bValor\s*da\s*Parcela\s*:?\s*(R?\$?\s*[\d\.\,]+)")
    res.valor_compra = _extract_first(text, r"\bValor\s*da\s*Compra\s*:?\s*(R?\$?\s*[\d\.\,]+)")

    # Normalization
    res.proposta = _norm_spaces(res.proposta) if res.proposta else None
    res.nome_financiado = _upper(res.nome_financiado)
    res.nome_loja = _upper(res.nome_loja)
    res.cidade_nascimento = _upper(res.cidade_nascimento)
    res.uf = _upper(res.uf)
    res.nome_mae = _upper(res.nome_mae)
    res.endereco = _upper(res.endereco)
    res.complemento = _upper(res.complemento)
    res.bairro = _upper(res.bairro)
    res.cidade = _upper(res.cidade)
    res.cargo = _upper(res.cargo)
    res.empresa = _upper(res.empresa)

    # Keep dates/money as normalized strings (not forced uppercase)
    res.data_nascimento = _norm_spaces(res.data_nascimento) if res.data_nascimento else None
    res.data_admissao = _norm_spaces(res.data_admissao) if res.data_admissao else None
    res.salario = _norm_spaces(res.salario) if res.salario else None
    res.outras_rendas = _norm_spaces(res.outras_rendas) if res.outras_rendas else None
    res.valor_parcela = _norm_spaces(res.valor_parcela) if res.valor_parcela else None
    res.valor_compra = _norm_spaces(res.valor_compra) if res.valor_compra else None

    fields: Dict[str, Any] = asdict(res)
    dbg = fields.pop("debug", {}) if isinstance(fields, dict) else {}

    if return_debug:
        return fields, dbg
    return fields, {}
