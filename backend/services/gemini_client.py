import os
from google import genai
from google.genai import types
import google.api_core.exceptions
from typing import Optional
import json

# ─────────────────────────────────────────────────────────────────────────────
# Model priority lists
# ─────────────────────────────────────────────────────────────────────────────

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
            print(f"Anthropic API call failed: {e}")
            raise RuntimeError(f"Anthropic API routing failed: {e}")

    # ── Groq SDK Routing Branch ──────────────────────────────────────────────
    if active_key.startswith("gsk_"):
        print("[LLM Client] Groq API key detected. Routing request through Groq SDK...")
        try:
            from groq import Groq
            groq_client = Groq(api_key=active_key)
            
            # Map standard jobs to the Groq flagship model
            groq_model = "llama-3.3-70b-versatile"
            print(f"Attempting Groq generation with model: {groq_model}...")
            
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
            print(f"Groq generation successful with: {groq_model}")
            return text
        except Exception as e:
            print(f"Groq API call failed: {e}")
            raise RuntimeError(f"Groq API routing failed: {e}")

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
                print(f"Attempting OpenRouter generation with model: {or_model}...")
                import urllib.request
                import urllib.parse
                import json
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
        try:
            print(f"Attempting generation with model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(**config_args),
            )
            # response.text can itself raise if model returned empty/blocked output
            try:
                text = response.text
            except Exception as text_err:
                print(f"Model {model_name} response.text access failed: {str(text_err)[:120]}. Trying next model.")
                last_error = text_err
                continue

            if not text or not text.strip():
                print(f"Model {model_name} returned empty response. Trying next model.")
                continue
            print(f"Generation successful with: {model_name}")
            return text
        except google.api_core.exceptions.GoogleAPICallError as e:
            last_error = e
            print(f"Model {model_name} failed (API error): {str(e)[:120]}")
            continue
        except Exception as e:
            last_error = e
            # Catch the "model output must contain either output text or tool calls" error
            err_str = str(e).lower()
            if "output text" in err_str or "tool calls" in err_str or "empty" in err_str:
                print(f"Model {model_name} returned empty/blocked output: {str(e)[:120]}. Trying next model.")
            else:
                print(f"Model {model_name} failed (generic): {str(e)[:120]}")
            continue

    raise RuntimeError(f"All model fallbacks failed. Last error: {str(last_error)}")


def generate_content_with_fallback(
    prompt: str,
    response_schema=None,
    custom_api_key: Optional[str] = None,
) -> str:
    """
    JSON / structured output generation.
    Uses the JSON_FALLBACK_MODELS list (starts with fast flash-lite).
    """
    return _generate_with_model_list(
        prompt, JSON_FALLBACK_MODELS, response_schema, custom_api_key
    )


def generate_latex_with_strong_model(
    prompt: str,
    custom_api_key: Optional[str] = None,
) -> str:
    """
    Raw LaTeX generation — no JSON schema, uses LATEX_FALLBACK_MODELS which starts
    with the strongest available model to minimize structural corruption.
    """
    return _generate_with_model_list(
        prompt, LATEX_FALLBACK_MODELS, response_schema=None, custom_api_key=custom_api_key
    )
