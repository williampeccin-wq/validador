from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


UF_SET = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR",
    "PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO",
}

# CIDADE, UF  (UF obrigatório ser UF BR)
RE_CITY_UF = re.compile(
    r"(?P<city>[A-ZÀ-Ü]{3,}(?:\s+[A-ZÀ-Ü]{2,}){0,8})\s*,\s*(?P<uf>[A-Z]{2})\b"
)

RE_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")

# header / lixo (determinístico por substring)
STOP_SUBSTRINGS = [
    "NOME", "SOBRENOME", "NAME", "SURNAME", "NOMBRE", "APELLIDOS",
    "PRIMEIRA", "HABILITAC", "FIRST", "DRIVER", "LICENSE", "LICENCIA",
    "CATEGORIA", "VEICULOS", "OBSERVA", "FILIA", "NACIONALIDADE",
    "REPUBLICA", "FEDERATIVA", "CARTEIRA", "ASSINATURA", "PORTADOR",
    "DATA", "VALIDADE", "EMISSAO",
    # multilíngue comum em cabeçalho de campos
    "NATURALIDADE", "NATURALITY", "NATURALITE",
]


def _u(s: Any) -> str:
    return ("" if s is None else str(s)).upper()


def _has_stopwords(city_u: str, line_u: str) -> bool:
    return any(w in city_u for w in STOP_SUBSTRINGS) or any(w in line_u for w in STOP_SUBSTRINGS)


def _clean_city_prefix(city: str) -> str:
    # Remove apenas prefixos determinísticos (ruído lateral), sem “caçar caracteres”.
    c = (city or "").strip()
    cu = c.upper()
    for p in ("N ", "N:", "N-", "Nº", "N°"):
        if cu.startswith(p):
            c = c[len(p):].lstrip()
            break
    return c


def _city_is_plausible(city_u: str) -> Tuple[bool, list[str]]:
    reasons: list[str] = []
    c = (city_u or "").strip()
    if not c:
        return False, ["city_empty"]

    # Não pode ter dígitos
    if any(ch.isdigit() for ch in c):
        reasons.append("city_has_digits")

    # Mínimo de letras “reais”
    letters = [ch for ch in c if "A" <= ch <= "Z" or "À" <= ch <= "Ü"]
    if len(letters) < 4:
        reasons.append("city_too_short")

    # Pelo menos 1 token com >=4 letras (mata 'PST TES' e 'ALA')
    tokens = [t for t in re.split(r"\s+", c) if t]
    max_tok = max((len(t) for t in tokens), default=0)
    if max_tok < 4:
        reasons.append("city_token_too_short")

    return (len(reasons) == 0), reasons


def _tail_kind(after_u: str) -> str:
    # classifica o ruído após UF (não bloqueia por si só; entra no desempate)
    a = (after_u or "").strip()
    if not a:
        return "empty"
    # apenas dígitos e/ou espaços
    if a.replace(" ", "").isdigit():
        return "digits"
    # UF+digits (com ou sem espaço), ex: "SC195714792" ou "SC 195714792" ou "PR926..."
    if re.match(r"^[A-Z]{2}\s*\d{6,}\b", a):
        return "uf_digits"
    return "other"


def _noise_count(s: str) -> int:
    # conta caracteres “suspeitos” (pontuação pesada), determinístico
    bad = 0
    for ch in (s or ""):
        if ch.isalnum() or ch.isspace() or ch in ",-":
            continue
        bad += 1
    return bad


