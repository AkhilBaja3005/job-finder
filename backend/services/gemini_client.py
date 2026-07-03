import os
import time
# pyrefly: ignore [missing-import]
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import types
# pyrefly: ignore [missing-import]
import google.api_core.exceptions
from typing import Optional, Callable
import json

# ─────────────────────────────────────────────────────────────────────────────
# Config-driven Provider Manifest
# To add a new provider: append an entry here. The routing branches in
# _generate_with_model_list check key prefixes and route accordingly.
# ─────────────────────────────────────────────────────────────────────────────
PROVIDERS = [
    {"name": "anthropic",   "key_prefix": "sk-ant-",  "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"]},
    {"name": "groq",        "key_prefix": "gsk_",     "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]},
    {"name": "openrouter",  "key_prefix": "sk-or-",   "models": ["google/gemini-2.5-flash", "google/gemini-2.5-flash-lite"]},
    {"name": "gemini",      "key_prefix": "AIza",     "models": ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.0-flash"]},
]

# For structured JSON output (analysis, scoring, review) — flash-lite is fast & cheap
JSON_FALLBACK_MODELS = [
    'gemini-3.1-flash-lite',
    'gemini-2.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.0-flash',
]

# For raw LaTeX generation — prioritize stronger reasoning models first to prevent document compilation failures
LATEX_FALLBACK_MODELS = [
    'gemini-2.5-flash',
    'gemini-3.1-flash-lite',
    'gemini-2.0-flash',
]

# For Groq client routing fallbacks
GROQ_FALLBACK_MODELS = [
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
    'mixtral-8x7b-32768',
    'gemma2-9b-it',
]


def clean_schema(schema: dict, inside_properties: bool = False) -> dict:
    """
    Recursively cleans a JSON schema for Gemini compatibility:
    - Inlines all nested definitions ($defs / $ref references) since Gemini rejects them.
    - Removes 'additionalProperties' (Gemini rejects it regardless of value).
    - Removes 'title' ONLY when it's a string metadata field on a schema node.
    """
    # If this is the root schema block and contains $defs, extract them first to inline nested parts
    if isinstance(schema, dict) and "$defs" in schema:
        schema = dict(schema) # shallow copy
        defs = schema.pop("$defs")
        
        def _resolve_refs(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    ref_path = node.pop("$ref")
                    ref_key = ref_path.split("/")[-1]
                    # Inline key definition
                    node.update(_resolve_refs(defs[ref_key]))
                for k, v in list(node.items()):
                    node[k] = _resolve_refs(v)
            elif isinstance(node, list):
                node = [_resolve_refs(item) for item in node]
            return node
            
        schema = _resolve_refs(schema)

    if isinstance(schema, dict):
        schema.pop("additionalProperties", None)
        # Only strip 'title' if we're NOT inside a 'properties' dict
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


def _generate_with_model_list(
    prompt: str,
    model_list: list,
    response_schema=None,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Core generation function. Tries each model in the given list in order.
    Falls back to the next model on any API error (rate limit, quota, etc).
    Supports OpenRouter routing if the API key prefix is "sk-or-".
    """
    active_key = custom_api_key or os.getenv("GEMINI_API_KEY")
    if not active_key:
        raise ValueError("API Key is not set.")

    # ── Anthropic Claude SDK Routing Branch ───────────────────────────────────
    if active_key.startswith("sk-ant-"):
        print("[LLM Client] Anthropic API key detected. Routing request through Anthropic SDK...")
        try:
            # pyrefly: ignore [missing-import]
            import anthropic
            anthropic_client = anthropic.Anthropic(api_key=active_key)
            
            # Select Sonnet for coding/LaTeX tasks, Haiku for quick JSON scoring
            is_latex_or_review = (response_schema is None or "latex" in prompt.lower())
            claude_model = "claude-3-5-sonnet-latest" if is_latex_or_review else "claude-3-5-haiku-latest"
            
            print(f"Attempting Anthropic generation with model: {claude_model}...")
            
            messages = [{"role": "user", "content": prompt}]
            system_prompt = "You are an expert recruiter AI system."
            
            if response_schema is not None:
                # Supply JSON schema and formatting guidelines directly to the prompt since Anthropic doesn't take raw schema parameters directly in chat completions
                schema_json = json.dumps(clean_schema(response_schema.model_json_schema()), indent=2)
                system_prompt += f"\nReturn ONLY a raw JSON object string that complies strictly with this JSON schema:\n{schema_json}"
                messages[0]["content"] += "\nEnsure your response is valid JSON and starts with '{' and ends with '}'."
            
            completion = anthropic_client.messages.create(
                model=claude_model,
                max_tokens=4096,
                temperature=0.1,
                system=system_prompt,
                messages=messages
            )
            
            text = completion.content[0].text
            if not text or not text.strip():
                raise ValueError("Anthropic returned empty text response.")
            print(f"Anthropic generation successful with: {claude_model}")
            return text
        except Exception as e:
            print(f"[LLM Client] Anthropic API call failed: {e}. Falling back to native Gemini models...")
            # Set active_key to default Gemini key to process fallback list
            active_key = os.getenv("GEMINI_API_KEY")

    # ── Groq SDK Routing Branch ──────────────────────────────────────────────
    if active_key and active_key.startswith("gsk_"):
        print("[LLM Client] Groq API key detected. Routing request through Groq SDK...")
        try:
            # pyrefly: ignore [missing-import]
            from groq import Groq
            groq_client = Groq(api_key=active_key)
            
            groq_error = None
            for groq_model in GROQ_FALLBACK_MODELS:
                # Retry loop for rate limits
                for retry_attempt in range(3):
                    try:
                        if on_log:
                            structured_log = json.dumps({"type": "llm_info", "message": f"🤖 Attempting generation with Groq model {groq_model} (attempt {retry_attempt + 1})..."})
                            on_log(structured_log)
                        print(f"Attempting Groq generation with model: {groq_model} (try {retry_attempt + 1})...")
                        
                        # Formulate query payload
                        messages = [{"role": "user", "content": prompt}]
                        payload_args = {
                            "model": groq_model,
                            "messages": messages,
                            "temperature": 0.2, # Keep low temperature for structured output alignment
                        }
                        
                        if response_schema is not None:
                            # Tell Groq to output JSON structured response
                            payload_args["response_format"] = {"type": "json_object"}
                            # Append schema format details to user prompt to reinforce structure compliance
                            schema_json = json.dumps(clean_schema(response_schema.model_json_schema()), indent=2)
                            messages[0]["content"] += f"\n\nCRITICAL: You must return a JSON object that adheres strictly to this JSON schema:\n{schema_json}"
                        
                        completion = groq_client.chat.completions.create(**payload_args)
                        text = completion.choices[0].message.content
                        
                        if not text or not text.strip():
                            raise ValueError("Groq returned empty text response.")
                        if on_log:
                            structured_log = json.dumps({"type": "llm_info", "message": f"✅ Groq generation successful with: {groq_model}"})
                            on_log(structured_log)
                        print(f"Groq generation successful with: {groq_model}")
                        return text
                    except Exception as model_err:
                        err_str = str(model_err).lower()
                        # Check for 429 Rate Limit/Quota error codes
                        if "429" in err_str or "rate_limit" in err_str or "quota" in err_str or "limit exceeded" in err_str:
                            msg = f"⚠️ Rate limit exceeded (429) for Groq model {groq_model}. Pausing for 10 seconds before resuming automatically..."
                            print(f"[LLM Client] {msg}")
                            structured_warn = json.dumps({"type": "llm_warn", "model": groq_model, "wait_s": 10, "message": msg})
                            if on_log:
                                on_log(structured_warn)
                            # Use a cooperative sleep loop that yields to the asyncio event loop
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                loop = None
                             
                            for _ in range(20):
                                if loop and loop.is_running():
                                    # Run asynchronous sleep thread-safely in the main event loop
                                    future = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.5), loop)
                                    try:
                                        future.result(timeout=1.0)
                                    except Exception:
                                        time.sleep(0.5)
                                else:
                                    time.sleep(0.5)
                            # Let the loop retry the same model
                            continue
                        else:
                            # For any other failure, move to the next model immediately
                            print(f"[LLM Client] Groq model {groq_model} failed: {model_err}. Trying next Groq model...")
                            groq_error = model_err
                            break
                else:
                    # Executes if the retry loop finished without breaking (meaning it retried 3 times and hit 429s each time)
                    print(f"[LLM Client] Groq model {groq_model} failed after 3 rate limit retries.")
            
            # If we completed the loop without returning, all Groq models failed
            raise RuntimeError(f"All Groq models failed. Last error: {groq_error}")
        except Exception as e:
            print(f"[LLM Client] All Groq API calls failed: {e}. Falling back to native Gemini models...")
            # Set active_key to default Gemini key to process fallback list
            active_key = os.getenv("GEMINI_API_KEY")

    # ── OpenRouter Routing Branch ───────────────────────────────────────────
    if active_key.startswith("sk-or-"):
        print("[LLM Client] OpenRouter API key detected. Routing request through OpenRouter...")
        # Map Google model names to their OpenRouter equivalents
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
                if on_log:
                    structured_log = json.dumps({"type": "llm_info", "message": f"🤖 Attempting OpenRouter generation with model {or_model}..."})
                    on_log(structured_log)
                print(f"Attempting OpenRouter generation with model: {or_model}...")
                import urllib.request
                import urllib.parse
                import ssl
                
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {active_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/AkhilBaja3005/job-finder",
                    "X-Title": "Job Finder Resume Tailor"
                }
                
                messages = [{"role": "user", "content": prompt}]
                payload = {
                    "model": or_model,
                    "messages": messages
                }
                if response_schema is not None:
                    # Provide JSON schema instructions directly for OpenRouter structure compliance
                    cleaned_schema = clean_schema(response_schema.model_json_schema())
                    payload["response_format"] = {
                        "type": "json_object",
                        "schema": cleaned_schema
                    }
                
                req_data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, headers=headers, data=req_data, method="POST")
                context = ssl._create_unverified_context()
                
                with urllib.request.urlopen(req, context=context, timeout=30) as response:
                    resp_body = response.read().decode("utf-8")
                    result = json.loads(resp_body)
                    text = result["choices"][0]["message"]["content"]
                    
                if not text or not text.strip():
                    print(f"OpenRouter model {or_model} returned empty response. Trying next model.")
                    continue
                if on_log:
                    structured_log = json.dumps({"type": "llm_info", "message": f"✅ OpenRouter generation successful with: {or_model}"})
                    on_log(structured_log)
                print(f"OpenRouter generation successful with: {or_model}")
                return text
            except Exception as e:
                last_error = e
                print(f"OpenRouter model {or_model} failed: {e}")
                continue
        raise RuntimeError(f"All OpenRouter model fallbacks failed. Last error: {last_error}")

    # ── Native Gemini SDK Branch ─────────────────────────────────────────────
    client = get_gemini_client(active_key)

    config_args = {}
    if response_schema is not None:
        cleaned_schema = clean_schema(response_schema.model_json_schema())
        config_args["response_mime_type"] = "application/json"
        config_args["response_schema"] = cleaned_schema

    last_error = None
    for model_name in model_list:
        for retry_attempt in range(3):
            try:
                if on_log:
                    structured_log = json.dumps({"type": "llm_info", "message": f"🤖 Attempting generation with Gemini model {model_name} (attempt {retry_attempt + 1})..."})
                    on_log(structured_log)
                print(f"Attempting generation with model: {model_name} (try {retry_attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_args),
                )
                try:
                    text = response.text
                except Exception as text_err:
                    print(f"Model {model_name} response.text access failed: {str(text_err)[:120]}. Trying next model.")
                    last_error = text_err
                    break # Break retry loop, try next model

                if not text or not text.strip():
                    print(f"Model {model_name} returned empty response. Trying next model.")
                    break # Break retry loop, try next model
                
                if on_log:
                    structured_log = json.dumps({"type": "llm_info", "message": f"✅ Generation successful with: {model_name}"})
                    on_log(structured_log)
                print(f"Generation successful with: {model_name}")
                return text
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                
                # Check for 429 Rate Limit/Quota errors
                if "429" in err_str or "quota" in err_str or "rate limit" in err_str or "resource_exhausted" in err_str or "resource exhausted" in err_str:
                    msg = f"⚠️ Rate limit exceeded (429) for Gemini model {model_name}. Pausing for 10 seconds before resuming automatically..."
                    print(f"[LLM Client] {msg}")
                    structured_warn = json.dumps({"type": "llm_warn", "model": model_name, "wait_s": 10, "message": msg})
                    if on_log:
                        on_log(structured_warn)
                    # Use a cooperative sleep loop that yields to the asyncio event loop
                    import time
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    
                    for _ in range(20):
                        if loop and loop.is_running():
                            # Run asynchronous sleep thread-safely in the main event loop
                            future = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.5), loop)
                            try:
                                future.result(timeout=1.0)
                            except Exception:
                                time.sleep(0.5)
                        else:
                            time.sleep(0.5)
                    continue
                
                # For block errors
                if "output text" in err_str or "tool calls" in err_str or "empty" in err_str:
                    print(f"Model {model_name} returned empty/blocked output: {str(e)[:120]}. Trying next model.")
                else:
                    print(f"Model {model_name} failed: {str(e)[:120]}")
                break # Break retry loop, try next model
        else:
            print(f"[LLM Client] Gemini model {model_name} failed after 3 rate limit retries.")

    raise RuntimeError(f"All model fallbacks failed. Last error: {str(last_error)}")


def generate_content_with_fallback(
    prompt: str,
    response_schema=None,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    JSON / structured output generation.
    Uses the JSON_FALLBACK_MODELS list (starts with fast flash-lite).
    """
    return _generate_with_model_list(
        prompt, JSON_FALLBACK_MODELS, response_schema, custom_api_key, on_log
    )


def generate_latex_with_strong_model(
    prompt: str,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Raw LaTeX generation — no JSON schema, uses LATEX_FALLBACK_MODELS which starts
    with the strongest available model to minimize structural corruption.
    """
    return _generate_with_model_list(
        prompt, LATEX_FALLBACK_MODELS, response_schema=None, custom_api_key=custom_api_key, on_log=on_log
    )
