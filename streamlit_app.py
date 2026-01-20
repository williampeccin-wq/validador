# streamlit_app.py
from __future__ import annotations

import json
import os
import re
import shutil
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# Projeto
from orchestrator.phase1 import start_case, collect_document, DocumentType
from validators.phase2.master_report import build_master_report


# ============================================================
# Config
# ============================================================
APP_TITLE = "Validador de Documentos"
TMP_UPLOADS_DIR = Path(".ui_tmp_uploads")
PHASE1_ROOT = Path("storage/phase1")
PHASE2_ROOT = Path("storage/phase2")


# ============================================================
# UI
# ============================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.write("Envie os documentos disponíveis e obtenha um **parecer consolidado**.")
st.write("O sistema indicará: **o que foi validado**, **o que ainda falta**, e **se há inconsistências**.")

allowed_doc_types: List[str] = [d.value for d in DocumentType]


# ============================================================
# Helpers (gerais)
# ============================================================
def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_pdf_text_head(pdf_path: Path, max_chars: int = 8000) -> str:
    """
    Leitura leve do início do texto do PDF (para classificação).
    Não usa OCR aqui.
    """
    try:
        import pdfplumber
        out = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:2]:
                t = (page.extract_text() or "").strip()
                if t:
                    out.append(t)
        s = "\n".join(out)
        s = re.sub(r"[ \t]+", " ", s)
        return s[:max_chars]
    except Exception:
        return ""


def _upper(s: str) -> str:
    return (s or "").upper()


def _mask_value(v: Any, kind: str) -> Any:
    """
    Redação básica para exibição ao usuário final.
    - Não tenta “adivinhar” demais.
    - Mantém utilidade: mostra os últimos dígitos quando fizer sentido.
    """
    if v is None:
        return None
    if not isinstance(v, str):
        return v

    s = v.strip()
    if not s:
        return s

    k = (kind or "").lower()

    # CPF/CNPJ: mantém últimos 3-4 dígitos
    if k in {"cpf", "cnpj"}:
        digits = re.sub(r"\D", "", s)
        if len(digits) >= 4:
            return "***." + digits[-4:]
        return "***"

    # Documento/registro: mantém últimos 3-4
    if k in {"rg", "registro", "cnh", "numero", "documento"}:
        digits = re.sub(r"\D", "", s)
        if len(digits) >= 4:
            return "***" + digits[-4:]
        return "***"

    # Nome: mostra completo (é o que o usuário final quer validar)
    if k in {"nome"}:
        return s

    # Datas: mostra completo
    if k in {"data", "data_nascimento", "nascimento"}:
        return s

    # Endereço: mostra completo (se estiver disponível, geralmente é relevante)
    if k in {"endereco", "logradouro"}:
        return s

    return s


def _present_kv(title: str, data: Dict[str, Any]) -> None:
    """
    Renderiza um bloco de "dados capturados" em formato amigável.
    """
    if not data:
        st.write("Nenhum dado disponível.")
        return
    st.markdown(f"**{title}**")
    rows = []
    for k, v in data.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        rows.append((k, v))
    if not rows:
        st.write("Nenhum dado disponível.")
        return
    for k, v in rows:
        st.write(f"- **{k}**: {v}")


