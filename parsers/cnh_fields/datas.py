from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional, Tuple


_RE_MRZ_DATES = re.compile(r"(?P<b>\d{6})(?P<bchk>\d)(?P<sex>[MF])(?P<e>\d{6})(?P<echk>\d)")


def _compact_mrz(s: str) -> str:
    # mantém dígitos/letras e '<' (MRZ)
    return re.sub(r"[^A-Z0-9<]", "", (s or "").upper())


def _yymmdd_to_date(yymmdd: str, *, kind: str, today: Optional[date] = None) -> Optional[date]:
    """
    kind:
      - "birth": resolve século por regra simples baseada no ano atual
      - "exp": assume normalmente 20xx; fallback para 19xx só se yy muito alto
    """
    if not yymmdd or len(yymmdd) != 6 or not yymmdd.isdigit():
        return None

    yy = int(yymmdd[0:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])

    if today is None:
        today = date.today()

    if kind == "birth":
        cur_yy = today.year % 100
        year = 2000 + yy if yy <= cur_yy else 1900 + yy
    else:
        # CNH validade tipicamente 20xx nas próximas décadas
        year = 2000 + yy if yy < 80 else 1900 + yy

    try:
        return date(year, mm, dd)
    except ValueError:
        return None


@dataclass(frozen=True)
class DatasCNH:
    data_nascimento: Optional[str]
    validade: Optional[str]
    dbg: Dict[str, Any]


def extract_datas_mrz(raw_text: str) -> DatasCNH:
    """
    Extrai datas via MRZ:
      - data_nascimento (DD/MM/YYYY)
      - validade (DD/MM/YYYY)

    MRZ típica contém: YYMMDD + checkdigit + sex(M/F) + YYMMDD + checkdigit
    Ex.: 9308097M3212183BRA<<<<<<<<<<<4
    """
    dbg: Dict[str, Any] = {"field": "datas", "method": None}
    if not raw_text:
        return DatasCNH(None, None, {"field": "datas", "method": "none"})

    for ln in raw_text.splitlines():
        s = _compact_mrz(ln)
        m = _RE_MRZ_DATES.search(s)
        if not m:
            continue

        b = _yymmdd_to_date(m.group("b"), kind="birth")
        e = _yymmdd_to_date(m.group("e"), kind="exp")
        if not b or not e:
            continue

        data_nascimento = b.strftime("%d/%m/%Y")
        validade = e.strftime("%d/%m/%Y")
        dbg.update(
            {
                "method": "mrz_line",
                "mrz_line": s,
                "birth_yymmdd": m.group("b"),
                "exp_yymmdd": m.group("e"),
                "sex": m.group("sex"),
            }
        )
        return DatasCNH(data_nascimento, validade, dbg)

    return DatasCNH(None, None, {"field": "datas", "method": "none"})
