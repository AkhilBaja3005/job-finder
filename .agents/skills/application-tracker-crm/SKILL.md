---
name: application-tracker-crm
description: >-
  Use this skill when managing the job hunt pipeline, tracking applied/saved jobs,
  preventing duplicate applications, and monitoring interview stages.
---

# Application Tracker & Career CRM Skill

Keeps your job search organized, prevents embarrassing duplicate applications, and maintains pipeline momentum.

## Core Procedures

1. **Pre-Application Duplicate Check**:
   - Before applying, always call `check_duplicate_application`:
     ```json
     {
       "company": "Stripe"
     }
     ```
   - If the candidate applied within the past 90 days, inform the user to prevent ATS spam flagging.

2. **Log Submission / Status Update**:
   - After submitting or saving, call `track_application`:
     ```json
     {
       "job_url": "https://boards.greenhouse.io/stripe/jobs/12345",
       "status": "applied",
       "company": "Stripe",
       "job_title": "Software Engineer, Payments",
       "score": 92
     }
     ```

3. **Weekly Pipeline Review**:
   - Call `list_applications` with `status_filter: "applied"` to review pending roles that are past Day 5 for follow-up outreach.
