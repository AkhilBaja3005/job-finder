"""
Interview Preparation & Company Intelligence MCP Tools.
"""

from typing import Dict, Any, Optional
from services.gemini_client import generate_content_with_fallback

INTERVIEW_TOOLS_SPEC = [
    {
        "name": "generate_interview_pack",
        "description": "Generates a targeted technical and behavioral interview preparation guide based on the job requirements and company profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_title": {
                    "type": "string",
                    "description": "Role title."
                },
                "company": {
                    "type": "string",
                    "description": "Company name."
                },
                "job_description": {
                    "type": "string",
                    "description": "Target job description."
                }
            },
            "required": ["job_title", "company"]
        }
    },
    {
        "name": "company_culture_brief",
        "description": "Analyzes the company's technical stack, engineering practices, and culture signals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name."
                },
                "job_description": {
                    "type": "string",
                    "description": "Job description text."
                }
            },
            "required": ["company"]
        }
    }
]


async def handle_generate_interview_pack(arguments: Dict[str, Any]) -> Dict[str, Any]:
    title = arguments.get("job_title", "")
    company = arguments.get("company", "")
    jd = arguments.get("job_description", "")

    prompt = f"""
    You are an expert technical hiring manager and interview coach.
    Generate a concise, high-yield interview preparation pack for:
    Role: {title}
    Company: {company}
    
    Job Context:
    {jd[:2000]}

    Provide:
    1. Top 5 Technical Questions likely asked with model talking points.
    2. Top 3 Behavioral Questions tailored using the STAR framework.
    3. 3 Smart, highly engaging questions the candidate should ask the interviewers.
    """
    try:
        response = generate_content_with_fallback(prompt)
    except Exception:
        response = f"""# Interview Preparation Pack: {title} at {company}

## 1. Top Technical Domains
- System Design: Scaling distributed services and high-throughput APIs.
- Code & Concurrency: Data structures, async/multithreading patterns, and database indexing.
- Observability & Reliability: Metrics, tracing, alerting, and failure recovery modes.

## 2. Behavioral STAR Scenarios
- Situation/Task: Describe a challenging architectural bottleneck or production outage.
- Action: How you triaged, prioritized with stakeholders, and implemented the solution.
- Result: Concrete measurable impact (latency, cost savings, reliability).

## 3. High-Impact Questions to Ask Interviewers
1. What is the biggest technical roadblock the team is facing this quarter?
2. How does the engineering team balance new feature delivery against technical debt?
3. How is success measured for an engineer in this role over their first 90 days?
"""
    return {
        "company": company,
        "job_title": title,
        "interview_prep_markdown": response
    }


async def handle_company_culture_brief(arguments: Dict[str, Any]) -> Dict[str, Any]:
    company = arguments.get("company", "")
    jd = arguments.get("job_description", "")

    prompt = f"""
    Analyze the engineering signals, values, and tech stack expectations for {company} based on this job posting:
    {jd[:2500]}

    Summarize in markdown:
    - Likely Architecture & Tech Stack
    - Engineering Values & Working Style
    - High-Value Impact Themes
    """
    try:
        response = generate_content_with_fallback(prompt)
    except Exception:
        response = f"""# Company Culture & Technical Brief: {company}

## Architectural Archetype
- Fast-paced, high-ownership engineering environment with CI/CD automation.
- Emphasis on writing clean, maintainable, production-ready code with automated testing.

## Working Style & Values
- Autonomy and pragmatic problem-solving over bureaucratic process.
- Direct cross-functional collaboration with product, infrastructure, and domain stakeholders.
"""
    return {
        "company": company,
        "culture_brief_markdown": response
    }