# ============================================================
# Detecção de tipo (Phase1)
# ============================================================
def _detect_doc_type(filename: str, file_path: Path) -> Optional[str]:
    """
    Regras determinísticas:
      - CNH DIGITAL.pdf (PDF) deve virar 'cnh' (não cnh_senatran).
    """
    fn = (filename or "").lower()

    # Por nome
    if "cnh" in fn:
        if "cnh" in allowed_doc_types:
            return "cnh"
        if "cnh_senatran" in allowed_doc_types:
            return "cnh_senatran"

    if "daycoval" in fn or "proposta" in fn:
        if "proposta_daycoval" in allowed_doc_types:
            return "proposta_daycoval"

    if "holerite" in fn:
        if "holerite" in allowed_doc_types:
            return "holerite"

    if "folha" in fn:
        if "folha_pagamento" in allowed_doc_types:
            return "folha_pagamento"

    if "extrato" in fn:
        if "extrato_bancario" in allowed_doc_types:
            return "extrato_bancario"

    # Por texto (PDF)
    text = _upper(_safe_read_pdf_text_head(file_path))
    if text:
        if ("CARTEIRA NACIONAL DE HABIL" in text) or ("ASSINADOR SERPRO" in text) or ("SENATRAN" in text):
            if "cnh" in allowed_doc_types:
                return "cnh"
            if "cnh_senatran" in allowed_doc_types:
                return "cnh_senatran"

        if ("BANCO DAYCOVAL" in text) or ("PLANILHA DE PROPOSTA" in text) or re.search(r"\bPROPOSTA:\s*\d{6,}\b", text):
            if "proposta_daycoval" in allowed_doc_types:
                return "proposta_daycoval"

        if ("EXTRATO" in text and "SALDO" in text) or ("LANCAMENTOS" in text) or ("HISTORICO" in text):
            if "extrato_bancario" in allowed_doc_types:
                return "extrato_bancario"

        if ("RECIBO DE PAGAMENTO" in text) or ("PAGAMENTO DE SALARIO" in text):
            if "holerite" in allowed_doc_types:
                return "holerite"
            if "folha_pagamento" in allowed_doc_types:
                return "folha_pagamento"

    return None


# ============================================================
# Status / Parecer
# ============================================================
def _status_emoji(status: str) -> str:
    s = (status or "").upper()
    if s == "OK":
        return "✅"
    if s == "WARN":
        return "⚠️"
    if s == "FAIL":
        return "❌"
    if s == "MISSING":
        return "📄"
    return "ℹ️"


def _human_overall_message(overall_status: str, missing_docs: List[str]) -> str:
    s = (overall_status or "").upper()
    if s == "OK":
        return "✅ Tudo certo com o que foi possível validar a partir dos documentos enviados."
    if s == "FAIL":
        return "❌ Foram encontradas inconsistências relevantes. Veja os detalhes."
    if s == "WARN":
        return "⚠️ Há pontos de atenção. Veja os detalhes."
    if s == "MISSING":
        if missing_docs:
            return "📄 Faltam documentos para concluir a validação. Veja o que está faltando."
        return "📄 Há validações pendentes por falta de evidências."
    return "ℹ️ Resultado disponível. Veja os detalhes."


