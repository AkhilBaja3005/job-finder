"""
portal_scanner.py — Automated ATS Job Portal Scanner (Greenhouse, Ashby, Lever)

Pings public ATS endpoints without browser overhead, filters by user keywords,
and auto-scores matches deterministically against the candidate's profile.
"""

import os
try:
    # pyrefly: ignore [untyped-import]
    import yaml  # type: ignore
except ImportError:
    yaml = None
import asyncio
# pyrefly: ignore [missing-import]
import httpx
from typing import List, Dict, Any, Optional
# pyrefly: ignore [missing-import]
from services.ats_scorer import compute_ats_score, estimate_role_fit_score

DEFAULT_PORTALS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "portals.yml")


class PortalScanner:
    def __init__(self, config_path: str = DEFAULT_PORTALS_PATH):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        base_portals = {
            "greenhouse": [{"company_slug": "anthropic", "name": "Anthropic"}, {"company_slug": "stripe", "name": "Stripe"}],
            "ashby": [{"company_slug": "cohere", "name": "Cohere"}],
            "lever": [{"company_slug": "palantir", "name": "Palantir"}]
        }
        loaded: Dict[str, Any] = {}
        if os.path.exists(self.config_path):
            try:
                if yaml is not None:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f) or {}
                else:
                    print(f"[PortalScanner] PyYAML not installed; falling back to default portal targets.")
            except Exception as e:
                print(f"[PortalScanner] Error loading config {self.config_path}: {e}")

        portals: Dict[str, Any] = loaded.get("portals", base_portals)

        # Merge verified active slugs from SQLite company slug registry (capped to top 50 active per ATS to prevent network hanging)
        try:
            try:
                from services.company_slug_registry import get_active_slugs
            except ImportError:
                from backend.services.company_slug_registry import get_active_slugs

            active_slugs = get_active_slugs()
            for ats_name, slug_list in active_slugs.items():
                if ats_name not in portals:
                    portals[ats_name] = []
                existing_slugs = {p.get("company_slug") for p in portals[ats_name]}
                # Cap dynamic slugs to 50 active companies per portal to ensure fast execution
                for s in slug_list[:50]:
                    if s and s not in existing_slugs:
                        portals[ats_name].append({"company_slug": s, "name": s.capitalize()})
        except Exception:
            pass

        return {
            "portals": portals,
            "config": loaded.get("config", {
                "min_ats_score_to_notify": 75,
                "roles_keywords": ["AI", "Machine Learning", "ML", "GenAI", "Software Engineer", "Systems"]
            })
        }

    def _format_age(self, dt_str: Optional[str], timestamp_ms: Optional[int] = None) -> str:
        """Helper to convert API date strings or timestamps into a human-friendly age (e.g. '2d ago', 'Today')."""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            if timestamp_ms:
                dt = datetime.fromtimestamp(timestamp_ms / 1000.0, timezone.utc)
            elif dt_str:
                # Replace trailing 'Z' with +00:00 for fromisoformat compatibility
                clean_dt = dt_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_dt)
            else:
                return "Active"

            diff = now - dt
            days = diff.days
            if days <= 0:
                hours = int(diff.total_seconds() // 3600)
                return f"{hours}h ago" if hours > 0 else "Just now"
            elif days == 1:
                return "1d ago"
            elif days < 30:
                return f"{days}d ago"
            else:
                return f"{days // 30}mo ago"
        except Exception:
            return "Active"

    async def scan_greenhouse_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Greenhouse public Board API."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
        jobs = []
        try:
            res = await client.get(url, timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobs", [])
                for rj in raw_jobs:
                    updated_at = rj.get("updated_at")
                    jobs.append({
                        "id": f"gh_{rj.get('id')}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": rj.get("absolute_url", ""),
                        "location": rj.get("location", {}).get("name", "Remote/Unspecified"),
                        "description": rj.get("content", ""),
                        "portal": "greenhouse",
                        "posted_at": updated_at,
                        "age": self._format_age(updated_at)
                    })
        except Exception:
            pass
        return jobs

    async def scan_ashby_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Ashby public Job Board API."""
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
        jobs = []
        try:
            res = await client.get(url, timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobs", [])
                for rj in raw_jobs:
                    pub_at = rj.get("publishedAt")
                    jobs.append({
                        "id": f"ashby_{rj.get('id')}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": rj.get("jobUrl", f"https://jobs.ashbyhq.com/{company_slug}/{rj.get('id')}"),
                        "location": rj.get("location", "Remote/Unspecified"),
                        "description": rj.get("descriptionHtml", rj.get("descriptionPlain", "")),
                        "portal": "ashby",
                        "posted_at": pub_at,
                        "age": self._format_age(pub_at)
                    })
        except Exception:
            pass
        return jobs

    async def scan_lever_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Lever public Postings API."""
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        jobs = []
        try:
            res = await client.get(url, timeout=3.0)
            if res.status_code == 200:
                raw_jobs = res.json()
                for rj in raw_jobs:
                    created_at_ms = rj.get("createdAt")
                    jobs.append({
                        "id": f"lever_{rj.get('id')}",
                        "title": rj.get("text", ""),
                        "company": company_name,
                        "url": rj.get("hostedUrl", ""),
                        "location": rj.get("categories", {}).get("location", "Remote/Unspecified"),
                        "description": rj.get("descriptionPlain", "") or rj.get("description", ""),
                        "portal": "lever",
                        "posted_at": created_at_ms,
                        "age": self._format_age(None, timestamp_ms=created_at_ms)
                    })
        except Exception:
            pass
        return jobs

    async def scan_bamboohr_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from BambooHR public careers endpoint."""
        url = f"https://{company_slug}.bamboohr.com/careers/list"
        jobs = []
        try:
            res = await client.get(url, timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("result", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for rj in raw_jobs:
                    loc = rj.get("location", {})
                    loc_str = f"{loc.get('city', '')}, {loc.get('state', '')}".strip(", ") or "Remote/Unspecified"
                    job_id = rj.get("id", "")
                    jobs.append({
                        "id": f"bamboo_{job_id}",
                        "title": rj.get("jobOpeningName", rj.get("title", "")),
                        "company": company_name,
                        "url": f"https://{company_slug}.bamboohr.com/careers/{job_id}",
                        "location": loc_str,
                        "description": rj.get("description", ""),
                        "portal": "bamboohr",
                        "posted_at": rj.get("dateCreated"),
                        "age": self._format_age(rj.get("dateCreated"))
                    })
        except Exception:
            pass
        return jobs

    async def scan_workday_company(self, client: httpx.AsyncClient, company_slug: str, company_name: str) -> List[Dict[str, Any]]:
        """Fetch active jobs from Workday public Candidate Experience (CXS) endpoint."""
        parts = company_slug.split("|")
        tenant = parts[0]
        instance = parts[1] if len(parts) > 1 else "wd1"
        site = parts[2] if len(parts) > 2 else "External"
        url = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        jobs = []
        try:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            res = await client.post(url, json={"limit": 20, "offset": 0, "searchText": ""}, headers=headers, timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobPostings", [])
                for rj in raw_jobs:
                    ext_path = rj.get("externalPath", "")
                    job_url = f"https://{tenant}.{instance}.myworkdayjobs.com/en-US/{tenant}/{site}{ext_path}" if ext_path else ""
                    jobs.append({
                        "id": f"workday_{rj.get('bulletFields', [ext_path])[0] if rj.get('bulletFields') else ext_path}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": job_url,
                        "location": rj.get("locationsText", "Remote/Unspecified"),
                        "description": rj.get("title", ""),
                        "portal": "workday",
                        "posted_at": rj.get("postedOn"),
                        "age": self._format_age(rj.get("postedOn"))
                    })
        except Exception:
            pass
        return jobs

    def _is_within_timeframe(self, posted_at: Any, timeframe: str) -> bool:
        """Filter jobs based on requested timeframe (24h, 48h, 7d, 14d, 30d, all)."""
        if not posted_at or timeframe in ("all", "any"):
            return True
        try:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            
            # Resolve cutoff timedelta
            tf_map = {
                "24h": timedelta(hours=24),
                "48h": timedelta(hours=48),
                "7d": timedelta(days=7),
                "14d": timedelta(days=14),
                "30d": timedelta(days=30),
            }
            cutoff_delta = tf_map.get(timeframe, timedelta(hours=48))
            cutoff_dt = now - cutoff_delta

            if isinstance(posted_at, (int, float)):
                dt = datetime.fromtimestamp(posted_at / 1000.0, timezone.utc)
            elif isinstance(posted_at, str):
                clean_dt = posted_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_dt)
            else:
                return True

            return dt >= cutoff_dt
        except Exception:
            return True

    def _matches_location(self, job_loc: str, target_loc: Optional[str]) -> bool:
        """Helper to match job location against target user location."""
        if not target_loc or target_loc.lower() in ("all", "any", "worldwide", "global"):
            return True
        t_lower = target_loc.lower().strip()
        j_lower = (job_loc or "").lower()

        # If job is remote/remote-friendly, it matches any location
        if "remote" in j_lower or "anywhere" in j_lower:
            return True

        # Check direct substring matching (e.g. 'london' in 'london, uk')
        if t_lower in j_lower:
            return True

        # Common city / country aliases
        aliases = {
            "london": ["london", "united kingdom", "uk", "great britain", "england"],
            "uk": ["london", "united kingdom", "uk", "manchester", "birmingham", "edinburgh", "cambridge", "oxford", "bristol"],
            "united kingdom": ["london", "united kingdom", "uk", "manchester", "cambridge", "oxford"],
            "us": ["united states", "usa", "san francisco", "new york", "seattle", "austin", "boston"],
            "united states": ["united states", "usa", "san francisco", "new york", "seattle", "austin", "boston"],
            "san francisco": ["san francisco", "sf", "bay area", "california", "ca"],
            "new york": ["new york", "nyc", "ny"]
        }
        for alias in aliases.get(t_lower, []):
            if alias in j_lower:
                return True
        return False

    async def scan_all_portals(
        self,
        target_keywords: Optional[List[str]] = None,
        timeframe: str = "48h",
        location: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Scans all configured target portals concurrently with keyword, timeframe & location filtering."""
        portals_def = self.config.get("portals", {})
        keywords = target_keywords or self.config.get("config", {}).get("roles_keywords", [])
        keywords_lower = [k.lower() for k in keywords]

        all_jobs: List[Dict[str, Any]] = []
        tasks = []
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        async with httpx.AsyncClient(headers={"User-Agent": ua}, limits=limits, timeout=5.0) as client:
            # Greenhouse
            for comp in portals_def.get("greenhouse", []):
                tasks.append(self.scan_greenhouse_company(client, comp["company_slug"], comp["name"]))
            # Ashby
            for comp in portals_def.get("ashby", []):
                tasks.append(self.scan_ashby_company(client, comp["company_slug"], comp["name"]))
            # Lever
            for comp in portals_def.get("lever", []):
                tasks.append(self.scan_lever_company(client, comp["company_slug"], comp["name"]))
            # BambooHR
            for comp in portals_def.get("bamboohr", []):
                tasks.append(self.scan_bamboohr_company(client, comp["company_slug"], comp["name"]))
            # Workday
            for comp in portals_def.get("workday", []):
                tasks.append(self.scan_workday_company(client, comp["company_slug"], comp["name"]))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_jobs.extend(r)

        # Apply Timeframe Filter
        if timeframe and timeframe not in ("all", "any"):
            all_jobs = [j for j in all_jobs if self._is_within_timeframe(j.get("posted_at"), timeframe)]

        # Apply Location Filter (if specified)
        if location and location.lower() not in ("all", "any", "worldwide", "global"):
            all_jobs = [j for j in all_jobs if self._matches_location(j.get("location", ""), location)]

        # Apply Keyword Filter
        if keywords_lower:
            # Flatten sub-terms if queries contain commas (e.g. ['AI Engineer', 'Machine Learning'])
            terms = set()
            for kw in keywords_lower:
                for sub in kw.split(","):
                    sub_clean = sub.strip()
                    if sub_clean:
                        terms.add(sub_clean)

            filtered = [
                j for j in all_jobs
                if any(t in j["title"].lower() or t in j.get("description", "").lower() for t in terms)
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
