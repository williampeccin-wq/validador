from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Literal


# =====================================================================================
# Parser DETRAN SC
#
# Objetivo (Phase 1): extração fiel + normalização básica de campos.
# - SEM validações
# - SEM inferências cruzadas
# - Tolerante a 2 formatos:
#   * consulta="despachante" (completo)
#   * consulta="aberta" (ofuscado)
#
# Observação: validações (vendedor=proprietário, restrições, IPVA, soma de débitos vs FIPE)
# devem ocorrer na Phase 2, após coletar todos os documentos.
# =====================================================================================


MIN_TEXT_LEN_THRESHOLD_DEFAULT = 700

_PLACA_RE = re.compile(r"\b([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b")
_RENAVAM_RE = re.compile(r"\b(\d{11})\b")
_ANO_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

# Documento do proprietário raramente aparece; quando aparece em consulta aberta pode vir ofuscado.
_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_CPF_MASKED_RE = re.compile(r"\b(\d{3}\*{3,}\d{2})\b")
_CNPJ_MASKED_RE = re.compile(r"\b(\d{2}\*{3,}\d{2})\b")

_MONEY_RE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})")

_NOISE_RE = re.compile(
    r"(DENATRAN|SENATRAN|QR\s*CODE|DPVAT|GOVERNO|SECRETARIA)",
    re.IGNORECASE,
)


def analyze_detran_sc(
    path: str,
    *,
    consulta: Optional[Literal["aberta", "despachante"]] = None,
    min_text_len_threshold: int = MIN_TEXT_LEN_THRESHOLD_DEFAULT,
    ocr_dpi: int = 300,
) -> Dict[str, Any]:
    """Parser Detran SC.

    Contrato (Phase 1):
      - Retorna dict flat (compatível com testes existentes).
      - Inclui campos textuais (blocos) para auditoria.
      - Extração best-effort com OCR fallback.
      - Não realiza validações nem inferências cruzadas.
    """

    native_text, pages_native_len = _extract_native_text(path)

    if len(native_text) >= min_text_len_threshold:
        mode = "native"
        ocr_text = ""
        pages_ocr_len = [0 for _ in pages_native_len]
    else:
        mode = "ocr"
        ocr_text, pages_ocr_len = _ocr_to_text(path, dpi=ocr_dpi)

    text = native_text if mode == "native" else ocr_text
    lines = _clean_lines(text)

    proprietario_nome = _extract_owner_name(lines)
    proprietario_nome_ofuscado = _detect_name_ofuscado(proprietario_nome) if proprietario_nome else False

    # Se consulta não foi informada, auto-detectar de forma conservadora:
    # - nome com asteriscos => aberta
    # - caso contrário => despachante
    consulta_eff: Literal["aberta", "despachante"] = (
        consulta if consulta in {"aberta", "despachante"} else ("aberta" if proprietario_nome_ofuscado else "despachante")
    )

    # Mantém compatibilidade: em consulta aberta, o nome é considerado ofuscado.
    if consulta_eff == "aberta":
        proprietario_nome_ofuscado = True

    extracted = _extract_fields(lines, proprietario_nome, proprietario_nome_ofuscado)

    pages: List[Dict[str, Any]] = []
    for i in range(max(len(pages_native_len), len(pages_ocr_len))):
        pages.append(
            {
                "page": i + 1,
                "native_len": pages_native_len[i] if i < len(pages_native_len) else 0,
                "ocr_len": pages_ocr_len[i] if i < len(pages_ocr_len) else 0,
            }
        )

    return {
        **extracted,
        "mode": mode,
        "debug": {
            "consulta": consulta_eff,
            "native_text_len": len(native_text),
            "ocr_text_len": len(ocr_text),
            "min_text_len_threshold": min_text_len_threshold,
            "ocr_dpi": ocr_dpi,
            "pages": pages,
            "warnings": [],
        },
    }


# =========================
# Text extraction
# =========================


def _extract_native_text(path: str) -> Tuple[str, List[int]]:
    texts, lens = [], []
    if path.lower().endswith(".pdf"):
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                t = p.extract_text() or ""
                texts.append(t)
                lens.append(len(t))
    else:
        lens = [0]
    return "\n".join(texts), lens


def _ocr_to_text(path: str, *, dpi: int) -> Tuple[str, List[int]]:
    from pdf2image import convert_from_path
    from PIL import Image
    import pytesseract

    texts, lens = [], []

    if path.lower().endswith(".pdf"):
        images = convert_from_path(path, dpi=dpi)
    else:
        images = [Image.open(path)]

    for img in images:
        t = pytesseract.image_to_string(img, lang="por") or ""
        texts.append(t)
        lens.append(len(t))
    return "\n".join(texts), lens


