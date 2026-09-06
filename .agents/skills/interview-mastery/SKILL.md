---
name: interview-mastery
description: >-
  Use this skill when preparing for upcoming technical, system design, and
  behavioral interviews, or conducting interactive mock interview simulations.
---

# Interview Mastery Skill

Prepares candidates for high-stakes engineering interview loops by generating company-specific technical challenges and STAR-method behavioral preparation packs.

## Recommended Flow

1. **Generate Comprehensive Interview Pack**:
   - Call the `generate_interview_pack` MCP tool:
     ```json
     {
       "job_title": "Senior Distributed Systems Engineer",
       "company": "Cloudflare",
       "job_description": "<jd_text>"
     }
     ```

2. **Conduct Mock Interview Simulation**:
   - Ask the candidate 1 question at a time (e.g., technical system design tradeoff or behavioral STAR question).
   - Wait for their answer, evaluate clarity, depth, and communication skills, then provide actionable critique.

3. **Prepare Reverse-Interview Questions**:
   - Arm the candidate with 3 insightful questions to ask the interviewer regarding engineering bottlenecks, deployment cadence, and technical debt handling.
