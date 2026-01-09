import os
import json
from typing import Dict, Any, Optional

try:
    import google.generativeai as genai
except Exception:
    genai = None


def gemini_enabled() -> bool:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return bool(key) and (genai is not None)


def gemini_structured_json(
    prompt: str,
    model_name: str = "gemini-1.5-flash",
    max_output_tokens: int = 1024,
) -> Dict[str, Any]:
    """
    Executa Gemini e tenta retornar um JSON (dict).
    Retorna {"_error": "...", "raw": "..."} em caso de falha.
    """
    if not gemini_enabled():
        return {"_error": "gemini_not_enabled", "raw": None}

    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": max_output_tokens,
                "temperature": 0.0,
            },
        )
        raw = (resp.text or "").strip()
        if not raw:
            return {"_error": "empty_response", "raw": ""}

        # tenta extrair JSON mesmo se vier com lixo em volta
        parsed = _best_effort_json(raw)
        if parsed is None:
            return {"_error": "json_parse_failed", "raw": raw}
        return parsed

    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}", "raw": None}


def _best_effort_json(raw: str) -> Optional[Dict[str, Any]]:
    raw = raw.strip()

    # caso venha puro
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # tenta achar um bloco {...}
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        chunk = raw[start:end + 1]
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None

    return None
