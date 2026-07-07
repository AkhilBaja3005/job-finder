import os
import time
import random
import asyncio
import threading
import json
import urllib.request
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types
from typing import Optional, Callable, Dict

from utils.ssl_utils import SSL_CONTEXT as _SSL_CONTEXT

# ─────────────────────────────────────────────────────────────────────────────
# Global Configurations & Provider Layout Models
# ─────────────────────────────────────────────────────────────────────────────
CLOUDFLARE_DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
CLOUDFLARE_MAX_TOKENS = 8192

PROVIDERS = [
    {"name": "anthropic",   "key_prefix": "sk-ant-",  "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"]},
    {"name": "groq",        "key_prefix": "gsk_",     "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]},
    {"name": "openrouter",  "key_prefix": "sk-or-",   "models": ["google/gemini-2.5-flash", "google/gemini-2.5-flash-lite"]},
    {"name": "nvidia",      "key_prefix": "nvapi-",   "models": ['meta/llama-3.1-8b-instruct', "meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct", "mistralai/mixtral-8x22b-instruct-v0.1"]},
    {"name": "gemini",      "key_prefix": "AIza",     "models": ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.0-flash"]},
]

# Updated for low-latency resume generation and screening pipelines
# Cleaned: Removed invalid catalog tracks to speed up response routing
NVIDIA_FALLBACK_MODELS = [
    'meta/llama-3.1-8b-instruct',
    'meta/llama-3.3-70b-instruct',
]

JSON_FALLBACK_MODELS = [
    'gemini-3.1-flash-lite',
    'gemini-2.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.0-flash',
]

LATEX_FALLBACK_MODELS = [
    'gemini-2.5-flash',
    'gemini-3.1-flash-lite',
    'gemini-2.0-flash',
]

GROQ_FALLBACK_MODELS = [
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
    'mixtral-8x7b-32768',
    'gemma2-9b-it',
]

# ─────────────────────────────────────────────────────────────────────────────
# Helper & Cleanup Functions
# ─────────────────────────────────────────────────────────────────────────────
def clean_schema(schema: dict, inside_properties: bool = False) -> dict:
    """
    Recursively cleans a JSON schema for Gemini/LLM engine compatibility.
    """
    if isinstance(schema, dict) and "$defs" in schema:
        schema = dict(schema)
        defs = schema.pop("$defs")

        def _resolve_refs(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    ref_path = node.pop("$ref")
                    ref_key = ref_path.split("/")[-1]
                    node.update(_resolve_refs(defs[ref_key]))
                elif "allOf" in node and len(node["allOf"]) == 1:
                    wrapped = node.pop("allOf")
                    resolved = _resolve_refs(wrapped[0])
                    for k, v in resolved.items():
                        node.setdefault(k, v)
                for k, v in list(node.items()):
                    node[k] = _resolve_refs(v)
            elif isinstance(node, list):
                node = [_resolve_refs(item) for item in node]
            return node

        schema = _resolve_refs(schema)

    if isinstance(schema, dict):
        schema.pop("additionalProperties", None)
        if not inside_properties and isinstance(schema.get("title"), str):
            schema.pop("title", None)
        result = {}
        for k, v in schema.items():
            result[k] = clean_schema(v, inside_properties=(k == "properties")) if isinstance(v, dict) else (
                [clean_schema(i) if isinstance(i, dict) else i for i in v] if isinstance(v, list) else v
            )
        return result
    elif isinstance(schema, list):
        return [clean_schema(item) if isinstance(item, dict) else item for item in schema]
    else:
        return schema


def get_gemini_client(custom_api_key: Optional[str] = None) -> genai.Client:
    api_key = custom_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


# ─────────────────────────────────────────────────────────────────────────────
# Proactive per-model RPM throttle (native Gemini only)
# ─────────────────────────────────────────────────────────────────────────────
# gemini-3.1-flash-lite is first in JSON_FALLBACK_MODELS, so with
# NVIDIA/Cloudflare disabled (the common local/dev config), nearly every LLM
# call in the app — resume parsing, per-job JD cleanup during discovery
# (several jobs scored concurrently), tailoring, the recruiter reviewer,
# autofill Q&A — funnels through this one model. The free/low tier for this
# model is commonly capped at 15 requests/minute; reacting to a 429 after the
# fact (the existing _cooperative_sleep retry) doesn't prevent a burst of
# concurrent calls from collectively exceeding that cap before any single one
# sees an error. This tracks call timestamps per model and cooperatively
# sleeps before making a call if the model is already at its RPM ceiling.
GEMINI_MODEL_RPM_LIMITS = {
    "gemini-3.1-flash-lite": 15,
    "gemini-2.5-flash": 5
}
_rpm_call_log: Dict[str, list] = {}
_rpm_lock = threading.Lock()

def _throttle_for_rpm(model_name: str) -> None:
    limit = GEMINI_MODEL_RPM_LIMITS.get(model_name)
    if not limit:
        return
    while True:
        with _rpm_lock:
            now = time.time()
            calls = [t for t in _rpm_call_log.get(model_name, []) if now - t < 60]
            if len(calls) < limit:
                calls.append(now)
                _rpm_call_log[model_name] = calls
                return
            wait_for = 60 - (now - calls[0]) + 0.1
        _cooperative_sleep(min(wait_for, 60))


def _cooperative_sleep(seconds: float) -> None:
    # Add jitter (±25%) so concurrent requests that all hit a rate limit at
    # the same moment don't retry in lockstep and immediately re-trigger the
    # same rate limit together.
    seconds = seconds * random.uniform(0.75, 1.25)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    remaining = seconds
    step = 0.5
    while remaining > 0:
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(asyncio.sleep(step), loop)
            try:
                future.result(timeout=step * 2)
            except Exception:
                time.sleep(step)
        else:
            time.sleep(step)
        remaining -= step


def _cloudflare_configured() -> bool:
    if os.getenv("CLOUDFLARE_DISABLED", "").strip() in ("1", "true", "True"):
        return False
    return bool(os.getenv("CLOUDFLARE_API_KEY") and os.getenv("CLOUDFLARE_ACCOUNT_ID"))

def _nvidia_configured() -> bool:
    if os.getenv("NVIDIA_DISABLED", "").strip() in ("1", "true", "True"):
        return False
    return bool(os.getenv("NVIDIA_API_KEY"))

# ─────────────────────────────────────────────────────────────────────────────
# Core Logic Engine and Cascading Routine
# ─────────────────────────────────────────────────────────────────────────────
def _generate_with_model_list(
    prompt: str,
    model_list: list,
    response_schema=None,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Core generation function. Executes a strict prioritized fallback pipeline:
    NVIDIA NIM ──> Cloudflare Workers AI ──> Native Gemini Client
    
    If a specific `custom_api_key` is passed directly to the function, that 
    provider is prioritized immediately.
    """
    # ── OVERRIDE CHECK: Manual Specific Key Provided ─────────────────────────
    if custom_api_key:
        if custom_api_key.startswith("nvapi-"):
            print("[LLM Client] Priority override: Explicit NVIDIA key provided.")
            try:
                return _execute_nvidia_nim_fallback(prompt, response_schema, custom_api_key, on_log)
            except Exception as e:
                print(f"[LLM Client] Override NVIDIA failed: {e}. Falling back to standard pipeline...")
        
        elif custom_api_key.startswith("sk-ant-"):
            try: return _execute_anthropic(prompt, response_schema, custom_api_key)
            except Exception as e: print(f"[LLM Client] Override Anthropic failed: {e}. Falling back to standard pipeline...")
        elif custom_api_key.startswith("gsk_"):
            try: return _execute_groq(prompt, response_schema, custom_api_key)
            except Exception as e: print(f"[LLM Client] Override Groq failed: {e}. Falling back to standard pipeline...")
        elif custom_api_key.startswith("sk-or-"):
            try: return _execute_openrouter(prompt, model_list, response_schema, custom_api_key, on_log)
            except Exception as e: print(f"[LLM Client] Override OpenRouter failed: {e}. Falling back to standard pipeline...")

    # ── STAGE 1: NVIDIA NIM (First General Checkpoint) ───────────────────────
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    if _nvidia_configured():
        try:
            # Internal execution now tests validation natively before returning text
            return _execute_nvidia_nim_fallback(prompt, response_schema, nvidia_api_key, on_log)
        except Exception as nv_err:
            print(f"[LLM Client] Stage 1 (NVIDIA NIM) failed or hit validation error: {str(nv_err)[:120]}. Falling back to Stage 2...")
            if on_log:
                on_log(json.dumps({"type": "llm_warn", "provider": "nvidia", "message": f"NVIDIA failed: {str(nv_err)[:100]}"}))

    # ── STAGE 2: Cloudflare Workers AI (Second Checkpoint) ───────────────────
    if _cloudflare_configured():
        try:
            # Internal execution now validates response schema before dropping back
            return _generate_with_cloudflare_llama(prompt, response_schema, on_log)
        except Exception as cf_err:
            print(f"[LLM Client] Stage 2 (Cloudflare) failed or hit validation error: {str(cf_err)[:120]}. Falling back to Stage 3...")
            if on_log:
                on_log(json.dumps({"type": "llm_warn", "provider": "cloudflare", "message": f"Cloudflare failed: {str(cf_err)[:100]}"}))

    # ── STAGE 3: Native Gemini Client (Final Fallback Floor) ─────────────────
    gemini_key = custom_api_key if (custom_api_key and custom_api_key.startswith("AIza")) else os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("Pipeline dropped to final floor, but GEMINI_API_KEY environment variable is missing.")

    client = get_gemini_client(gemini_key)
    config_args = {"temperature": 0.1}
    if response_schema is not None:
        config_args["response_mime_type"] = "application/json"
        config_args["response_schema"] = clean_schema(response_schema.model_json_schema())

    last_error = None
    for model_name in model_list:
        for retry_attempt in range(3):
            try:
                _throttle_for_rpm(model_name)
                if on_log:
                    on_log(json.dumps({"type": "llm_info", "message": f"🤖 Attempting Gemini model {model_name} (try {retry_attempt + 1})..."}))
                print(f"Attempting generation with model: {model_name} (try {retry_attempt + 1})...")

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_args),
                )
                text = response.text
                if not text or not text.strip():
                    break # Try next variant shape model in list
                return text
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if any(x in err_str for x in ["429", "quota", "rate limit", "resource_exhausted"]):
                    _cooperative_sleep(10)
                    continue
                break # Non-rate-limit client problems move strictly forward to downstream models

    raise RuntimeError(f"All sequence pipelines and model alternatives exhausted. Final floor exception: {last_error}")
# ─────────────────────────────────────────────────────────────────────────────
# Standalone Provider-Specific Implementations
# ─────────────────────────────────────────────────────────────────────────────

import ast
import re

def _execute_nvidia_nim_fallback(prompt: str, response_schema, api_key: str, on_log: Optional[Callable[[str], None]]) -> str:
    last_error = None
    for model_name in NVIDIA_FALLBACK_MODELS:
        for retry_attempt in range(3):
            try:
                if on_log:
                    on_log(json.dumps({"type": "llm_info", "message": f"🤖 Attempting NVIDIA NIM model {model_name}..."}))
                print(f"Attempting NVIDIA NIM generation with model: {model_name} (try {retry_attempt + 1})...")
                
                url = "https://integrate.api.nvidia.com/v1/chat/completions".strip().lstrip("[")
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                messages = [{"role": "user", "content": prompt}]
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 4096,
                }
                
                if response_schema is not None:
                    payload["response_format"] = {"type": "json_object"}
                    schema_dict = clean_schema(response_schema.model_json_schema())
                    properties = schema_dict.get("properties", {})
                    
                    example_obj = {}
                    for field, metadata in properties.items():
                        if "properties" in metadata or metadata.get("type") == "object":
                            sub_props = metadata.get("properties", {})
                            sub_obj = {}
                            for sub_field, sub_meta in sub_props.items():
                                if sub_meta.get("type") == "array" or "items" in sub_meta:
                                    sub_obj[sub_field] = ["entry_string_1", "entry_string_2"]
                                else:
                                    sub_obj[sub_field] = "flat_string_value"
                            example_obj[field] = sub_obj
                        elif metadata.get("type") == "array" or "items" in metadata:
                            example_obj[field] = ["entry_string_1", "entry_string_2"]
                        else:
                            example_obj[field] = "flat_string_value"
                    
                    messages[0]["content"] += (
                        f"\n\n[CRITICAL OUTPUT RULES]"
                        f"\nYou must respond ONLY with a raw JSON object string structured exactly like this pattern layout:"
                        f"\n{json.dumps(example_obj, indent=2)}"
                        f"\n\nSTRICT RECRUITING DATA TYPE FORMAT RULES:"
                        f"\n1. Arrays and lists MUST be true native JSON arrays, e.g., [\"A\", \"B\"]. Never wrap a whole list in quotes to turn it into a string."
                        f"\n2. Do NOT map data frames or experience updates under custom dynamic keys like 'Qualcomm'."
                        f"\n3. Do NOT use markdown ```json block wrappers."
                    )

                req_data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, headers=headers, data=req_data, method="POST")

                with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=35) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    text = result["choices"][0]["message"]["content"]
                    
                    if text and text.strip():
                        text_str = str(text).strip()
                        
                        # ─────────────────────────────────────────────────────────────────
                        # PRE-VALIDATION REPAIR ENGINE
                        # ─────────────────────────────────────────────────────────────────
                        if response_schema is not None:
                            try:
                                # Parse to raw dictionary to scrub layout bugs before validation processing
                                data_dict = json.loads(text_str)
                                
                                # Fix 1: Resolve stringified arrays (e.g., input_value="['A', 'B']")
                                for key, val in data_dict.items():
                                    if isinstance(val, str) and val.strip().startswith("[") and val.strip().endswith("]"):
                                        try:
                                            data_dict[key] = ast.literal_eval(val)
                                        except Exception:
                                            pass
                                    
                                    # Fix 2: Handle nested structural properties (like suggested_resume_updates)
                                    if isinstance(val, dict):
                                        for sub_key, sub_val in val.items():
                                            if isinstance(sub_val, str) and sub_val.strip().startswith("[") and sub_val.strip().endswith("]"):
                                                try:
                                                    val[sub_key] = ast.literal_eval(sub_val)
                                                except Exception:
                                                    pass
                                            
                                            # Fix 3: Standardize structured dictionaries back to flat list arrays if a collection is inverted
                                            # e.g., transforming {"Qualcomm": ["bullet1"]} -> ["bullet1"]
                                            if sub_key in ["experience", "projects", "skills"] and isinstance(sub_val, dict):
                                                flattened_list = []
                                                for k, v in sub_val.items():
                                                    if isinstance(v, list):
                                                        flattened_list.extend(v)
                                                    else:
                                                        flattened_list.append(str(v))
                                                val[sub_key] = flattened_list
                                                
                                            # Fix 4: If an array of objects gets converted into a dictionary of objects
                                            if sub_key == "projects" and isinstance(sub_val, list):
                                                for idx, item in enumerate(sub_val):
                                                    if isinstance(item, dict) and "title" in item and len(item) == 1:
                                                        # If the structure is corrupted like {'title': 'Project Name'}, keep it valid
                                                        pass
                                
                                text_str = json.dumps(data_dict)
                            except Exception as parse_err:
                                print(f"[LLM Client] Pre-validation parser skipped remediation: {parse_err}")

                            # Execute strict Pydantic parsing test
                            response_schema.model_validate_json(text_str)
                        return text_str
            except Exception as model_err:
                last_error = model_err
                print(f"[LLM Client] NVIDIA NIM model {model_name} processing anomaly: {model_err}")
                if "429" in str(model_err) or "rate_limit" in str(model_err).lower():
                    _cooperative_sleep(5)
                    continue
                break 
    raise RuntimeError(f"NVIDIA NIM processing sequence crashed: {last_error}")

def _generate_with_cloudflare_llama(prompt: str, response_schema=None, on_log: Optional[Callable[[str], None]] = None) -> str:
    api_key = os.getenv("CLOUDFLARE_API_KEY")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    model = CLOUDFLARE_DEFAULT_MODEL

    user_content = prompt
    system_prompt = "You are an expert recruiter AI system. You output raw JSON only, matching structural types perfectly."
    
    if response_schema is not None:
        schema_dict = clean_schema(response_schema.model_json_schema())
        system_prompt += f"\nOutput a single flat JSON object complying strictly with this structure:\n{json.dumps(schema_dict)}"
        user_content += (
            "\n\nDATA TYPE RULE COMPLIANCE:"
            "\n- 'cover_letter' must be a basic string payload value, NOT an object."
            "\n- Lists must be structural flat JSON arrays `[...]` only."
            "\n- Return raw string payload contents only. Do NOT wrap inside backticks or backslash escape patterns."
        )

    if on_log:
        on_log(json.dumps({"type": "llm_info", "message": f"🤖 Attempting Cloudflare Workers AI model {model}..."}))
    print(f"[LLM Client] Attempting Cloudflare Workers AI model: {model}...")

    # Fixed: Forced strict string sanitization to eliminate the `<urlopen error unknown url type: [https>` block completely
    url = f"[https://api.cloudflare.com/client/v4/accounts/](https://api.cloudflare.com/client/v4/accounts/){account_id}/ai/run/{model}".strip().lstrip("[")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=req_data, method="POST")

    with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=45) as response:
        resp_body = response.read().decode("utf-8")
    result = json.loads(resp_body)

    if not result.get("success", True):
        errs = result.get("errors") or result.get("error")
        raise RuntimeError(f"Cloudflare returned success=false: {errs}")

    res = result.get("result", {}) or {}
    text = ""
    if isinstance(res, dict):
        if isinstance(res.get("choices"), list) and res["choices"]:
            text = res["choices"][0].get("message", {}).get("content", "")
        if not text and isinstance(res.get("response"), dict):
            text = res["response"].get("content", "") or ""
        if not text:
            raw = res.get("response") or res.get("content")
            if isinstance(raw, str):
                text = raw

    if not text or not str(text).strip():
        raise RuntimeError(f"Cloudflare returned empty response body: {resp_body[:300]}")

    text_str = str(text).strip()
    
    if response_schema is not None:
        try:
            response_schema.model_validate_json(text_str)
        except Exception as schema_err:
            raise RuntimeError(f"Cloudflare pipeline response failed structural parsing check: {schema_err}")

    print(f"[LLM Client] Cloudflare generation successful with: {model}")
    return text_str

def _execute_anthropic(prompt: str, response_schema, api_key: str) -> str:
    # pyrefly: ignore [missing-import]
    import anthropic
    anthropic_client = anthropic.Anthropic(api_key=api_key)
    is_latex_or_review = (response_schema is None or "latex" in prompt.lower())
    claude_model = "claude-3-5-sonnet-latest" if is_latex_or_review else "claude-3-5-haiku-latest"
    
    messages = [{"role": "user", "content": prompt}]
    system_prompt = "You are an expert recruiter AI system."
    if response_schema is not None:
        schema_json = json.dumps(clean_schema(response_schema.model_json_schema()), indent=2)
        system_prompt += f"\nReturn ONLY a raw JSON object string that complies strictly with this JSON schema:\n{schema_json}"
        messages[0]["content"] += "\nEnsure your response is valid JSON and starts with '{' and ends with '}'."

    completion = anthropic_client.messages.create(
        model=claude_model, max_tokens=4096, temperature=0.1, system=system_prompt, messages=messages
    )
    return completion.content[0].text


def _execute_groq(prompt: str, response_schema, api_key: str) -> str:
    # pyrefly: ignore [missing-import]
    from groq import Groq
    groq_client = Groq(api_key=api_key)
    groq_error = None
    for groq_model in GROQ_FALLBACK_MODELS:
        for retry_attempt in range(3):
            try:
                messages = [{"role": "user", "content": prompt}]
                payload_args = {"model": groq_model, "messages": messages, "temperature": 0.1}
                if response_schema is not None:
                    payload_args["response_format"] = {"type": "json_object"}
                    schema_json = json.dumps(clean_schema(response_schema.model_json_schema()), indent=2)
                    messages[0]["content"] += f"\n\nCRITICAL: You must return a JSON object that adheres strictly to this JSON schema:\n{schema_json}"

                completion = groq_client.chat.completions.create(**payload_args)
                return completion.choices[0].message.content
            except Exception as model_err:
                err_str = str(model_err).lower()
                if any(x in err_str for x in ["429", "rate_limit", "quota", "limit exceeded"]):
                    _cooperative_sleep(10)
                    continue
                groq_error = model_err
                break
    raise RuntimeError(f"All Groq models failed. Last error: {groq_error}")


def _execute_openrouter(prompt: str, model_list: list, response_schema, api_key: str, on_log: Optional[Callable[[str], None]]) -> str:
    or_model_map = {
        'gemini-3.1-flash-lite': 'google/gemini-2.5-flash-lite',
        'gemini-2.5-flash-lite': 'google/gemini-2.5-flash-lite',
        'gemini-2.5-flash': 'google/gemini-2.5-flash',
        'gemini-2.0-flash': 'google/gemini-2.5-flash',
    }
    last_error = None
    for model_name in model_list:
        or_model = or_model_map.get(model_name, 'google/gemini-2.5-flash')
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            url = url.lstrip("[")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/AkhilBaja3005/job-finder",
                "X-Title": "Job Finder Resume Tailor"
            }
            payload = {"model": or_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
            if response_schema is not None:
                payload["response_format"] = {"type": "json_object", "schema": clean_schema(response_schema.model_json_schema())}

            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, headers=headers, data=req_data, method="POST")
            with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"All OpenRouter alternatives failed. Last error: {last_error}")

# ─────────────────────────────────────────────────────────────────────────────
# High-Level Entrypoints
# ─────────────────────────────────────────────────────────────────────────────
def generate_content_with_fallback(
    prompt: str,
    response_schema=None,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """JSON / structured output generation via fallback list."""
    return _generate_with_model_list(
        prompt, JSON_FALLBACK_MODELS, response_schema, custom_api_key, on_log
    )


def generate_latex_with_strong_model(
    prompt: str,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Raw text/LaTeX generation without predefined model schemas."""
    return _generate_with_model_list(
        prompt, LATEX_FALLBACK_MODELS, response_schema=None, custom_api_key=custom_api_key, on_log=on_log
    )