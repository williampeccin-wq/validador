import re
from typing import Optional

_UF_SET = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _upper(s: str) -> str:
    return _norm_spaces(s).upper()


def _safe_get(lines: list[str], idx: int) -> str:
    if 0 <= idx < len(lines):
        return lines[idx]
    return ""


def _alpha_ratio_letters_only(s: str) -> float:
    if not s:
        return 0.0
    letters = sum(1 for ch in s if ch.isalpha())
    alnum = sum(1 for ch in s if ch.isalnum())
    return letters / max(alnum, 1)


def extract_naturalidade(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    def _extract_from_text(txt: str) -> tuple[Optional[str], Optional[str]]:
        u = _upper(txt)
        m = re.search(
            r"\b(\d{2}[/-]\d{2}[/-]\d{4})\s*,\s*([A-ZÀ-Ú][A-ZÀ-Ú\s'\-\.]{2,}?)\s*,\s*([A-Z]{2})\b",
            u,
        )
        if not m:
            return None, None
        cidade = _norm_spaces(m.group(2)).strip(" \t\"'|.,;-_")
        uf = re.sub(r"[^A-Z]", "", m.group(3))
        if not uf or uf not in _UF_SET:
            return None, None
        if not cidade or len(cidade) < 3:
            return None, None
        if _alpha_ratio_letters_only(cidade) < 0.6:
            return None, None
        return cidade, uf

    for i, ln in enumerate(lines):
        u = _upper(ln)

        # Âncora do bloco "DATA, LOCAL E UF DE NASCIMENTO" (CNH exportada)
        if ("LOCAL" in u and "UF" in u and "NASC" in u):
            chunk = "\n".join([ln, _safe_get(lines, i + 1), _safe_get(lines, i + 2)])
            cidade, uf = _extract_from_text(chunk)
            if cidade and uf:
                return cidade, uf

        # Fallback: NATURALIDADE / NATURAL
        if "NATURAL" in u:
            tail = re.split(r"NATURAL(?:IDADE)?\s*[:\-]?\s*", u, maxsplit=1)
            cand = tail[1] if len(tail) == 2 else ""
            chunk = "\n".join([cand, _safe_get(lines, i + 1), _safe_get(lines, i + 2)])
            cidade, uf = _extract_from_text(chunk)
            if cidade and uf:
                return cidade, uf

            # padrão sem vírgula e sem data: "CIDADE UF"
            cand_u = _upper(cand)
            m_inline = re.search(r"\b([A-ZÀ-Ú][A-ZÀ-Ú\s'\-\.]{2,}?)\s+([A-Z]{2})\b", cand_u)
            if m_inline:
                cidade2 = _norm_spaces(m_inline.group(1)).strip(" \t\"'|.,;-_")
                uf2 = re.sub(r"[^A-Z]", "", m_inline.group(2))
                if uf2 in _UF_SET and cidade2 and _alpha_ratio_letters_only(cidade2) >= 0.6:
                    return cidade2, uf2

            # "CIDADE, UF" sem data
            u2 = _upper(_safe_get(lines, i + 1))
            m2 = re.search(r"\b([A-ZÀ-Ú][A-ZÀ-Ú\s'\-\.]{2,}?)\s*,\s*([A-Z]{2})\b", u2)
            if m2:
                cidade3 = _norm_spaces(m2.group(1)).strip(" \t\"'|.,;-_")
                uf3 = re.sub(r"[^A-Z]", "", m2.group(2))
                if uf3 in _UF_SET and cidade3 and _alpha_ratio_letters_only(cidade3) >= 0.6:
                    return cidade3, uf3

    return None, None
