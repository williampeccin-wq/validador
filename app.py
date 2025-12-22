import os
import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from core.ocr import extract_text_any, diagnose_environment
from core.gemini_client import gemini_enabled

from parsers.cnh import analyze_cnh
from parsers.holerite import analyze_holerite
from parsers.extrato import analyze_extrato
from parsers.proposta_daycoval import analyze_proposta_daycoval
from parsers.residencia import analyze_residencia


# ============================================================
# Config UI
# ============================================================
st.set_page_config(page_title="Validador de Documentos — MVP", layout="wide")
st.title("Validador de Documentos — MVP (CNH/Proposta/Residência/Holerite/Extrato)")


# ============================================================
# Helpers (simples e determinísticos)
# ============================================================
_UFS = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}

def _upper(s: str) -> str:
    return (s or "").upper()

def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _parse_date(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    try:
        dd, mm, yyyy = d.strip().split("/")
        return date(int(yyyy), int(mm), int(dd))
    except Exception:
        return None

def _guess_kind(filename: str, text: str) -> str:
    """
    Classificação determinística por palavras-chave (sem IA).
    Observação importante: sempre compara em UPPER para evitar bugs.
    """
    fn = (filename or "").lower()
    up = _upper(text)

    # CNH
    if ("cnh" in fn) or ("CARTEIRA NACIONAL DE HABIL" in up) or ("SENATRAN" in up) or ("ASSINADOR SERPRO" in up):
        return "cnh"

    # Proposta Daycoval
    if ("daycoval" in fn) or ("PLANILHA DE PROPOSTA" in up) or ("BANCO DAYCOVAL" in up) or re.search(r"\bPROPOSTA:\s*\d{6,}\b", up):
        return "proposta"

    # Residência (conta/luz/água etc)
    if ("celesc" in fn) or ("SEGUNDA VIA" in up and "ENDERECO" in up) or ("UNIDADE CONSUMIDORA" in up) or ("NOME:" in up and "CEP:" in up and "CIDADE:" in up):
        return "residencia"

    # Holerite
    if ("holerite" in fn) or ("RECIBO DE PAGAMENTO" in up) or ("PAGAMENTO DE SALARIO" in up) or ("ADM.:" in up and "SALARIO" in up):
        return "holerite"

    # Extrato
    if ("extrato" in fn) or ("EXTRATO POR PERIODO" in up) or ("LANCAMENTOS" in up) or ("HISTORICO/COMPLEMENTO" in up) or ("SALDO ANTERIOR" in up):
        return "extrato"

    return "desconhecido"


def _required_fields_for(kind: str) -> List[str]:
    if kind == "cnh":
        return ["nome", "cpf", "data_nascimento", "validade"]
    if kind == "proposta":
        return ["proposta", "nome_financiado", "cpf", "data_nascimento"]
    if kind == "residencia":
        return ["nome_titular", "endereco", "cep", "cidade", "uf", "vencimento"]
    if kind == "holerite":
        return ["nome", "empregador", "data_admissao", "total_vencimentos"]
    if kind == "extrato":
        return ["titular", "agencia", "conta", "periodo_inicio", "periodo_fim", "lancamentos"]
    return []


def _missing(fields: Dict[str, Any], required: List[str]) -> List[str]:
    miss = []
    for k in required:
        v = fields.get(k)
        if v is None:
            miss.append(k)
        elif isinstance(v, str) and not v.strip():
            miss.append(k)
        elif isinstance(v, list) and len(v) == 0:
            miss.append(k)
    return miss


def _critique_cnh(fields: Dict[str, Any]) -> List[str]:
    notes: List[str] = []

    cpf = _only_digits(fields.get("cpf") or "")
    if cpf and len(cpf) != 11:
        notes.append(f"CPF com tamanho inválido: {fields.get('cpf')}")

    uf = (fields.get("uf_nascimento") or "").strip().upper()
    if uf and uf not in _UFS:
        notes.append(f"UF de nascimento suspeita: {uf}")

    validade = _parse_date(fields.get("validade"))
    if validade:
        # regra: validade precisa ser pelo menos hoje + 30 dias (seu caso de uso inicial)
        if validade < (date.today() + timedelta(days=30)):
            notes.append(f"CNH vencida ou vencendo em menos de 30 dias: validade {fields.get('validade')}")
        # regra sanidade: validade absurda (ex.: 2087)
        if validade > (date.today() + timedelta(days=365*25)):
            notes.append(f"Validade da CNH parece absurda (provável OCR): {fields.get('validade')}")
    else:
        notes.append("Validade não encontrada ou inválida.")

    nasc = _parse_date(fields.get("data_nascimento"))
    if nasc and nasc > date.today():
        notes.append(f"Data de nascimento no futuro (provável OCR): {fields.get('data_nascimento')}")

    return notes


def _critique_residencia(fields: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    uf = (fields.get("uf") or "").strip().upper()
    if uf and uf not in _UFS:
        notes.append(f"UF no comprovante suspeita: {uf}")
    return notes


def _compare_cross(doc_a: str, a: Dict[str, Any], doc_b: str, b: Dict[str, Any]) -> List[str]:
    """
    Comparações simples entre docs quando ambos existem:
    - CPF (proposta vs CNH)
    - Data de nascimento (proposta vs CNH)
    - Nome (proposta vs CNH) comparação fraca via inclusão / tokens
    """
    notes: List[str] = []

    def tokset(name: str) -> set:
        return set(re.findall(r"[A-Z]{2,}", (name or "").upper()))

    # CPF
    cpf_a = _only_digits(a.get("cpf") or "")
    cpf_b = _only_digits(b.get("cpf") or "")
    if cpf_a and cpf_b and cpf_a != cpf_b:
        notes.append(f"CPF divergente entre {doc_a} e {doc_b}: {cpf_a} vs {cpf_b}")

    # Data nascimento
    dn_a = a.get("data_nascimento")
    dn_b = b.get("data_nascimento")
    if dn_a and dn_b and dn_a != dn_b:
        notes.append(f"Data de nascimento divergente entre {doc_a} e {doc_b}: {dn_a} vs {dn_b}")

    # Nome (bem conservador)
    name_a = a.get("nome") or a.get("nome_financiado") or ""
    name_b = b.get("nome") or b.get("nome_financiado") or ""
    if name_a and name_b:
        ta, tb = tokset(name_a), tokset(name_b)
        if ta and tb:
            inter = len(ta.intersection(tb))
            union = len(ta.union(tb))
            sim = inter / union if union else 0.0
            if sim < 0.6:
                notes.append(f"Nome possivelmente divergente entre {doc_a} e {doc_b} (similaridade baixa): '{name_a}' vs '{name_b}'")

    return notes


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.subheader("Status / Ambiente")
    st.write("parsers.cnh: ✅")
    st.write(f"gemini_client: {'✅' if gemini_enabled() else '⚠️ (sem GEMINI_API_KEY)'}")

    st.divider()
    st.subheader("Configurar OCR (se necessário)")

    default_tesseract = os.getenv("TESSERACT_CMD", "/opt/homebrew/bin/tesseract")
    default_poppler = os.getenv("POPPLER_PATH", "/opt/homebrew/bin")

    tesseract_cmd = st.text_input("Caminho TESSERACT_CMD", value=default_tesseract)
    poppler_path = st.text_input("POPPLER_PATH (pasta que contém pdftoppm)", value=default_poppler)

    min_text_len_threshold = st.number_input("min_text_len_threshold", min_value=0, max_value=5000, value=800, step=50)
    ocr_dpi = st.number_input("ocr_dpi (PDF->imagem)", min_value=100, max_value=600, value=350, step=50)

    st.divider()
    if st.button("Diagnóstico de Ambiente"):
        st.json(diagnose_environment(tesseract_cmd=tesseract_cmd, poppler_path=poppler_path))


# ============================================================
# Main
# ============================================================
st.markdown(
    """
Envie arquivos **PDF/JPG/PNG**.

- **CNH**: OCR + REGEX + (Gemini opcional)  
- **Proposta Daycoval**: PDF nativo (pdfplumber) + REGEX  
- **Comprovante de Residência**: PDF nativo + REGEX  
- **Holerite**: OCR + REGEX  
- **Extrato**: OCR + REGEX (lista de lançamentos)  
"""
)

uploads = st.file_uploader(
    "Envie documentos (CNH/Proposta/Residência/Holerite/Extrato)",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True
)

# Armazena resultados por tipo para comparações cruzadas
doc_results: Dict[str, Dict[str, Any]] = {}

if uploads:
    st.subheader("Arquivos enviados")
    for up in uploads:
        st.write(f"- {up.name}")

    st.divider()

    for idx, up in enumerate(uploads, start=1):
        file_bytes = up.getvalue()
        filename = up.name

        with st.expander(f"{idx}. {filename}", expanded=True):
            # 1) extrair texto
            text, src_dbg = extract_text_any(
                file_bytes=file_bytes,
                filename=filename,
                tesseract_cmd=tesseract_cmd,
                poppler_path=poppler_path,
                min_text_len_threshold=int(min_text_len_threshold),
                ocr_dpi=int(ocr_dpi),
            )

            # 2) classificar
            kind = _guess_kind(filename, text)
            st.write(f"Classificação — **{filename} → {kind}**")
            st.caption(f"Extrator usado: {src_dbg.get('debug_src')}")

            # 3) parse + crítica mínima
            fields: Dict[str, Any] = {}
            dbg: Dict[str, Any] = {}

            if kind == "cnh":
                fields, dbg = analyze_cnh(raw_text=text or "", filename=filename, use_gemini=True)

            elif kind == "proposta":
                fields = analyze_proposta_daycoval(text or "")

            elif kind == "residencia":
                fields = analyze_residencia(text or "")

            elif kind == "holerite":
                fields = analyze_holerite(text or "")

            elif kind == "extrato":
                fields = analyze_extrato(text or "")

            else:
                st.warning("Tipo não reconhecido. Exibindo texto inicial para diagnóstico.")
                st.text((text or "")[:1500])

            # Se reconheceu, mostra resultado estruturado + crítica
            if kind != "desconhecido":
                # Guarda para cruzar depois (apenas um por tipo, por enquanto)
                doc_results[kind] = fields

                required = _required_fields_for(kind)
                miss = _missing(fields, required)

                st.subheader("Resultado estruturado")
                st.json(fields)

                st.subheader("Crítica (mínima)")
                crit: List[str] = []
                if miss:
                    crit.append(f"Campos ausentes: {', '.join(miss)}")

                if kind == "cnh":
                    crit.extend(_critique_cnh(fields))
                elif kind == "residencia":
                    crit.extend(_critique_residencia(fields))

                if crit:
                    for c in crit:
                        st.error(c)
                else:
                    st.success("Sem críticas mínimas; campos obrigatórios presentes e sanidade OK.")

            # Debug toggles (sem expanders aninhados)
            if st.checkbox("Mostrar fonte do texto (debug do extrator)", key=f"show_srcdbg_{idx}", value=False):
                st.json({
                    "debug_src": src_dbg.get("debug_src"),
                    "pages": src_dbg.get("pages"),
                    "tamanho_texto": src_dbg.get("text_len"),
                    "ocr_retry": src_dbg.get("ocr_retry"),
                })

            if st.checkbox("Mostrar texto (início)", key=f"show_text_{idx}", value=False):
                st.text((text or "")[:2000])

            if dbg and st.checkbox("Mostrar debug do parser", key=f"show_dbg_{idx}", value=False):
                st.json(dbg)

    # ============================================================
    # Comparações cruzadas (quando tiver mais de um doc)
    # ============================================================
    st.divider()
    st.subheader("Comparações cruzadas (quando aplicável)")

    cross_notes: List[str] = []
    if "proposta" in doc_results and "cnh" in doc_results:
        cross_notes.extend(_compare_cross("proposta", doc_results["proposta"], "cnh", doc_results["cnh"]))

    if cross_notes:
        for n in cross_notes:
            st.error(n)
    else:
        st.info("Sem comparações aplicáveis (ou nenhuma divergência detectada).")
