import os
import re
import json
# pyrefly: ignore [missing-import]
from pypdf import PdfReader
# pyrefly: ignore [missing-import]
from docx import Document
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union

from services.gemini_client import generate_content_with_fallback

class WorkExperience(BaseModel):
    company: str
    role: str
    start_date: str
    end_date: str
    technologies: Optional[str] = Field(default="", description="Technologies list under role e.g. 'Python, C++, Jedi, Jenkins...'")
    description: List[str]

class Education(BaseModel):
    institution: str
    degree: str
    field_of_study: Optional[str] = Field(default="")
    start_date: Optional[str] = Field(default="", description="Start date e.g. 'Sept 2026' or 'Aug 2019'")
    graduation_date: str = Field(description="Graduation or end date / range e.g. 'Sept 2027', 'May 2023', or 'Sept 2026 – Sept 2027'")
    location: Optional[str] = Field(default="", description="City/Country e.g. 'London, UK'")
    gpa: Optional[str] = Field(default=None, description="GPA, CPI, percentage, or grade score e.g. 'CPI: 8.04' or '94.2%'")
    highlights: List[str] = Field(default_factory=list, description="Leadership roles, coordinator roles, or bullet highlights under education")

class Project(BaseModel):
    title: str
    description: List[str]

class StructuredResume(BaseModel):
    name: str
    email: str
    phone: str
    links: List[str]
    summary: str
    skills: Union[Dict[str, List[str]], List[str]]
    experience: List[WorkExperience]
    education: List[Education]
    projects: List[Project] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list, description="Achievements & Leadership list items")

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_text_from_docx(file_path: str) -> str:
    doc = Document(file_path)
    text = []
    for para in doc.paragraphs:
        text.append(para.text)
    return "\n".join(text)

class CategorizedSkillItem(BaseModel):
    skill: str = Field(description="Normalized skill name")
    category: str = Field(description="One of the categories e.g. Languages, AI/ML & GenAI, Data & Analytics, Frontend & Web, DevOps & Cloud, Testing & QA, Finance & Quant, Software & Systems")

class SkillsCategorizationResponse(BaseModel):
    categorized: List[CategorizedSkillItem] = Field(default_factory=list)

KNOWN_SKILL_CATEGORY_MAP = {
    # Languages
    "python": "Languages", "sql": "Languages", "c++": "Languages", "java": "Languages", "c#": "Languages",
    "c": "Languages", "r": "Languages", "golang": "Languages", "go": "Languages", "typescript": "Languages",
    "javascript": "Languages", "rust": "Languages", "bash": "Languages", "shell": "Languages", "scala": "Languages",
    "kotlin": "Languages", "swift": "Languages", "php": "Languages", "ruby": "Languages", "perl": "Languages", "matlab": "Languages",
    # AI/ML & GenAI
    "ai": "AI/ML & GenAI", "ml": "AI/ML & GenAI", "genai": "AI/ML & GenAI", "llm": "AI/ML & GenAI", "rag": "AI/ML & GenAI",
    "machine learning": "AI/ML & GenAI", "deep learning": "AI/ML & GenAI", "pytorch": "AI/ML & GenAI", "tensorflow": "AI/ML & GenAI",
    "keras": "AI/ML & GenAI", "scikit-learn": "AI/ML & GenAI", "sklearn": "AI/ML & GenAI", "opencv": "AI/ML & GenAI",
    "langchain": "AI/ML & GenAI", "llamaindex": "AI/ML & GenAI", "huggingface": "AI/ML & GenAI", "computer vision": "AI/ML & GenAI",
    "nlp": "AI/ML & GenAI", "transformers": "AI/ML & GenAI", "xgboost": "AI/ML & GenAI",
    # Data & Analytics
    "pyspark": "Data & Analytics", "postgresql": "Data & Analytics", "postgres": "Data & Analytics", "sas": "Data & Analytics",
    "spark": "Data & Analytics", "hive": "Data & Analytics", "snowflake": "Data & Analytics", "bigquery": "Data & Analytics",
    "redshift": "Data & Analytics", "mongodb": "Data & Analytics", "mongo": "Data & Analytics", "redis": "Data & Analytics",
    "mysql": "Data & Analytics", "oracle": "Data & Analytics", "elasticsearch": "Data & Analytics", "kafka": "Data & Analytics",
    "airflow": "Data & Analytics", "databricks": "Data & Analytics", "hadoop": "Data & Analytics", "pandas": "Data & Analytics",
    "numpy": "Data & Analytics", "power bi": "Data & Analytics", "powerbi": "Data & Analytics", "tableau": "Data & Analytics",
    # Frontend & Web
    "react": "Frontend & Web", "react.js": "Frontend & Web", "next.js": "Frontend & Web", "nextjs": "Frontend & Web",
    "vue": "Frontend & Web", "vue.js": "Frontend & Web", "angular": "Frontend & Web", "svelte": "Frontend & Web",
    "html": "Frontend & Web", "html5": "Frontend & Web", "css": "Frontend & Web", "css3": "Frontend & Web",
    "tailwind": "Frontend & Web", "bootstrap": "Frontend & Web", "webpack": "Frontend & Web", "vite": "Frontend & Web",
    # DevOps & Cloud
    "docker": "DevOps & Cloud", "kubernetes": "DevOps & Cloud", "k8s": "DevOps & Cloud", "helm": "DevOps & Cloud",
    "terraform": "DevOps & Cloud", "aws": "DevOps & Cloud", "gcp": "DevOps & Cloud", "azure": "DevOps & Cloud",
    "jenkins": "DevOps & Cloud", "github actions": "DevOps & Cloud", "rancher": "DevOps & Cloud", "git": "DevOps & Cloud",
    # Testing & QA
    "pytest": "Testing & QA", "unittest": "Testing & QA", "junit": "Testing & QA", "selenium": "Testing & QA",
    "cypress": "Testing & QA", "playwright": "Testing & QA", "jest": "Testing & QA",
    # Business Analysis & Methodologies
    "requirements gathering": "Business Analysis", "gap analysis": "Business Analysis", "user stories": "Business Analysis",
    "brd": "Business Analysis", "brds": "Business Analysis", "frd": "Business Analysis", "process mapping": "Business Analysis",
    "stakeholder management": "Business Analysis", "agile": "Business Analysis", "scrum": "Business Analysis",
    "jira": "Business Analysis", "confluence": "Business Analysis", "business analysis": "Business Analysis"
}

