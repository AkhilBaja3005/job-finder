---
name: company-intelligence
description: >-
  Use this skill when researching a target company, investigating their engineering
  culture, technology stack, and salary compensation benchmarks.
---

# Company Intelligence Skill

This skill guides agents in performing background research on prospective employers before submitting applications or attending interview rounds.

## Workflow

1. **Extract Culture and Technical Architecture**:
   - Call the `company_culture_brief` MCP tool:
     ```json
     {
       "company": "Anthropic",
       "job_description": "<jd_text>"
     }
     ```
   - Analyze engineering priorities, system architecture patterns, and team scope.

2. **Benchmark Compensation & Seniority**:
   - Call `extract_seniority_salary` to parse explicit or implicit compensation data.
   - Cross-reference known leveling systems (e.g. L4/L5, IC5/IC6, Lead vs Principal).

3. **Formulate High-Impact Value Hooks**:
   - Identify 2-3 acute technical challenges the team is hiring to solve (e.g. scaling API latency, migrating to distributed Kafka streams, LLM evaluation pipelines).
   - Arm the candidate with talking points addressing those exact themes.
