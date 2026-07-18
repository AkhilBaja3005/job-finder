import os
# pyrefly: ignore [missing-import]
from pypdf import PdfReader
# pyrefly: ignore [missing-import]
from docx import Document
import json
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import List, Optional

from services.gemini_client import generate_content_with_fallback

class WorkExperience(BaseModel):
    company: str
    role: str
    start_date: str
    end_date: str
    description: List[str]

class Education(BaseModel):
    institution: str
    degree: str
    field_of_study: str
    graduation_date: str
    gpa: Optional[str] = Field(default=None, description="GPA, CPI, percentage, or grade score e.g. 'CPI: 8.04' or '94.2%'")

class Project(BaseModel):
    title: str
    description: List[str]

class StructuredResume(BaseModel):
    name: str
    email: str
    phone: str
    links: List[str]
    summary: str
    skills: List[str]
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
    3. For each Education entry, extract the GPA, CPI, percentage, or grade score into the `gpa` field (e.g. "CPI: 8.04", "94.2%"). Do NOT omit this even if it appears on the same line as the degree.
    4. Extract the phone number exactly as it appears.

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
        parsed_data["skills"] = []
    if not parsed_data.get("experience"):
        parsed_data["experience"] = []
    if not parsed_data.get("education"):
        parsed_data["education"] = []
    if not parsed_data.get("projects"):
        parsed_data["projects"] = []
    if not parsed_data.get("achievements"):
        parsed_data["achievements"] = []

    return StructuredResume(**parsed_data)