def categorize_skills_with_llm(raw_skills: Union[str, List[str]]) -> Dict[str, List[str]]:
    """
    Hybrid Skill Categorization Engine:
    1. Deterministic Dictionary Map for 80% known skills (instant, 0 latency, 0 hallucination).
    2. LLM Fallback Call for remaining unknown/unclassified skills with temperature=0.
    """
    if isinstance(raw_skills, list):
        skill_items = [str(s).strip() for s in raw_skills if str(s).strip()]
    else:
        skill_items = [s.strip() for s in str(raw_skills).split(",") if s.strip()]

    result_categories: Dict[str, List[str]] = {}
    unknown_skills: List[str] = []

    # Step 1: Deterministic dictionary mapping
    for s in skill_items:
        s_clean = s.strip()
        if not s_clean or len(s_clean) > 50:
            continue
        cat = KNOWN_SKILL_CATEGORY_MAP.get(s_clean.lower())
        if cat:
            result_categories.setdefault(cat, [])
            if s_clean not in result_categories[cat]:
                result_categories[cat].append(s_clean)
        else:
            unknown_skills.append(s_clean)

    # Step 2: LLM Fallback for remaining unknown skills
    if unknown_skills:
        prompt = f"""
You are a skill categorization engine. You will be given a list of skills and a set of categories.
Assign each skill to exactly ONE category — the single best fit.

CATEGORIES:
1. Languages — programming languages (e.g. C++, Java, Rust, Go, Python, SQL, R).
2. AI/ML & GenAI — machine learning models, frameworks, AI tools, LLMs (e.g. PyTorch, LangChain, Transformers).
3. Data & Analytics — databases, query tools, BI, data processing engines (e.g. PostgreSQL, Spark, Tableau, Power BI, Excel).
4. Business Analysis — requirements gathering, process mapping, user stories, BRDs, Agile/Scrum, stakeholder management, Jira.
5. Frontend & Web — web development frameworks, UI tools, web tech (e.g. React, HTML, CSS).
6. DevOps & Cloud — cloud platforms, containerization, CI/CD, VCS (e.g. AWS, Docker, Git, Jenkins).
7. Testing & QA — automation frameworks, testing tools (e.g. Selenium, Cypress).
8. Finance & Quant — risk modeling, quantitative finance, financial tools (e.g. Black-Scholes, Monte Carlo).
9. Software & Systems — software architecture, developer tools, system libraries (e.g. RabbitMQ, AST Parsing, Microservices).

RULES:
- Normalize near-duplicate names before categorizing (e.g. "PowerBI" → "Power BI").
- Do NOT invent skills that were not in the input list. Do NOT skip any input skill.
- Output ONLY valid JSON matching the schema.

SKILLS TO CATEGORIZE:
{", ".join(unknown_skills)}
"""
        try:
            response_text = generate_content_with_fallback(prompt, SkillsCategorizationResponse)
            parsed = json.loads(response_text)
            items = parsed.get("categorized", [])
            for item in items:
                if isinstance(item, dict):
                    sk = item.get("skill", "").strip()
                    cat = item.get("category", "Software & Systems").strip()
                    if sk and len(sk) < 50:
                        result_categories.setdefault(cat, [])
                        if sk not in result_categories[cat]:
                            result_categories[cat].append(sk)
        except Exception as e:
            print(f"[categorize_skills_with_llm] Hybrid LLM fallback error: {e}")
            for sk in unknown_skills:
                result_categories.setdefault("Software & Systems", [])
                if sk not in result_categories["Software & Systems"]:
                    result_categories["Software & Systems"].append(sk)

    res_cats = {k: v for k, v in result_categories.items() if v}
    return res_cats if res_cats else {"Technical Skills": skill_items}

