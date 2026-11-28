"""Phase 6: Model routing, determinism, two-pass repair, rate-limit backoff & offline mode."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


DEFAULT_TAILOR_MODELS: Dict[str, str] = {
    "gemini": "gemini-2.5-flash",
    "claude": "claude-sonnet-4-5",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}


def resolve_tailor_provider_and_model(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[str, str]:
    """Resolve user's chosen AI provider and default to a stronger (non-lite) model."""
    prov = (provider or "gemini").strip().lower()
    if prov == "anthropic":
        prov_norm = "claude"
    else:
        prov_norm = prov if prov in DEFAULT_TAILOR_MODELS else "gemini"

    chosen_model = (model or "").strip()
    if not chosen_model or "lite" in chosen_model.lower():
        chosen_model = DEFAULT_TAILOR_MODELS[prov_norm]
    return prov_norm, chosen_model


def write_manifest_model_info(
    manifest_path: Path,
    *,
    provider: str,
    model: str,
    prompt_version: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record tailoring model metadata in manifest.json."""
    existing: Dict[str, Any] = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing["tailor_provider"] = provider
    existing["tailor_model"] = model
    existing["prompt_version"] = prompt_version
    if extra:
        existing.update(extra)
    manifest_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return existing


def compute_tailor_cache_key(
    master: Dict[str, Any],
    jd_text: str,
    prompt_version: str,
    model: str,
) -> str:
    """Deterministic SHA-256 cache key of (master, JD, prompt_version, model)."""
    payload = json.dumps(
        {
            "master": master,
            "jd_text": jd_text,
            "prompt_version": prompt_version,
            "model": model,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TailorCache:
    """In-memory deterministic cache for tailoring runs."""

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def get_or_compute(self, key: str, fn: Callable[[], Any]) -> Any:
        if key not in self._store:
            self._store[key] = fn()
        return self._store[key]


def run_two_pass_repair(
    items: Sequence[Dict[str, str]],
    *,
    validator: Callable[[Dict[str, str]], List[str]],
    repair_fn: Callable[[Dict[str, str], List[str]], str],
    max_repairs: int = 2,
) -> List[Dict[str, Any]]:
    """Validate candidate rewrites; repair only rejected items up to max_repairs, else revert."""
    results: List[Dict[str, Any]] = []
    for item in items:
        current = dict(item)
        reasons = validator(current)
        repairs_done = 0
        while reasons and repairs_done < max_repairs:
            repairs_done += 1
            current["candidate"] = repair_fn(current, reasons)
            reasons = validator(current)

        if reasons:
            results.append(
                {
                    "id": item.get("id"),
                    "final_text": item.get("original", ""),
                    "reverted": True,
                    "reasons": reasons,
                    "repairs": repairs_done,
                }
            )
        else:
            results.append(
                {
                    "id": item.get("id"),
                    "final_text": current.get("candidate", item.get("original", "")),
                    "reverted": False,
                    "reasons": [],
                    "repairs": repairs_done,
                }
            )
    return results


def compare_candidates(
    candidates: Sequence[Dict[str, Any]],
    *,
    scorer: Callable[[Dict[str, Any]], float],
) -> Dict[str, Any]:
    """Score multiple candidate CVs and return the highest-scoring one."""
    if not candidates:
        raise ValueError("candidates must be non-empty")
    return max(candidates, key=scorer)


def call_with_backoff(
    fn: Callable[[], Any],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> Dict[str, Any]:
    """Retry transient 429/rate-limit errors with exponential backoff."""
    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            return {"ok": True, "result": fn(), "attempts": attempt + 1, "user_message": ""}
        except Exception as exc:
            last_err = str(exc)
            is_rate_limit = "429" in last_err or "rate limit" in last_err.lower() or "quota" in last_err.lower()
            if not is_rate_limit or attempt >= max_retries:
                msg = (
                    "AI provider rate limit / quota reached. Please wait or switch providers."
                    if is_rate_limit
                    else f"Model call failed: {last_err}"
                )
                return {"ok": False, "result": None, "attempts": attempt + 1, "user_message": msg}
            if base_delay > 0:
                time.sleep(base_delay * (2 ** attempt))
    return {"ok": False, "result": None, "attempts": max_retries + 1, "user_message": last_err}


def redact_secrets(text: str) -> str:
    """Strip common API key patterns before logging or prompting."""
    s = re.sub(r"sk-[A-Za-z0-9_\-]{10,}", "[REDACTED_KEY]", text or "")
    s = re.sub(r"AIza[A-Za-z0-9_\-]{10,}", "[REDACTED_KEY]", s)
    return s


LAST_TAILOR_CALL: Dict[str, str] = {}


def pick_tailor_provider() -> str:
    """The AI to tailor with. JOB_FINDER_TAILOR_PROVIDER wins; otherwise the first provider in the user's order
    (BROWSER_USE_PROVIDERS, set from the app's "AI that drives the browser" choice) that has a key; otherwise Gemini."""
    import os
    keys = {"claude": "ANTHROPIC_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
    wanted = [os.getenv("JOB_FINDER_TAILOR_PROVIDER", "")] + [p for p in os.getenv("BROWSER_USE_PROVIDERS", "").replace(";", ",").split(",")]
    for prov in wanted:
        prov = prov.strip().lower()
        if prov in keys and os.getenv(keys[prov]):
            return "claude" if prov == "anthropic" else prov
    return "gemini"


def call_tailor_model(prompt: str, schema: Any) -> str:
    """One structured-output call to the chosen provider, with a strong (not "lite") model. Records what really ran."""
    import os
    from backend.services import gemini_client as gc
    provider = pick_tailor_provider()
    if provider == "claude":
        model = os.getenv("JOB_FINDER_TAILOR_MODEL") or "sonnet"
        LAST_TAILOR_CALL.update(provider="claude", model=model)
        return gc._execute_anthropic(prompt, schema, os.environ["ANTHROPIC_API_KEY"], model)
    if provider == "openai":
        model = os.getenv("JOB_FINDER_TAILOR_MODEL") or "terra"
        LAST_TAILOR_CALL.update(provider="openai", model=model)
        return gc._execute_openai(prompt, schema, os.environ["OPENAI_API_KEY"], model)
    LAST_TAILOR_CALL.update(provider="gemini", model="strong tier (non-lite Gemini models)")
    return gc.generate_content_with_fallback(prompt, schema, model_tier="strong")
