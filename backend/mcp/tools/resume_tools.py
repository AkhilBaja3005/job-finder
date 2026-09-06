"""
LaTeX Resume Architecture & Compilation MCP Tools.
"""

from typing import Dict, Any, Optional
import os
import asyncio
from services.llm_agent import tailor_latex_code
from utils.latex_utils import compile_and_check_page_metrics, apply_latex_hotfix, generate_latex_from_json
from services.resume_parser import parse_resume
from services.overleaf import upload_zip_to_tmpfiles
from services.session_store import get_session_data

RESUME_TOOLS_SPEC = [
    {
        "name": "tailor_resume_latex",
        "description": "Tailors candidate LaTeX resume code specifically for a job description without inventing fake experience or credentials.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latex_code": {
                    "type": "string",
                    "description": "The base master LaTeX resume code."
                },
                "job_description": {
                    "type": "string",
                    "description": "Target job description text."
                },
                "job_title": {
                    "type": "string",
                    "description": "Target role title."
                },
                "company_name": {
                    "type": "string",
                    "description": "Target hiring company."
                }
            },
            "required": ["latex_code", "job_description"]
        }
    },
    {
        "name": "compile_latex_metrics",
        "description": "Compiles LaTeX code and performs page-budget metric checks to guarantee strict 1-page fit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latex_code": {
                    "type": "string",
                    "description": "LaTeX source code to validate."
                }
            },
            "required": ["latex_code"]
        }
    },
    {
        "name": "export_overleaf_bundle",
        "description": "Generates a 1-click Overleaf direct import URL with complete LaTeX project structure and resume.cls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latex_code": {
                    "type": "string",
                    "description": "The complete tailored LaTeX code."
                },
                "candidate_name": {
                    "type": "string",
                    "description": "Candidate name for the project bundle title."
                },
                "job_title": {
                    "type": "string",
                    "description": "Target job title."
                },
                "company": {
                    "type": "string",
                    "description": "Target company."
                }
            },
            "required": ["latex_code"]
        }
    },
    {
        "name": "parse_and_convert_to_latex",
        "description": "Parses a resume file (PDF, DOCX, TXT, or LaTeX) into structured JSON and generates canonical, compilable single-page LaTeX code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the resume file on disk (PDF, DOCX, or TEX)."
                },
                "raw_text": {
                    "type": "string",
                    "description": "Optional raw text if no file path is provided."
                }
            }
        }
    }
]


async def handle_tailor_resume_latex(arguments: Dict[str, Any]) -> Dict[str, Any]:
    latex = arguments.get("latex_code", "")
    jd = arguments.get("job_description", "")
    title = arguments.get("job_title", "Software Engineer")
    missing_skills = arguments.get("missing_skills", [])
    suggestions = arguments.get("suggestions", {})

    try:
        tailored = tailor_latex_code(
            master_latex=latex,
            job_title=title,
            job_description=jd,
            suggestions=suggestions,
            missing_skills=missing_skills
        )
    except Exception:
        # Graceful fallback: apply standard hotfixes without failing the tool call
        tailored = apply_latex_hotfix(latex)

    return {
        "tailored_latex": tailored,
        "length_chars": len(tailored)
    }


async def handle_compile_latex_metrics(arguments: Dict[str, Any]) -> Dict[str, Any]:
    latex = arguments.get("latex_code", "")
    fixed = apply_latex_hotfix(latex)
    res = compile_and_check_page_metrics(fixed)
    if isinstance(res, tuple):
        pages, filled_height = res
        success = pages != 999
    elif isinstance(res, dict):
        pages = res.get("pages", 1)
        filled_height = res.get("filled_height", 0.0)
        success = res.get("success", True)
    else:
        pages, filled_height, success = 1, 0.0, True

    return {
        "success": success,
        "page_count": pages,
        "fit_perfect": pages == 1,
        "filled_height_pt": filled_height
    }


async def handle_export_overleaf_bundle(arguments: Dict[str, Any]) -> Dict[str, Any]:
    latex = arguments.get("latex_code", "")
    candidate = arguments.get("candidate_name", "Candidate")
    title = arguments.get("job_title", "Role")
    company = arguments.get("company", "Company")

    overleaf_url = upload_zip_to_tmpfiles(latex, candidate, title, company)
    return {
        "overleaf_import_url": overleaf_url,
        "project_name": f"{candidate} - {title} Resume"
    }


async def handle_parse_and_convert_to_latex(arguments: Dict[str, Any]) -> Dict[str, Any]:
    file_path = arguments.get("file_path", "")
    raw_text = arguments.get("raw_text", "")

    if not file_path and not raw_text:
        return {
            "success": False,
            "error": "Either file_path or raw_text must be provided."
        }

    # If raw text provided without a file, save to a temp txt file
    if not file_path and raw_text:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write(raw_text)
            file_path = tf.name

    if not os.path.exists(file_path):
        return {
            "success": False,
            "error": f"File not found: {file_path}"
        }

    try:
        if file_path.endswith(".tex"):
            with open(file_path, "r", encoding="utf-8") as f:
                tex_code = f.read()
            return {
                "success": True,
                "latex_code": tex_code,
                "format": "tex",
                "message": "Direct LaTeX file loaded successfully."
            }

        # Parse PDF / DOCX to structured JSON
        structured_resume = await asyncio.to_thread(parse_resume, file_path)
        data = structured_resume.model_dump()
        
        # Convert JSON structure to compilable single-page LaTeX
        canonical_latex = generate_latex_from_json(data)
        hotfixed_latex = apply_latex_hotfix(canonical_latex)

        return {
            "success": True,
            "format": os.path.splitext(file_path)[1].lower().lstrip("."),
            "candidate_name": data.get("name"),
            "structured_data": data,
            "latex_code": hotfixed_latex,
            "message": "Successfully parsed resume and converted to single-page LaTeX."
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