# =========================
# Helpers
# =========================


def _clean_lines(text: str) -> List[str]:
    out: List[str] = []
    for l in (text or "").splitlines():
        l = l.strip()
        if not l:
            continue
        if _NOISE_RE.search(l):
            continue
        out.append(l)
    return out


def _detect_name_ofuscado(name: str) -> bool:
    # Ex.: "L*** L***" ou "J********".
    return "*" in (name or "")


def _extract_owner_name(lines: List[str]) -> Optional[str]:
    # Padrão aberto: "Nome do proprietário atual" e na linha seguinte o nome (ofuscado).
    # Padrão despachante: "Nome do Proprietário Atual" e na linha seguinte o nome.
    for i, l in enumerate(lines):
        u = l.upper()
        if "NOME DO PROPRIET" in u and "ATUAL" in u:
            tail = l.split(":", 1)[-1].strip()
            if tail and tail.upper() != l.upper():
                return tail
            if i + 1 < len(lines):
                return lines[i + 1].strip()

        # fallback: "PROPRIET...: <nome>"
        if "PROPRIET" in u and ":" in l:
            return l.split(":", 1)[-1].strip()

    return None


def _first(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text or "")
    return m.group(1) if m else None


def _value_after(lines: List[str], label: str) -> Optional[str]:
    label_u = label.upper()
    for i, l in enumerate(lines):
        if label_u in l.upper():
            tail = l.split(":", 1)[-1].strip()
            if tail and tail.upper() != label_u:
                return tail
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    return None


