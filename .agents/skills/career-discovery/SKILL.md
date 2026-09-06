---
name: career-discovery
description: >-
  Use this skill when searching for job opportunities across Ashby, Greenhouse,
  Lever, LinkedIn, and Indeed. Orchestrates search queries, seniority & compensation
  filters, and ranks matches by ATS compatibility score.
---

# Career Discovery Skill

This skill teaches agents how to autonomously uncover and rank the highest-matching career opportunities across direct ATS boards and public listings.

## Recommended Workflow

1. **Identify Target Role & Criteria**:
   - Determine target job keywords (e.g., "Senior Python Engineer", "Staff Machine Learning Engineer").
   - Define target location (e.g., "Remote", "London", "New York") and timeframe (default `48h` for newest posts).

2. **Execute Job Search Tool**:
   - Call the MCP tool `search_jobs`:
     ```json
     {
       "keywords": "Senior Python Engineer",
       "location": "Remote",
       "timeframe": "48h"
     }
     ```

3. **Filter and Rank by Fit**:
   - Prioritize listings from direct ATS platforms (Ashby, Greenhouse, Lever) as they typically feature verified hiring teams and direct links without aggregator noise.
   - Separate listings into High Tier ($\ge 85\%$), Mid Tier ($70-84\%$), and Low Tier.

4. **Deep-Scrape Top Matches**:
   - For listings of interest, call `scrape_job_posting` with the job URL to retrieve clean requirements, tech stack details, and hiring manager / recruiter tags.