def _summarize_missing_docs_from_checks(checks: List[Dict[str, Any]]) -> List[str]:
    missing: List[str] = []
    for c in checks:
        if (c.get("status") or "").upper() != "MISSING":
            continue
        ev = c.get("evidence") or {}
        miss = ev.get("missing")
        if isinstance(miss, list):
            for x in miss:
                if isinstance(x, str) and x.strip():
                    missing.append(x.strip())

        if c.get("id", "").startswith("income.") and isinstance(ev.get("proof_docs"), list) and len(ev.get("proof_docs")) == 0:
            missing.append("comprovantes_de_renda")

    out: List[str] = []
    seen = set()
    for x in missing:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _group_checks(checks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out = {"OK": [], "WARN": [], "FAIL": [], "MISSING": [], "OTHER": []}
    for c in checks:
        s = (c.get("status") or "").upper()
        if s in out:
            out[s].append(c)
        else:
            out["OTHER"].append(c)
    return out


# ============================================================
# Dados capturados (Phase1) → "cara limpa"
# ============================================================
PHASE1_DISPLAY_WHITELIST: Dict[str, List[Tuple[str, str]]] = {
    # (field_name, kind_for_mask)
    "cnh": [
        ("nome", "nome"),
        ("data_nascimento", "data_nascimento"),
        ("cpf", "cpf"),
        ("rg", "rg"),
        ("numero_registro", "cnh"),
        ("uf", "uf"),
        ("municipio", "municipio"),
    ],
    "cnh_senatran": [
        ("nome", "nome"),
        ("data_nascimento", "data_nascimento"),
        ("cpf", "cpf"),
    ],
    "proposta_daycoval": [
        ("nome_financiado", "nome"),
        ("data_nascimento", "data_nascimento"),
        ("cpf", "cpf"),
        ("salario", "valor"),
        ("outras_rendas", "valor"),
        ("renda_total", "valor"),
        ("valor_financiado", "valor"),
        ("prazo_meses", "numero"),
    ],
    "holerite": [
        ("nome", "nome"),
        ("cpf", "cpf"),
        ("competencia", "data"),
        ("salario_bruto", "valor"),
        ("salario_liquido", "valor"),
    ],
    "folha_pagamento": [
        ("nome", "nome"),
        ("cpf", "cpf"),
        ("competencia", "data"),
        ("salario_bruto", "valor"),
        ("salario_liquido", "valor"),
    ],
    "extrato_bancario": [
        ("banco", "texto"),
        ("titular_nome", "nome"),
        ("titular_cpf", "cpf"),
        ("periodo_inicio", "data"),
        ("periodo_fim", "data"),
        ("total_entradas", "valor"),
        ("total_saidas", "valor"),
    ],
}


def _extract_phase1_display(doc_type: str, phase1_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrai e normaliza campos principais para exibir ao usuário final.
    Espera o shape típico Phase1: { "document_type": ..., "data": {...}, ... }.
    """
    data = phase1_json.get("data") if isinstance(phase1_json, dict) else None
    if not isinstance(data, dict):
        data = {}

    whitelist = PHASE1_DISPLAY_WHITELIST.get(doc_type, [])
    out: Dict[str, Any] = {}

    # pega direto do data
    for field, kind in whitelist:
        if field in data:
            out[field] = _mask_value(data.get(field), kind)

    # complementos: tenta mapear nomes alternativos comuns (conservador)
    if doc_type == "proposta_daycoval":
        # renda_total pode estar ausente; tenta derivar só para exibição (não é validação)
        if "renda_total" not in out:
            sal = data.get("salario")
            outr = data.get("outras_rendas")
            if isinstance(sal, (int, float)) and isinstance(outr, (int, float)):
                out["renda_total"] = float(sal) + float(outr)

    return out


def _load_phase1_inputs_from_report(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Lê report["inputs"][doc_type]["path"] e carrega os JSONs Phase1 correspondentes.
    Retorna: { doc_type: {"path":..., "raw":..., "display":...} }
    """
    inputs = report.get("inputs") or {}
    if not isinstance(inputs, dict):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for doc_type, payload in inputs.items():
        if not isinstance(payload, dict):
            continue
        p = payload.get("path")
        if not isinstance(p, str) or not p:
            continue
        path = Path(p)
        raw = _safe_read_json(path)
        if not isinstance(raw, dict):
            continue
        display = _extract_phase1_display(doc_type, raw)
        debug = raw.get("debug") if isinstance(raw, dict) else None
        if not isinstance(debug, dict):
            debug = {}
        out[doc_type] = {
            "path": str(path),
            "raw": raw,
            "display": display,
            "debug": debug,
        }
    return out


def _summarize_data_used_by_checks(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrai do report/checks um resumo explícito do que foi usado nos checks,
    sem depender de PII dentro do master_report.
    """
    checks = report.get("checks") or []
    if not isinstance(checks, list):
        return {}

    used: Dict[str, Any] = {}

    # Identity: quais campos foram comparados
    for c in checks:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        ev = c.get("evidence") or {}
        if cid == "identity.proposta_vs_cnh":
            used["identity.proposta_vs_cnh"] = {
                "fields_compared": ev.get("fields_compared") if isinstance(ev, dict) else None,
                "diffs_present": bool(ev.get("diffs")) if isinstance(ev, dict) else None,
            }

        # Income: declared/proven/proof_docs
        if isinstance(cid, str) and cid.startswith("income.declared_vs_proven."):
            if isinstance(ev, dict):
                used[cid] = {
                    "declared": ev.get("declared"),
                    "proven": ev.get("proven"),
                    "proof_docs_count": len(ev.get("proof_docs") or []) if isinstance(ev.get("proof_docs"), list) else None,
                }

    return used


# ============================================================
# Persistência / pipeline
# ============================================================
@dataclass
class IdentifiedDoc:
    name: str
    path: Path
    doc_type: Optional[str]


def _ensure_clean_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _persist_uploads(case_id: str, uploads: List[Any]) -> List[IdentifiedDoc]:
    out: List[IdentifiedDoc] = []
    case_dir = TMP_UPLOADS_DIR / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    _ensure_clean_dir(case_dir)

    for up in uploads:
        name = up.name
        dest = case_dir / name
        dest.write_bytes(up.getbuffer())
        doc_type = _detect_doc_type(name, dest)
        out.append(IdentifiedDoc(name=name, path=dest, doc_type=doc_type))
    return out


def _run_pipeline(case_id: str, docs: List[IdentifiedDoc]) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    logs: List[str] = []

    for d in docs:
        if not d.doc_type:
            continue
        collect_document(
            case_id=case_id,
            file_path=str(d.path),
            document_type=d.doc_type,
        )
        logs.append(f"collect_document OK: {d.doc_type} <- {d.name}")

    report, report_path = _build_master_report_compat(case_id=case_id)
    if report is not None:
        return logs, report
    if report_path is not None and Path(report_path).exists():
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        return logs, report

    default_path = PHASE2_ROOT / case_id / "report.json"
    if default_path.exists():
        report = json.loads(default_path.read_text(encoding="utf-8"))
        return logs, report

    return logs, None


def _build_master_report_compat(case_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        sig = inspect.signature(build_master_report)
    except Exception:
        sig = None

    kwargs: Dict[str, Any] = {}
    if sig is not None:
        params = sig.parameters
        if "case_id" in params:
            kwargs["case_id"] = case_id
        if "phase1_root" in params:
            kwargs["phase1_root"] = PHASE1_ROOT
        if "phase2_root" in params:
            kwargs["phase2_root"] = PHASE2_ROOT
        if "phase1_dir" in params:
            kwargs["phase1_dir"] = PHASE1_ROOT
        if "phase2_dir" in params:
            kwargs["phase2_dir"] = PHASE2_ROOT

    call_attempts: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    if kwargs:
        call_attempts.append((tuple(), dict(kwargs)))
    call_attempts.append(((case_id,), {}))
    call_attempts.append((tuple(), {"case_id": case_id}))
    call_attempts.append(((case_id,), {"phase1_root": PHASE1_ROOT, "phase2_root": PHASE2_ROOT}))

    last_err: Optional[BaseException] = None
    for args, k in call_attempts:
        try:
            result = build_master_report(*args, **k)
            report, path = _normalize_master_report_result(result)
            return report, path
        except TypeError as e:
            last_err = e
            continue
        except Exception:
            raise

    if last_err is not None:
        raise last_err
    return None, None


def _normalize_master_report_result(result: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if result is None:
        return None, None
    if isinstance(result, dict):
        return result, None
    if isinstance(result, (str, os.PathLike)):
        return None, str(result)

    for attr in ("report_path", "path", "output_path"):
        if hasattr(result, attr):
            v = getattr(result, attr)
            if isinstance(v, (str, os.PathLike)):
                return None, str(v)

    if hasattr(result, "report"):
        v = getattr(result, "report")
        if isinstance(v, dict):
            return v, None
        if isinstance(v, (str, os.PathLike)):
            return None, str(v)

    return None, None


# ============================================================
# Main flow
# ============================================================
uploads = st.file_uploader(
    "Envie os documentos (PDF, JPG, PNG)",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if uploads:
    if "active_case_id" not in st.session_state:
        st.session_state["active_case_id"] = start_case()

    case_id = st.session_state["active_case_id"]
    identified = _persist_uploads(case_id, uploads)

    st.subheader("Documentos identificados")

    unknown = [d for d in identified if not d.doc_type]
    known = [d for d in identified if d.doc_type]

    for d in known:
        st.write(f"✅ {d.name} → `{d.doc_type}`")
    for d in unknown:
        st.write(f"❓ {d.name} → **tipo não identificado**")

    if unknown:
        st.warning(
            "Alguns documentos não puderam ser identificados automaticamente. "
            "Você pode renomear o arquivo (ex.: conter 'cnh', 'extrato', 'holerite', 'daycoval') "
            "ou ajustar manualmente abaixo."
        )
        with st.expander("Ajustar tipo (opcional)", expanded=False):
            for d in unknown:
                sel = st.selectbox(
                    f"Tipo do documento: {d.name}",
                    options=["(não usar)"] + allowed_doc_types,
                    index=0,
                    key=f"manual_{d.name}",
                )
                if sel != "(não usar)":
                    d.doc_type = sel

        unknown_after = [d for d in identified if not d.doc_type]
        if unknown_after:
            st.error("Ainda há arquivos sem tipo. Para analisar, identifique ou remova os arquivos não reconhecidos.")
            st.stop()

    st.divider()

    colA, colB = st.columns([1, 2], vertical_alignment="center")
    with colA:
        run = st.button("Analisar documentos", type="primary")
    with colB:
        st.caption("Observação: detalhes técnicos podem ser expandidos ao final.")

    if run:
        with st.spinner("Processando…"):
            try:
                logs, report = _run_pipeline(case_id, identified)
            except Exception as e:
                st.error(f"Falha ao processar: {type(e).__name__}: {e}")
                st.stop()

        st.success("Documentos processados com sucesso.")

        with st.expander("Log (opcional)", expanded=False):
            for line in logs:
                st.code(line)

        if not report:
            st.error("Não foi possível localizar o report.json em storage/phase2. Verifique o Phase2.")
            st.stop()

        # ============================================================
        # Dados capturados (pré-requisito da UI)
        # ============================================================
        st.subheader("Dados capturados dos documentos enviados")

        phase1_inputs = _load_phase1_inputs_from_report(report)
        if not phase1_inputs:
            st.warning(
                "Não foi possível carregar os dados extraídos (Phase 1) a partir dos paths presentes no relatório. "
                "Isso indica problema de persistência/paths em report['inputs']."
            )
        else:
            # Resumo “cara limpa” por documento
            for doc_type, payload in phase1_inputs.items():
                display = payload.get("display") or {}
                debug = payload.get("debug") or {}
                extractor_dbg = (debug.get("extractor") or {}) if isinstance(debug, dict) else {}
                parse_error = (debug.get("parse_error") if isinstance(debug, dict) else None)

                # Campos minimos por tipo (UI precisa ser objetiva)
                required_fields: List[str] = []
                if doc_type == "cnh":
                    required_fields = ["nome", "data_nascimento"]
                if doc_type == "proposta_daycoval":
                    required_fields = ["nome_financiado", "data_nascimento"]

                missing_required: List[str] = []
                if required_fields:
                    data = (payload.get("raw") or {}).get("data") if isinstance(payload.get("raw"), dict) else None
                    if not isinstance(data, dict):
                        data = {}
                    for f in required_fields:
                        if not data.get(f):
                            # aceita alternativa para proposta
                            if doc_type == "proposta_daycoval" and f == "nome_financiado" and data.get("nome"):
                                continue
                            missing_required.append(f)
                with st.expander(f"📌 {doc_type} — dados extraídos", expanded=True):
                    if missing_required:
                        st.warning(
                            "Não foi possível extrair campos mínimos deste documento. "
                            "Sem isso, algumas validações ficam pendentes."
                        )
                        st.write("**Campos mínimos esperados:**")
                        for f in required_fields:
                            st.write(f"- {f}")
                        st.write("**Campos mínimos não encontrados:**")
                        for f in missing_required:
                            st.write(f"- {f}")

                    if display:
                        _present_kv("Campos principais extraídos", display)
                    else:
                        st.write(
                            "O documento foi coletado, mas não há campos reconhecidos na whitelist para exibição "
                            "ou o parser não produziu dados esperados."
                        )

                    # Diagnostico objetivo do motivo mais comum (OCR indisponivel)
                    if isinstance(extractor_dbg, dict):
                        ocr_err = extractor_dbg.get("ocr_error")
                        if isinstance(ocr_err, str) and ("pytesseract" in ocr_err or "ModuleNotFoundError" in ocr_err):
                            st.error(
                                "OCR indisponível no ambiente Python atual (pytesseract não instalado). "
                                "Instale as dependências do projeto e reinicie a UI."
                            )
                            st.code("python3 -m pip install -r requirements.txt")

                    if parse_error:
                        st.error(f"Parse error: {parse_error}")

                    # Link técnico (sem expor por padrão, mas fica aqui)
                    st.caption(f"Fonte (técnico): {payload.get('path')}")

                    with st.expander("Debug de extração/parsing (técnico)", expanded=False):
                        st.json({
                            "extractor": extractor_dbg,
                            "parser": debug.get("parser") if isinstance(debug, dict) else None,
                        })

        # Também mostra explicitamente “o que foi usado nos checks”
        used_by_checks = _summarize_data_used_by_checks(report)
        if used_by_checks:
            with st.expander("O que foi usado nas validações (explicação objetiva)", expanded=True):
                for k, v in used_by_checks.items():
                    st.write(f"- **{k}**: {v}")

        st.divider()

        # ============================================================
        # Parecer humano (checks)
        # ============================================================
        st.subheader("Parecer consolidado")

        checks = report.get("checks") or []
        if not isinstance(checks, list):
            checks = []

        overall_status = (report.get("overall_status") or report.get("status") or "WARN").upper()
        grouped = _group_checks(checks)
        missing_docs = _summarize_missing_docs_from_checks(checks)

        st.info(_human_overall_message(overall_status, missing_docs))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("OK", len(grouped["OK"]))
        c2.metric("Atenção", len(grouped["WARN"]))
        c3.metric("Inconsistências", len(grouped["FAIL"]))
        c4.metric("Faltando", len(grouped["MISSING"]))

        if missing_docs:
            st.markdown("**O que está faltando (alto nível):**")
            for md in missing_docs:
                st.write(f"- {md}")

        st.divider()

        def render_section(title: str, items: List[Dict[str, Any]]):
            st.markdown(f"### {title}")
            if not items:
                st.write("Nenhum item.")
                return
            for c in items:
                cid = c.get("id", "(sem id)")
                status = (c.get("status") or "").upper()
                msg = c.get("message") or c.get("title") or ""
                header = f"{_status_emoji(status)} {cid}"
                if msg:
                    header += f" — {msg}"
                with st.expander(header, expanded=False):
                    st.json(c)

        render_section("O que foi validado (OK)", grouped["OK"])
        render_section("Pontos de atenção (WARN)", grouped["WARN"])
        render_section("Inconsistências (FAIL)", grouped["FAIL"])
        render_section("Documentos / evidências faltantes (MISSING)", grouped["MISSING"])

        # Download do report.json (técnico)
        st.divider()
        st.download_button(
            "Download do relatório (report.json)",
            data=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="report.json",
            mime="application/json",
        )

        with st.expander("Detalhes técnicos (opcional)", expanded=False):
            st.write(f"case_id interno: `{case_id}`")
            st.write(f"uploads temporários: `{TMP_UPLOADS_DIR / case_id}`")
            st.write(f"phase1 storage: `{PHASE1_ROOT / case_id}`")
            st.write(f"phase2 storage: `{PHASE2_ROOT / case_id}`")

        st.divider()
        if st.button("Reiniciar (novo envio)", type="secondary"):
            st.session_state.pop("active_case_id", None)
            st.rerun()

else:
    st.caption("Envie ao menos um arquivo para iniciar.")
