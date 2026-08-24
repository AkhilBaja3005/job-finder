"""
portal_scanner.py — Automated ATS Job Portal Scanner (Greenhouse, Ashby, Lever)

Pings public ATS endpoints without browser overhead, filters by user keywords,
and auto-scores matches deterministically against the candidate's profile.
"""

import os
import yaml
import asyncio
import httpx
from typing import List, Dict, Any, Optional

from services.ats_scorer import compute_ats_score, estimate_role_fit_score

DEFAULT_PORTALS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "portals.yml")


class PortalScanner:
    def __init__(self, config_path: str = DEFAULT_PORTALS_PATH):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[PortalScanner] Error loading {self.config_path}: {e}")
        return {
            "portals": {
                "greenhouse": [{"company_slug": "anthropic", "name": "Anthropic"}, {"company_slug": "stripe", "name": "Stripe"}],
                "ashby": [{"company_slug": "cohere", "name": "Cohere"}],
                "lever": [{"company_slug": "palantir", "name": "Palantir"}]
            },
            "config": {
                "min_ats_score_to_notify": 75,
                "roles_keywords": ["AI", "Machine Learning", "ML", "GenAI", "Software Engineer", "Systems"]
            }
        }

    async def scan_greenhouse_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Greenhouse public Board API."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
        jobs = []
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobs", [])
                for rj in raw_jobs:
                    jobs.append({
                        "id": f"gh_{rj.get('id')}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": rj.get("absolute_url", ""),
                        "location": rj.get("location", {}).get("name", "Remote/Unspecified"),
                        "description": rj.get("content", ""),
                        "portal": "greenhouse"
                    })
        except Exception as e:
            print(f"[PortalScanner] Greenhouse scrape error for {company_slug}: {e}")
        return jobs

    async def scan_ashby_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Ashby public Job Board API."""
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
        jobs = []
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobs", [])
                for rj in raw_jobs:
                    jobs.append({
                        "id": f"ashby_{rj.get('id')}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": rj.get("jobUrl", f"https://jobs.ashbyhq.com/{company_slug}/{rj.get('id')}"),
                        "location": rj.get("location", "Remote/Unspecified"),
                        "description": rj.get("descriptionHtml", rj.get("descriptionPlain", "")),
                        "portal": "ashby"
                    })
        except Exception as e:
            print(f"[PortalScanner] Ashby scrape error for {company_slug}: {e}")
        return jobs

    async def scan_lever_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Lever public Postings API."""
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        jobs = []
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                raw_jobs = res.json()
                for rj in raw_jobs:
                    jobs.append({
                        "id": f"lever_{rj.get('id')}",
                        "title": rj.get("text", ""),
                        "company": company_name,
                        "url": rj.get("hostedUrl", ""),
                        "location": rj.get("categories", {}).get("location", "Remote/Unspecified"),
                        "description": rj.get("descriptionPlain", "") or rj.get("description", ""),
                        "portal": "lever"
                    })
        except Exception as e:
            print(f"[PortalScanner] Lever scrape error for {company_slug}: {e}")
        return jobs

    async def scan_all_portals(self, target_keywords: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Scans all configured target portals concurrently."""
        portals_def = self.config.get("portals", {})
        keywords = target_keywords or self.config.get("config", {}).get("roles_keywords", [])
        keywords_lower = [k.lower() for k in keywords]

        all_jobs: List[Dict[str, Any]] = []
        tasks = []

        async with httpx.AsyncClient(headers={"User-Agent": "JobFinder/1.0"}) as client:
            # Greenhouse
            for comp in portals_def.get("greenhouse", []):
                tasks.append(self.scan_greenhouse_company(client, comp["company_slug"], comp["name"]))
            # Ashby
            for comp in portals_def.get("ashby", []):
                tasks.append(self.scan_ashby_company(client, comp["company_slug"], comp["name"]))
            # Lever
            for comp in portals_def.get("lever", []):
                tasks.append(self.scan_lever_company(client, comp["company_slug"], comp["name"]))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_jobs.extend(r)

        # Keyword filtering
        if keywords_lower:
            filtered = [
                j for j in all_jobs
                if any(kw in j["title"].lower() for kw in keywords_lower)
            ]
            return filtered
        return all_jobs

    def score_portal_jobs_for_candidate(
        self,
        jobs: List[Dict[str, Any]],
        candidate_resume_data: dict,
        min_score: int = 70
    ) -> List[Dict[str, Any]]:
        """Deterministic batch scoring for discovery jobs against candidate resume."""
        scored_jobs = []
        for job in jobs:
            try:
                ats_res = compute_ats_score(candidate_resume_data, job.get("description", ""))
                est_fit = estimate_role_fit_score(candidate_resume_data, job.get("description", ""))
                overall = round(0.40 * ats_res.skills_score + 0.35 * ats_res.experience_score + 0.25 * est_fit)
                if overall >= min_score:
                    scored_jobs.append({
                        **job,
                        "ats_score": overall,
                        "skills_score": ats_res.skills_score,
                        "experience_score": ats_res.experience_score,
                        "matched_skills": ats_res.matched_skills[:6],
                        "missing_skills": ats_res.missing_skills[:4],
                    })
            except Exception:
                continue
        # Sort highest score first
        scored_jobs.sort(key=lambda x: x.get("ats_score", 0), reverse=True)
        return scored_jobs
