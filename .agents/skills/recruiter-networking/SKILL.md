---
name: recruiter-networking
description: >-
  Use this skill when drafting high-converting recruiter cold outreach, LinkedIn
  InMails, and follow-up sequences. Adheres to modern 3-sentence brevity rules.
---

# Recruiter Networking & Outreach Skill

Recruiters receive hundreds of generic AI messages every week. This skill enforces human-sounding, punchy, 3-sentence messages that yield 3x higher response rates.

## The 3-Sentence High-Converting Formula

- **Sentence 1 (The Hook)**: Specific mention of the role and why this particular team/company caught your attention.
- **Sentence 2 (The Proof)**: 1 quantified accomplishment directly matching their #1 technical pain point.
- **Sentence 3 (The Low-Friction Ask)**: An open-ended question that does not demand an immediate 30-minute calendar block (e.g., *"Are you open to a brief chat if my background aligns?"*).

## Execution Steps

1. **Extract Recruiter Name & Profile**:
   - Call `extract_recruiter_profile` with the job posting URL.

2. **Draft Targeted InMail**:
   - Call `generate_outreach_inmail`:
     ```json
     {
       "job_title": "Staff Backend Engineer",
       "company_name": "Datadog",
       "recruiter_name": "Sarah Jenkins",
       "candidate_skills": ["Go", "Distributed Systems", "Kubernetes"]
     }
     ```

3. **Multi-Touch Sequence**:
   - Provide the user with Day 0 (Initial outreach), Day 4 (Follow-up with a relevant technical thought/project link), and Day 9 (Graceful close-out).
