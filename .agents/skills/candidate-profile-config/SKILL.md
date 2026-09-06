---
name: candidate-profile-config
description: Save, inspect, or update the user's candidate profile, career background, search preferences (target roles, locations, 24h timeframe, min ATS threshold), and reference strategy.
---

# Candidate Profile & Preferences Configuration Skill

Use this skill when a user asks to:
1. Save or update their candidate background, core skills, or resume contact info.
2. Set their target roles (e.g., "AI Engineer", "LLM Engineer"), target locations ("London", "Remote"), and search freshness window ("past_24_hours").
3. Configure minimum ATS score thresholds and reference/networking strategy.

## Workflow

### 1. Ingesting User Information
When the user shares their resume, job preferences, target location, or timeframe:
- Extract `name`, `email`, `linkedin`, `location`, `core_skills`, `experience_summary`.
- Extract `target_roles`, `target_locations`, `timeframe` (e.g. `past_24_hours`), and `min_ats_score_threshold`.
- Extract any specific reference contacts or preferred reference personas.

### 2. Calling the MCP Tool
Call `save_candidate_profile`:
```json
{
  "name": "User Name",
  "email": "user@example.com",
  "location": "London, UK",
  "target_roles": ["AI Engineer", "LLM Engineer"],
  "target_locations": ["London, UK", "Remote"],
  "timeframe": "past_24_hours",
  "min_ats_score_threshold": 65,
  "core_skills": ["Python", "PyTorch", "LangChain", "Docker"]
}
```

### 3. Retrieving Active Profile
To view or verify currently saved configurations across any AI harness, call `get_candidate_profile`.