def extract_naturalidade(raw_text: str) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
    """Naturalidade v2 — determinístico, explicável, auditável.

    Regras:
      - base: linha contendo 'CIDADE, UF' (UF BR)
      - rejeita headers / stopwords
      - rejeita cidades muito curtas / tokens curtos
      - NÃO inventa cidade; se baixa confiança retorna None
      - tolera 'UF+digits' após o UF (ex.: 'PR926358404' / 'SC 195714792')
      - prioriza candidatos em linhas que também contenham data dd/mm/yyyy (naturalidade costuma vir na linha do nascimento)
      - desempate por menor ruído lateral (tail + pontuação) e ordem de aparição
    """

    dbg: Dict[str, Any] = {
        "field": "naturalidade",
        "method": "none",
        "v": 2,
        "candidates": [],
    }

    lines = (raw_text or "").splitlines()

    best: Optional[Dict[str, Any]] = None
    best_key: Optional[Tuple[int, int, int, int, int]] = None
    # rank_key (menor é melhor):
    #   0) prefer_date: 0 se tem data na linha, 1 se não tem
    #   1) date_gap: distância (chars) entre última data antes do match e o início do match (menor melhor; 9999 se não aplicável)
    #   2) tail_rank: empty(0) < digits(1) < uf_digits(2) < other(3)
    #   3) noise: caracteres suspeitos no after (menor melhor)
    #   4) line_index: primeiro que aparece ganha

    tail_rank_map = {"empty": 0, "digits": 1, "uf_digits": 2, "other": 3}

    for i, ln in enumerate(lines):
        line_u = _u(ln)
        m = RE_CITY_UF.search(line_u)
        if not m:
            continue

        raw_city = (m.group("city") or "").strip()
        uf = (m.group("uf") or "").strip()

        cand: Dict[str, Any] = {
            "line_index": i,
            "line": ln,
            "city_raw": raw_city,
            "uf": uf,
            "accepted": False,
            "reject_reason": None,
        }

        if uf not in UF_SET:
            cand["reject_reason"] = "uf_not_br"
            dbg["candidates"].append(cand)
            continue

        city = _clean_city_prefix(raw_city)
        city_u = _u(city)
        cand["city"] = city

        if _has_stopwords(city_u=city_u, line_u=line_u):
            cand["reject_reason"] = "stopwords/header_like"
            dbg["candidates"].append(cand)
            continue

        ok_city, city_reasons = _city_is_plausible(city_u)
        if not ok_city:
            cand["reject_reason"] = ",".join(city_reasons)
            dbg["candidates"].append(cand)
            continue

        # data proximity
        before = line_u[: m.start()]
        dates = list(RE_DATE.finditer(before))
        has_date = bool(dates)
        if has_date:
            last = dates[-1]
            date_gap = max(0, m.start() - last.end())
        else:
            date_gap = 9999

        after = line_u[m.end() : m.end() + 40]
        tk = _tail_kind(after)
        noise = _noise_count(after)

        prefer_date = 0 if has_date else 1
        key = (prefer_date, date_gap, tail_rank_map.get(tk, 9), noise, i)

        cand.update(
            {
                "city": city,
                "after": after,
                "tail_kind": tk,
                "has_date_before": has_date,
                "date_gap": date_gap if has_date else None,
                "noise": noise,
                "rank_key": list(key),
            }
        )

        cand["accepted"] = True
        dbg["candidates"].append(cand)

        if best is None or key < best_key:  # type: ignore[operator]
            best = cand
            best_key = key

    if not best:
        dbg["method"] = "none"
        return None, None, dbg

    dbg["best"] = {
        "line_index": best.get("line_index"),
        "line": best.get("line"),
        "cidade": best.get("city"),
        "uf": best.get("uf"),
        "rank_key": best.get("rank_key"),
    }

    # Critério de aceitação: precisa ter data na linha para considerar naturalidade confiável.
    # Isso evita “inventar” Florianópolis por aparecer como ruído recorrente sem data.
    if not best.get("has_date_before"):
        dbg["method"] = "none_low_confidence"
        return None, None, dbg

    dbg["method"] = "naturalidade_v2_city_uf_date_line"
    dbg["chosen"] = {"cidade": best["city"], "uf": best["uf"]}
    dbg["chosen_from_line_index"] = best["line_index"]
    dbg["chosen_from_line"] = best["line"]

    return best["city"], best["uf"], dbg
