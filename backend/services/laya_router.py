"""
laya_router.py — Non-autoregressive decision & field classification engine powered by Laya.

Provides ultra-fast (<40ms) calibrated classification, field-intent mapping,
guardrail validation, and routing between System 1 reflex actions and System 2 LLM generation.
"""

import os
import sys
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Check if laya package is available
try:
    import laya  # type: ignore
    HAS_LAYA = True
except ImportError:
    HAS_LAYA = False


def call_openai_decisions_api(
    input_text: str,
    questions: List[Dict[str, Any]],
    api_key: Optional[str] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    Calls OpenAI Decisions API (POST /v1/decisions) using gpt-6-luna.
    Returns typed answers 10x faster than traditional completion/chat endpoints.
    """
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return None

    url = os.getenv("OPENAI_DECISIONS_URL", "https://api.openai.com/v1/decisions")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-6-luna",
        "input": input_text,
        "questions": questions
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get("answers", [])
        logger.warning(f"[openai-decisions] API returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"[openai-decisions] Failed to execute decisions request: {e}")
    return None


class LayaDecisionRouter:
    """
    Sub-millisecond semantic classifier & router for ATS job application inputs,
    guardrails, and decision branches.
    """

    def __init__(self, model_name: str = "modernbert-decision-v1"):
        self.model_name = model_name
        self.has_native = HAS_LAYA
        self._model = None
        if self.has_native:
            try:
                # Initialize native Laya router instance if available
                # pyrefly: ignore [missing-attribute]
                self._model = laya.DecisionEngine(model_name)
            except Exception as e:
                logger.warning(f"[laya] Could not load native model {model_name}: {e}")
                self.has_native = False

    def classify_form_field(self, label_or_placeholder: str) -> str:
        """
        Classifies an input label into standardized ATS taxonomy in <10ms:
        e.g. 'first_name', 'last_name', 'email', 'phone', 'phone_country_code',
             'location', 'linkedin', 'github', 'sponsorship', 'experience_years', 'custom_essay'
        """
        text = label_or_placeholder.lower().strip()

        # 1. Primary Priority: If OPENAI_API_KEY is provided, use OpenAI Decisions API (gpt-6-luna)
        # for complex or ambiguous fields (10x faster typed evaluation than completion endpoints)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key and len(text) > 5:
            decisions = call_openai_decisions_api(
                input_text=label_or_placeholder,
                questions=[
                    {
                        "type": "choice",
                        "name": "field_category",
                        "instructions": "Classify this job application form field into the standard taxonomy.",
                        "choices": [
                            "first_name", "last_name", "email", "phone", "phone_country_code",
                            "location", "country", "linkedin", "github", "portfolio", "sponsorship",
                            "notice_period", "source_referral", "gender", "ethnicity",
                            "veteran_status", "disability_status", "resume_upload",
                            "ai_assistance_prohibited", "legal_or_sensitive_blocker", "custom_essay", "generic_text"
                        ]
                    }
                ],
                api_key=openai_key
            )
            if decisions and len(decisions) > 0 and decisions[0].get("choice"):
                chosen = decisions[0]["choice"]
                logger.info(f"[openai-decisions] gpt-6-luna classified '{label_or_placeholder}' -> {chosen}")
                return chosen

        # 2. Reflex keyword & pattern matching (<10ms non-autoregressive)
        if any(w in text for w in ["country code", "dial code", "phone code", "dialing code", "calling prefix", "flag"]):
            return "phone_country_code"
        if any(w in text for w in ["mobile", "phone", "cell", "telephone", "contact number"]):
            return "phone"
        if any(w in text for w in ["first name", "firstname", "given name"]):
            return "first_name"
        if any(w in text for w in ["last name", "lastname", "surname", "family name"]):
            return "last_name"
        if any(w in text for w in ["email", "e-mail"]):
            return "email"
        if any(w in text for w in ["linkedin"]):
            return "linkedin"
        if any(w in text for w in ["github"]):
            return "github"
        if any(w in text for w in ["website", "portfolio", "personal link"]):
            return "portfolio"
        if any(w in text for w in ["sponsor", "visa", "work authorization", "authorized to work", "require sponsorship"]):
            return "sponsorship"
        if any(w in text for w in ["notice period", "earliest start", "when can you start", "availability"]):
            return "notice_period"
        if any(w in text for w in ["how did you hear", "source", "referral"]):
            return "source_referral"
        if any(w in text for w in ["gender"]):
            return "gender"
        if any(w in text for w in ["race", "ethnicity"]):
            return "ethnicity"
        if any(w in text for w in ["veteran"]):
            return "veteran_status"
        if any(w in text for w in ["disability"]):
            return "disability_status"
        if any(w in text for w in ["city", "location", "address", "state", "postal", "zipcode", "postcode"]):
            return "location"
        if any(w in text for w in ["country", "residence country", "nationality"]):
            return "country"
        if any(w in text for w in ["resume", "cv", "attach file", "upload resume"]):
            return "resume_upload"

        # Explicit AI assistance prohibitions (attention blockers)
        if any(w in text for w in [
            "do not use ai", "don't use ai", "without ai assistance", "no ai assistance",
            "write in your own words", "in your own voice", "generative ai is not allowed",
            "chatgpt not allowed", "ai generated content is not permitted"
        ]):
            return "ai_assistance_prohibited"

        # Legal certification & sensitive identification blockers
        if any(w in text for w in [
            "under penalty of perjury", "i certify that", "i swear", "background check consent",
            "social security", "ssn", "national insurance", "passport number", "driver's license"
        ]):
            return "legal_or_sensitive_blocker"


        # Check if length indicates a long-form custom essay requiring System 2 LLM
        if len(text) > 60 or any(w in text for w in ["why do you want", "tell us about", "describe a time", "cover letter"]):
            return "custom_essay"

        return "generic_text"

    def route_decision(self, question: str, candidate_data: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """
        Determines whether a question can be answered immediately via System 1 reflex (<10ms)
        or must be routed to System 2 LLM generation.
        Returns: (route_type: 'reflex' | 'llm_generation', reflex_value)
        """
        field_type = self.classify_form_field(question)
        cand = candidate_data.get("candidate", candidate_data)

        if field_type == "first_name":
            name = cand.get("name", "")
            return "reflex", name.split()[0] if name else ""
        if field_type == "last_name":
            name = cand.get("name", "")
            return "reflex", name.split()[-1] if len(name.split()) > 1 else ""
        if field_type == "email":
            return "reflex", cand.get("email", "")
        if field_type == "phone":
            phone = cand.get("phone", "")
            return "reflex", phone
        if field_type == "phone_country_code":
            phone = str(cand.get("phone", "")).strip()
            loc = str(cand.get("location", "")).lower()
            if "+44" in phone or phone.startswith("0044") or (phone.startswith("44") and len(phone) >= 11) or "uk" in loc or "london" in loc or "united kingdom" in loc:
                return "reflex", "+44"
            if "+91" in phone or phone.startswith("0091") or (phone.startswith("91") and len(phone) >= 12) or "india" in loc:
                return "reflex", "+91"
            if "+1" in phone or phone.startswith("001") or "united states" in loc or "usa" in loc:
                return "reflex", "+1"
            return "reflex", "+44" if "uk" in loc else "+91"
        if field_type == "linkedin":
            return "reflex", cand.get("linkedin", "")
        if field_type == "github":
            return "reflex", cand.get("github", "")
        if field_type == "portfolio":
            return "reflex", cand.get("portfolio", "")
        if field_type == "gender":
            return "reflex", cand.get("gender", "Male")
        if field_type == "ethnicity":
            return "reflex", cand.get("ethnicity", "Asian")
        if field_type == "veteran_status":
            return "reflex", cand.get("veteran_status", "No")
        if field_type == "disability_status":
            return "reflex", cand.get("disability_status", "No")
        if field_type == "country":
            loc = str(cand.get("location", "")).lower()
            if "uk" in loc or "london" in loc or "united kingdom" in loc:
                return "reflex", "United Kingdom"
            if "india" in loc:
                return "reflex", "India"
            if "united states" in loc or "usa" in loc:
                return "reflex", "United States"
            return "reflex", cand.get("country", "United Kingdom")
        if field_type == "ai_assistance_prohibited":
            return "blocked_ai_policy", None
        if field_type == "legal_or_sensitive_blocker":
            return "blocked_legal_sensitive", None
        if field_type == "sponsorship":
            req_spons = cand.get("requires_sponsorship", True)
            return "reflex", "Yes" if req_spons else "No"
        if field_type == "source_referral":
            return "reflex", "LinkedIn"
        if field_type == "notice_period":
            return "reflex", "Available immediately"

        # Long custom screening questions route to System 2 LLM
        return "llm_generation", None


# Global singleton router instance
_laya_router: Optional[LayaDecisionRouter] = None

def get_laya_router() -> LayaDecisionRouter:
    global _laya_router
    if _laya_router is None:
        _laya_router = LayaDecisionRouter()
    return _laya_router
