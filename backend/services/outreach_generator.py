"""
Outreach message generation service.
Generates personalized recruiter outreach messages using LLM.
"""

import json
from typing import Optional, Dict
from pydantic import BaseModel, Field

from services.gemini_client import generate_content_with_fallback


class OutreachMessage(BaseModel):
    """Generated outreach message sections"""
    why_applying: str = Field(description="1-2 sentences on why applying to this role")
    why_fit: str = Field(description="2-3 sentences on why candidate fits the role")
    questions: list[str] = Field(description="2-3 thoughtful questions about role/team/company")
    email_subject: str = Field(description="Professional email subject line")
    email_body: str = Field(description="Full email body with all sections")
    linkedin_message: str = Field(description="LinkedIn message formatted for copy-paste")


def generate_outreach_message(
    job_description: str,
    resume_data: dict,
    ats_analysis: dict,
    recruiter_name: Optional[str],
    company_name: str,
    custom_api_key: Optional[str] = None,
    on_log: Optional[callable] = None
) -> OutreachMessage:
    """
    Generate personalized outreach message sections using LLM.

    Args:
        job_description: The job posting description
        resume_data: Parsed resume data (name, email, phone, skills, experience, etc.)
        ats_analysis: ATS analysis result with match_analysis and suggested_resume_updates
        recruiter_name: Name of the recruiter (if found)
        company_name: Name of the company
        custom_api_key: Optional custom Gemini API key
        on_log: Optional callback for logging

    Returns:
        OutreachMessage with all sections
    """

    # Extract key info from resume
    candidate_name = resume_data.get("name", "Candidate")
    candidate_email = resume_data.get("email", "")
    candidate_phone = resume_data.get("phone", "")
    candidate_skills = resume_data.get("skills", [])
    candidate_experience = resume_data.get("experience", [])

    # Extract key info from ATS analysis
    match_analysis = ats_analysis.get("match_analysis", {})
    overall_score = match_analysis.get("overall_score", 0)
    matched_skills = match_analysis.get("matched_skills", [])
    missing_skills = match_analysis.get("missing_skills", [])
    tailoring_suggestions = match_analysis.get("tailoring_suggestions", [])

    # Build context for LLM
    experience_summary = ""
    if candidate_experience:
        exp_list = []
        for exp in candidate_experience[:3]:  # Top 3 experiences
            role = exp.get("role", "")
            company = exp.get("company", "")
            if role and company:
                exp_list.append(f"- {role} at {company}")
        experience_summary = "\n".join(exp_list)

    matched_skills_str = ", ".join(matched_skills[:5]) if matched_skills else "N/A"
    missing_skills_str = ", ".join(missing_skills[:3]) if missing_skills else "None"

    # Handle missing recruiter name gracefully
    recruiter_greeting = f"Hi {recruiter_name}," if recruiter_name else "Dear Hiring Team,"

    prompt = f"""You are an expert recruiter outreach specialist. Generate a personalized outreach message for a job candidate.

CANDIDATE PROFILE:
- Name: {candidate_name}
- Email: {candidate_email}
- Phone: {candidate_phone}
- Top Skills: {", ".join(candidate_skills[:8])}
- Recent Experience:
{experience_summary}

JOB DETAILS:
- Company: {company_name}
- Job Description: {job_description[:1500]}

ATS ANALYSIS:
- Overall Match Score: {overall_score}/100
- Matched Skills: {matched_skills_str}
- Missing Skills: {missing_skills_str}
- Tailoring Suggestions: {", ".join(tailoring_suggestions[:3])}

GREETING: Use this greeting in the email body: "{recruiter_greeting}"

TASK: Generate a personalized outreach message with these sections:

1. "Why I'm applying" (1-2 sentences): Explain motivation based on job fit and company
2. "Why I fit" (2-3 sentences): Highlight skills/experience alignment from ATS analysis
3. "Relevant questions" (2-3 bullet points): Ask thoughtful questions about role/team/company
4. Email subject line: Professional and compelling
5. Full email body: Combine all sections into a professional email
6. LinkedIn message: Format for LinkedIn copy-paste (shorter, more casual)

Return ONLY valid JSON (no markdown, no code fences) with this exact structure:
{{
  "why_applying": "...",
  "why_fit": "...",
  "questions": ["...", "...", "..."],
  "email_subject": "...",
  "email_body": "Dear {recruiter_name or 'Hiring Team'},\\n\\n[why_applying]\\n\\n[why_fit]\\n\\nI'd love to learn more about this opportunity. I have a few questions:\\n\\n[questions as bullet points]\\n\\nThank you for considering my application.\\n\\nBest regards,\\n{candidate_name}",
  "linkedin_message": "..."
}}

Make the messages personalized, professional, and compelling. Use the ATS analysis to highlight relevant skills."""

    try:
        if on_log:
            on_log(json.dumps({"type": "log", "message": "Generating personalized outreach message..."}))

        print(f"[outreach_generator] Generating with job_description length: {len(job_description) if job_description else 0}")
        print(f"[outreach_generator] Company: {company_name}, Recruiter: {recruiter_name}")

        response = generate_content_with_fallback(
            prompt=prompt,
            custom_api_key=custom_api_key,
            on_log=on_log
        )

        print(f"[outreach_generator] LLM response length: {len(response)}")
        print(f"[outreach_generator] LLM response (first 500 chars): {response[:500]}")

        # Parse the response
        try:
            result = json.loads(response)
            print(f"[outreach_generator] Parsed JSON successfully: {list(result.keys())}")
        except json.JSONDecodeError:
            print(f"[outreach_generator] JSON parse failed, trying regex extraction")
            # Try to extract JSON from markdown code fences
            import re
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
            if match:
                result = json.loads(match.group(1))
                print(f"[outreach_generator] Extracted from markdown: {list(result.keys())}")
            else:
                # Try to find the outermost {...} block
                match = re.search(r'\{.*\}', response, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                    print(f"[outreach_generator] Extracted from braces: {list(result.keys())}")
                else:
                    raise ValueError("Could not parse LLM response as JSON")

        # Validate and create OutreachMessage
        outreach_msg = OutreachMessage(
            why_applying=result.get("why_applying", ""),
            why_fit=result.get("why_fit", ""),
            questions=result.get("questions", []),
            email_subject=result.get("email_subject", ""),
            email_body=result.get("email_body", ""),
            linkedin_message=result.get("linkedin_message", "")
        )
        print(f"[outreach_generator] Created OutreachMessage: {outreach_msg.model_dump()}")
        return outreach_msg

    except Exception as e:
        print(f"Error generating outreach message: {e}")
        # Return a fallback message
        return OutreachMessage(
            why_applying=f"I am interested in the {company_name} opportunity and believe my skills align well with the role requirements.",
            why_fit=f"With my background in {', '.join(candidate_skills[:3])}, I am confident I can contribute effectively to your team.",
            questions=[
                "What are the key priorities for this role in the first 90 days?",
                "Can you tell me more about the team structure and collaboration style?",
                "What does success look like in this position?"
            ],
            email_subject=f"Application for {company_name} Position",
            email_body=f"""Dear Hiring Team,

I am interested in the {company_name} opportunity and believe my skills align well with the role requirements.

With my background in {', '.join(candidate_skills[:3])}, I am confident I can contribute effectively to your team.

I would love to learn more about this opportunity. I have a few questions:
- What are the key priorities for this role in the first 90 days?
- Can you tell me more about the team structure and collaboration style?
- What does success look like in this position?

Thank you for considering my application.

Best regards,
{candidate_name}""",
            linkedin_message=f"Hi! I'm very interested in the {company_name} opportunity. My background in {', '.join(candidate_skills[:3])} aligns well with what you're looking for. Would love to chat more about this role!"
        )