def parse_resume(file_path: str) -> StructuredResume:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        raw_text = extract_text_from_pdf(file_path)
    elif ext in ['.docx', '.doc']:
        raw_text = extract_text_from_docx(file_path)
    elif ext == '.tex':
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
    else:
        raise ValueError("Unsupported file format. Please upload PDF, DOCX, or TEX.")

    if not raw_text or not raw_text.strip():
        raise ValueError("Could not extract text from resume. Please ensure the file is not empty or corrupted.")

    prompt = f"""
    You are an expert resume parsing AI. Extract all information from the raw resume text below and organize it into a structured object matching the schema.

    CRITICAL RULES:
    1. Clean up any spacing or kerning anomalies in the candidate's name (e.g. "P A L L A V I" → "PALLAVI").
    2. Extract ALL URLs from the resume into the `links` array. This MUST include LinkedIn URLs (e.g. https://linkedin.com/in/username), GitHub URLs, portfolios, etc. Do NOT leave `links` empty if URLs are present.
    3. TECHNICAL SKILLS CATEGORIZATION (ABSOLUTE MANDATORY):
       - Extract ALL skills explicitly mentioned in the raw resume text below. Do NOT drop, truncate, or summarize long lists. Extract every single technology, language, framework, database, methodology, and tool listed.
       - Preserve the exact category key-value pairs as listed in the candidate's resume (e.g. "Languages", "AI/ML & GenAI", "Data & Platforms", "Software & Infrastructure"). Every item in each comma-separated list MUST be preserved.
       - Do NOT invent or copy skills from any external template!
    4. For each Education entry, extract:
       - Full start date AND graduation date (e.g. "Sept 2026 – Sept 2027", "Aug 2019 – May 2023"). Do NOT drop the start/end dates.
       - City/Country location if listed (e.g. "London, UK").
       - GPA, CPI, percentage, or grade score into the `gpa` field (e.g. "CPI: 8.04", "94.2%").
       - Leadership/extracurricular/coordinator bullets into `highlights` (e.g. "Internship and Placement Cell Coordinator — Managed corporate outreach...").
    5. Extract the phone number exactly as it appears.
    6. WORK EXPERIENCE BULLETS & SUB-PROJECTS: If a work experience entry contains sub-project headers (e.g. "Quartz (Context-as-a-Service & LLM Engineering):"), do NOT duplicate the sub-project title prefix on every child bullet point! Keep the sub-project header distinct or keep individual accomplishment bullets clean.
    7. WORK EXPERIENCE TECHNOLOGIES: If a work experience entry lists technologies under the role (e.g. "Technologies: Python, C++, Jedi, Jenkins..."), extract them into the `technologies` string field.

    Raw Resume Text:
    ---
    {raw_text}
    ---
    """

    response_text = generate_content_with_fallback(prompt, StructuredResume)
    parsed_data = json.loads(response_text)

    # Validate that we got required fields
    if not parsed_data.get("name"):
        parsed_data["name"] = "Candidate"
    if not parsed_data.get("email"):
        parsed_data["email"] = ""
    if not parsed_data.get("phone"):
        parsed_data["phone"] = ""
    if not parsed_data.get("links"):
        parsed_data["links"] = []
    if not parsed_data.get("summary"):
        parsed_data["summary"] = ""
    if not parsed_data.get("skills"):
        parsed_data["skills"] = {}
    if not parsed_data.get("experience"):
        parsed_data["experience"] = []
    if not parsed_data.get("education"):
        parsed_data["education"] = []
    if not parsed_data.get("projects"):
        parsed_data["projects"] = []
    if not parsed_data.get("achievements"):
        parsed_data["achievements"] = []

    # Auto-categorize skills using dedicated LLM call
    raw_skills = parsed_data.get("skills")
    if not isinstance(raw_skills, dict) or len(raw_skills) == 0 or sum(len(v) for v in raw_skills.values() if isinstance(v, list)) == 0:
        if raw_skills and not isinstance(raw_skills, dict):
            parsed_data["skills"] = categorize_skills_with_llm(raw_skills)
        else:
            # Fallback: Collect explicit technologies string from work experience entries
            collected = []
            for exp in parsed_data.get("experience", []):
                if exp.get("technologies"):
                    collected.extend([t.strip() for t in exp["technologies"].split(",") if t.strip()])
            
            if collected:
                parsed_data["skills"] = categorize_skills_with_llm(list(set(collected)))
            else:
                parsed_data["skills"] = {}

    # Post-process experience and project descriptions to ensure clean string representations
    for item in parsed_data.get("experience", []):
        if "description" in item and isinstance(item["description"], list):
            cleaned_bullets = []
            for b in item["description"]:
                if isinstance(b, str):
                    cleaned_bullets.append(b.strip())
            item["description"] = cleaned_bullets

    for proj in parsed_data.get("projects", []):
        if "description" in proj and isinstance(proj["description"], list):
            cleaned_bullets = []
            for b in proj["description"]:
                if isinstance(b, str):
                    cleaned_bullets.append(b.strip())
            proj["description"] = cleaned_bullets

    return StructuredResume(**parsed_data)
