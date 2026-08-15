import os
# pyrefly: ignore [missing-import]
from pypdf import PdfReader
# pyrefly: ignore [missing-import]
from docx import Document
import json
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

class SkillsCategorizationResponse(BaseModel):
    categorized_skills: Dict[str, List[str]] = Field(description="Dictionary of category names to list of skill strings")

def categorize_skills_with_llm(raw_skills: Union[str, List[str]]) -> Dict[str, List[str]]:
    """Use dedicated LLM call to dynamically categorize raw skill strings/lists into 3-5 categories."""
    if isinstance(raw_skills, list):
        skills_str = ", ".join([str(s) for s in raw_skills])
    else:
        skills_str = str(raw_skills)
        
    prompt = f"""
    You are an expert technical recruiter and resume classifier.
    Extract all individual technical skill items, tools, languages, frameworks, and libraries from the text below, and group them into 3 to 5 distinct, non-overlapping functional categories tailored to the candidate's domain (e.g. "Languages", "AI/ML & GenAI", "Data & Platforms", "Software & Infrastructure", "Cloud & DevOps", etc.).
    
    CRITICAL RULES:
    1. Extract ONLY concise skill names (e.g. "Python", "SQL", "Docker", "RAG", "PySpark"). Do NOT output full sentences or paragraph text.
    2. Every skill in the input MUST be placed into EXACTLY ONE category.
    3. Do NOT duplicate any skill across multiple categories.
    4. Keep category names concise and professional.
    
    Input Skill Text:
    {skills_str}
    """
    try:
        response_text = generate_content_with_fallback(prompt, SkillsCategorizationResponse)
        parsed = json.loads(response_text)
        cats = parsed.get("categorized_skills", {})
        if isinstance(cats, dict) and len(cats) > 0:
            clean_cats = {}
            for k, v in cats.items():
                if isinstance(v, list):
                    valid_items = []
                    for item in v:
                        s_str = str(item).replace("\n", " ").strip()
                        if s_str and len(s_str) < 50 and not s_str.lower().startswith("education") and not s_str.lower().startswith("work experience"):
                            valid_items.append(s_str)
                    if valid_items:
                        clean_cats[k] = valid_items
            if clean_cats:
                return clean_cats
    except Exception as e:
        print(f"[categorize_skills_with_llm] LLM call error: {e}")
        
    # Rule-based categorization fallback if LLM call fails or returns flat object
    flat_skills = [s.strip() for s in skills_str.split(",") if s.strip() and len(s.strip()) < 50]
    cats = {
        "Languages": [],
        "AI/ML & GenAI": [],
        "Data & Analytics": [],
        "Frontend & Web": [],
        "DevOps, SRE & Cloud": [],
        "Testing & QA": [],
        "Finance & Quant": [],
        "Software & Systems": []
    }
    
    lang_keywords = ["python", "sql", "c++", "java", "c#", "c", "r", "golang", "go", "typescript", "javascript", "rust", "bash", "shell", "scala", "kotlin", "swift", "php", "ruby", "perl", "matlab"]
    
    aiml_keywords = [
        "ai", "ml", "genai", "llm", "rag", "machine learning", "deep learning", "anomaly", "xgboost", 
        "naive bayes", "vision", "u-net", "densenet", "computer vision", "nlp", "transformers", "pytorch", 
        "tensorflow", "keras", "scikit-learn", "sklearn", "opencv", "langchain", "llama", "azure openai", 
        "huggingface", "context engineering", "fine-tuning", "prompt engineering", "reinforcement learning", 
        "bert", "diffusion", "neural network", "forecast", "forecasting", "predictive modeling"
    ]
    
    data_analytics_keywords = [
        "pyspark", "azure", "cloudera", "postgresql", "postgres", "sas", "database", "spark", "hive", 
        "snowflake", "bigquery", "redshift", "mongo", "mongodb", "redis", "mysql", "oracle", "elasticsearch", 
        "kafka", "airflow", "databricks", "hadoop", "etl", "elt", "data warehouse", "dbt", "looker", "tableau", 
        "power bi", "powerbi", "excel", "google analytics", "mixpanel", "data modeling", "business intelligence", 
        "kpi", "a/b testing", "data pipeline", "pandas", "numpy", "statistics"
    ]

    frontend_keywords = [
        "react", "react.js", "next.js", "nextjs", "vue", "vue.js", "angular", "svelte", "html", "html5", 
        "css", "css3", "tailwind", "bootstrap", "webpack", "vite", "redux", "zustand", "webassembly", 
        "responsive design", "ux", "ui", "storybook"
    ]

    devops_sre_keywords = [
        "docker", "kubernetes", "k8s", "helm", "terraform", "ansible", "puppet", "chef", "aws", "gcp", 
        "cloud", "azure", "ci/cd", "jenkins", "github actions", "gitlab ci", "rancher", "prometheus", 
        "grafana", "datadog", "splunk", "istio", "argocd", "linux", "unix", "sre", "infrastructure as code"
    ]

    testing_keywords = [
        "pytest", "unittest", "junit", "selenium", "cypress", "playwright", "jest", "mocha", "chai", 
        "test automation", "qa", "integration testing", "end-to-end testing", "tdd", "bdd", "loadrunner", "jmeter"
    ]

    quant_finance_keywords = [
        "stochastic", "black-scholes", "monte carlo", "risk modeling", "var", "value at risk", "time series", 
        "algorithmic trading", "derivatives", "options", "fixed income", "portfolio optimization", "quantitative analysis", 
        "quant", "bloomberg", "reuters", "financial modeling", "econometrics"
    ]

    for s in flat_skills:
        s_clean = s.strip()
        if not s_clean:
            continue
        s_lower = s_clean.lower()
        
        if any(k == s_lower or (len(k) > 2 and k in s_lower and not any(ai_k in s_lower for ai_k in ["ai", "ml", "learning"])) for k in lang_keywords):
            cats["Languages"].append(s_clean)
        elif any(k in s_lower for k in aiml_keywords):
            cats["AI/ML & GenAI"].append(s_clean)
        elif any(k in s_lower for k in frontend_keywords):
            cats["Frontend & Web"].append(s_clean)
        elif any(k in s_lower for k in devops_sre_keywords):
            cats["DevOps, SRE & Cloud"].append(s_clean)
        elif any(k in s_lower for k in testing_keywords):
            cats["Testing & QA"].append(s_clean)
        elif any(k in s_lower for k in quant_finance_keywords):
            cats["Finance & Quant"].append(s_clean)
        elif any(k in s_lower for k in data_analytics_keywords):
            cats["Data & Analytics"].append(s_clean)
        else:
            cats["Software & Systems"].append(s_clean)
    
    res_cats = {k: v for k, v in cats.items() if v}
    return res_cats if res_cats else {"Technical Skills": flat_skills}

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
       - Extract ONLY skills explicitly mentioned in the raw resume text below. Do NOT fabricate or assume any skill not present in the candidate's text.
       - Group extracted skills into 3-5 distinct, non-overlapping category key-value pairs inside `skills` matching how they appear in the candidate's resume (e.g. "Languages", "Frameworks & Tools", "Databases", "Cloud & Infrastructure").
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
            # Fallback: Extract technical terms directly mentioned in the user's actual text
            collected = []
            for exp in parsed_data.get("experience", []):
                if exp.get("technologies"):
                    collected.extend([t.strip() for t in exp["technologies"].split(",") if t.strip()])
                for b in exp.get("description", []):
                    # Find technical terms (capitalized words, frameworks, tools) from actual text
                    for match in re.findall(r'\b[A-Z][A-Za-z0-9+#.]{1,20}\b', str(b)):
                        if match not in ["The", "A", "An", "In", "On", "At", "To", "For", "With", "By", "From", "And", "Or", "Using", "Used", "Built", "Created", "Led", "Managed", "Reduced", "Increased"]:
                            if match not in collected:
                                collected.append(match)
            for proj in parsed_data.get("projects", []):
                if proj.get("title"):
                    for match in re.findall(r'\b[A-Z][A-Za-z0-9+#.]{1,20}\b', str(proj["title"])):
                        if match not in ["Project", "System", "Platform", "Tool", "App", "Application", "Dashboard"]:
                            if match not in collected:
                                collected.append(match)
            
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