def _extract_years(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    for l in lines:
        if "FABRICA" in l.upper() or "ANO" in l.upper():
            ys = _ANO_RE.findall(l)
            if len(ys) >= 2:
                return ys[0], ys[1]
            if len(ys) == 1:
                return ys[0], ys[0]
    return None, None


def _block_after(lines: List[str], label: str, *, stop_on_header: bool = True) -> Optional[str]:
    label_u = label.upper()
    buf: List[str] = []
    capture = False
    for l in lines:
        u = l.upper()
        if label_u in u:
            capture = True
            continue
        if capture:
            if stop_on_header and re.match(r"^[A-ZÇÃÕÁÉÍÓÚÂÊÎÔÛ\s]{3,}$", u):
                break
            buf.append(l)
    return " ".join(buf).strip() if buf else None


def _extract_owner_doc_best_effort(lines: List[str]) -> Tuple[Optional[str], bool]:
    for l in lines:
        m = _CPF_RE.search(l) or _CNPJ_RE.search(l)
        if m:
            return m.group(1), False
        m2 = _CPF_MASKED_RE.search(l) or _CNPJ_MASKED_RE.search(l)
        if m2:
            return m2.group(1), True
    return None, False


def _money_values_to_cents(text: Optional[str]) -> List[int]:
    if not text:
        return []
    cents: List[int] = []
    for m in _MONEY_RE.finditer(text):
        inteiro = m.group(1).replace(".", "")
        frac = m.group(2)
        try:
            cents.append(int(inteiro) * 100 + int(frac))
        except Exception:
            continue
    return cents


def _detect_alienacao_status(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    blob = "\n".join(lines).upper()

    if "SEM GRAVAME" in blob:
        return "ausente", "SEM GRAVAME"

    if "BAIXA" in blob and "ALIENA" in blob:
        return "inativa", "BAIXA DE ALIENAÇÃO"

    if "ALIENA" in blob or "GRAVAME" in blob:
        return "desconhecida", "ALIENA/GRAVAME MENCIONADO"

    return None, None


def _detect_restricao_admin(lines: List[str]) -> Tuple[Optional[bool], Optional[str]]:
    blob = "\n".join(lines).upper()

    negatives = [
        "NENHUMA RESTRIÇÃO CADASTRADA",
        "NENHUMA RESTRIÇÃO REGISTRADA",
        "SEM RESTRIÇÃO",
        "SEM RESTRICOES",
    ]
    for n in negatives:
        if n in blob:
            return False, n

    positives = [
        "RESTRIÇÃO",
        "RESTRICAO",
        "BLOQUEIO",
        "IMPEDIMENTO",
        "RESTRIÇÃO ADMINISTRATIVA",
        "RESTRICAO ADMINISTRATIVA",
    ]
    if any(p in blob for p in positives):
        return True, "MENCIONA RESTRIÇÃO/BLOQUEIO"

    return None, None


def _detect_ipva_atraso(lines: List[str]) -> Tuple[Optional[bool], Optional[str]]:
    blob = "\n".join(lines).upper()

    if "DÍVIDA ATIVA" in blob or "DIVIDA ATIVA" in blob:
        if _MONEY_RE.search(blob):
            return True, "DÍVIDA ATIVA + VALOR"
        return None, "DÍVIDA ATIVA (SEM VALOR)"

    if "IPVA" in blob and ("EM ATRASO" in blob or "EM ABERTO" in blob or "NOTIFICADO" in blob):
        if _MONEY_RE.search(blob):
            return True, "IPVA + (ATRASO/ABERTO/NOTIFICADO) + VALOR"
        return None, "IPVA + (ATRASO/ABERTO/NOTIFICADO)"

    if "IPVA" in blob and ("NENHUM" in blob or "NENHUMA" in blob):
        return False, "IPVA + NENHUM"

    return None, None


def _extract_fields(
    lines: List[str],
    proprietario_nome: Optional[str],
    proprietario_nome_ofuscado: bool,
) -> Dict[str, Any]:
    blob = " ".join(lines).upper()

    placa = _first(_PLACA_RE, blob)
    renavam = _first(_RENAVAM_RE, blob)

    marca_modelo = _value_after(lines, "MARCA")
    ano_fabricacao, ano_modelo = _extract_years(lines)
    cor = _value_after(lines, "COR")
    chassi = _value_after(lines, "CHASSI")

    situacao_texto = _block_after(lines, "SITUAÇÃO") or _block_after(lines, "SITUACAO")
    debitos_texto = (
        _block_after(lines, "DÉBITOS")
        or _block_after(lines, "DEBITOS")
        or _block_after(lines, "LISTAGEM DE DÉBITOS")
        or _block_after(lines, "LISTAGEM DE DEBITOS")
    )
    multas_texto = _block_after(lines, "MULTAS") or _block_after(lines, "LISTAGEM DE MULTAS")
    restricoes_texto = _block_after(lines, "RESTRIÇÕES") or _block_after(lines, "RESTRICOES")
    restricao_venda_texto = _block_after(lines, "RESTRIÇÃO À VENDA") or _block_after(lines, "RESTRICAO A VENDA")

    proprietario_doc, proprietario_doc_ofuscado = _extract_owner_doc_best_effort(lines)

    alienacao_status, alienacao_evidence = _detect_alienacao_status(lines)
    restricao_admin_ativa, restricao_admin_evidence = _detect_restricao_admin(lines)
    ipva_atraso, ipva_evidence = _detect_ipva_atraso(lines)

    debitos_cents = _money_values_to_cents(debitos_texto)
    multas_cents = _money_values_to_cents(multas_texto)
    debitos_total_cents = sum(debitos_cents) if debitos_cents else 0
    multas_total_cents = sum(multas_cents) if multas_cents else 0

    debitos_em_aberto = None
    if debitos_texto:
        u = debitos_texto.upper()
        if "NENHUM" in u and "DÉBITO" in u:
            debitos_em_aberto = False
        elif _MONEY_RE.search(u):
            debitos_em_aberto = True

    multas_em_aberto = None
    if multas_texto:
        u = multas_texto.upper()
        if "NENHUM" in u and "MULTA" in u:
            multas_em_aberto = False
        elif _MONEY_RE.search(u):
            multas_em_aberto = True

    return {
        "placa": placa,
        "renavam": renavam,
        "chassi": chassi,
        "marca_modelo": marca_modelo,
        "ano_fabricacao": ano_fabricacao,
        "ano_modelo": ano_modelo,
        "cor": cor,

        "proprietario_nome": proprietario_nome,
        "proprietario_nome_ofuscado": proprietario_nome_ofuscado,
        "proprietario_doc": proprietario_doc,
        "proprietario_doc_ofuscado": proprietario_doc_ofuscado,

        "situacao_texto": situacao_texto,
        "debitos_texto": debitos_texto,
        "multas_texto": multas_texto,
        "restricoes_texto": restricoes_texto,
        "restricao_venda_texto": restricao_venda_texto,

        "alienacao_fiduciaria_status": alienacao_status,
        "restricao_administrativa_ativa": restricao_admin_ativa,
        "ipva_em_atraso": ipva_atraso,

        "debitos_total_cents": debitos_total_cents,
        "multas_total_cents": multas_total_cents,
        "debitos_em_aberto": debitos_em_aberto,
        "multas_em_aberto": multas_em_aberto,

        "evidence": {
            "alienacao": alienacao_evidence,
            "restricao_admin": restricao_admin_evidence,
            "ipva": ipva_evidence,
        },
    }
