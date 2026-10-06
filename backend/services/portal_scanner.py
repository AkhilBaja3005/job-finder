"""
portal_scanner.py — Automated ATS Job Portal Scanner (Greenhouse, Ashby, Lever)

Pings public ATS endpoints without browser overhead, filters by user keywords,
and auto-scores matches deterministically against the candidate's profile.
"""

import os
import re
import json
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
from utils.text_cleaner import clean_html_to_markdown

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

        portals_dict = loaded.get("portals", base_portals)
        try:
            try:
                from services.company_slug_registry import get_active_slugs
            except ImportError:
                from backend.services.company_slug_registry import get_active_slugs

            db_slugs = get_active_slugs()
            for ats_name, slug_list in db_slugs.items():
                if ats_name not in portals_dict:
                    portals_dict[ats_name] = []
                existing = {p["company_slug"] for p in portals_dict[ats_name] if isinstance(p, dict) and p.get("company_slug")}
                for s in slug_list:
                    if s and s not in existing:
                        disp_name = s.split("|")[0].replace("-", " ").replace("_", " ").title() if "|" in s else s.replace("-", " ").replace("_", " ").title()
                        portals_dict[ats_name].append({"company_slug": s, "name": disp_name})
        except Exception as e:
            print(f"[PortalScanner] Note: Could not load DB active slugs in _load_config: {e}")

        return {
            "portals": portals_dict,
            "config": loaded.get("config", {
                "min_ats_score_to_notify": 75,
                "roles_keywords": ["AI", "Machine Learning", "ML", "GenAI", "Software Engineer", "Systems"]
            })
        }

    def _get_active_portals_for_scan(self, target_portals: Optional[List[str]] = None) -> Dict[str, List[Dict[str, str]]]:
        """Dynamically fetch confirmed active slugs for the requested portals."""
        active_portals: Dict[str, List[Dict[str, str]]] = {
            "greenhouse": [],
            "ashby": [],
            "lever": [],
            "bamboohr": [],
            "workday": []
        }
        
        filter_lower = [p.lower().strip() for p in (target_portals or []) if p.strip()]
        is_single_targeted = len(filter_lower) == 1 and "all" not in filter_lower
        max_boards = 800 if is_single_targeted else 250

        base = self.config.get("portals", {})
        for ats_k, comp_list in base.items():
            if ats_k not in active_portals:
                active_portals[ats_k] = []
            for c in comp_list[:max_boards]:
                if isinstance(c, dict) and c.get("company_slug"):
                    active_portals[ats_k].append(c)

        return active_portals

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
        """Fetch active jobs with full descriptions from Greenhouse public Board API."""
        url = f"https://api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
        jobs = []
        try:
            res = await client.get(url, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobs", [])
                for rj in raw_jobs:
                    updated_at = rj.get("updated_at")
                    raw_content = rj.get("content", "")
                    clean_desc = clean_html_to_markdown(raw_content) if raw_content else rj.get("title", "")
                    jobs.append({
                        "id": f"gh_{rj.get('id')}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": rj.get("absolute_url", f"https://boards.greenhouse.io/{company_slug}/jobs/{rj.get('id')}"),
                        "location": rj.get("location", {}).get("name", "Remote/Unspecified"),
                        "description": clean_desc,
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
            res = await client.get(url, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobs", [])
                for rj in raw_jobs:
                    pub_at = rj.get("publishedAt")
                    raw_d = rj.get("descriptionHtml") or rj.get("descriptionPlain", "")
                    clean_desc = clean_html_to_markdown(raw_d) if raw_d else rj.get("title", "")
                    jobs.append({
                        "id": f"ashby_{rj.get('id')}",
                        "title": rj.get("title", ""),
                        "company": company_name,
                        "url": rj.get("jobUrl", f"https://jobs.ashbyhq.com/{company_slug}/{rj.get('id')}"),
                        "location": rj.get("location", "Remote/Unspecified"),
                        "description": clean_desc,
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
            res = await client.get(url, timeout=6.0)
            if res.status_code == 200:
                raw_jobs = res.json()
                for rj in raw_jobs:
                    created_at_ms = rj.get("createdAt")
                    
                    full_parts = []
                    if rj.get("descriptionPlain"):
                        full_parts.append(rj["descriptionPlain"].strip())
                    elif rj.get("description"):
                        full_parts.append(clean_html_to_markdown(rj["description"]))

                    for l in rj.get("lists", []):
                        header = l.get("text", "")
                        content_html = l.get("content", "")
                        clean_content = clean_html_to_markdown(content_html)
                        if header and clean_content:
                            full_parts.append(f"\n{header}\n{clean_content}")
                        elif clean_content:
                            full_parts.append(clean_content)

                    if rj.get("additionalPlain"):
                        full_parts.append(rj["additionalPlain"].strip())

                    full_desc = clean_html_to_markdown("\n\n".join([p for p in full_parts if p.strip()])) or rj.get("text", "")

                    jobs.append({
                        "id": f"lever_{rj.get('id')}",
                        "title": rj.get("text", ""),
                        "company": company_name,
                        "url": rj.get("hostedUrl", ""),
                        "location": rj.get("categories", {}).get("location", "Remote/Unspecified"),
                        "description": full_desc,
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
            res = await client.get(url, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("result", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for rj in raw_jobs:
                    loc = rj.get("location", {})
                    loc_str = f"{loc.get('city', '')}, {loc.get('state', '')}".strip(", ") or "Remote/Unspecified"
                    job_id = str(rj.get("id", ""))
                    raw_d = rj.get("description", "")
                    clean_d = clean_html_to_markdown(raw_d) if raw_d else ""
                    jobs.append({
                        "id": f"bamboo_{job_id}",
                        "job_id": job_id,
                        "company_slug": company_slug,
                        "title": rj.get("jobOpeningName", rj.get("title", "")),
                        "company": company_name,
                        "url": f"https://{company_slug}.bamboohr.com/careers/{job_id}",
                        "location": loc_str,
                        "description": clean_d or rj.get("jobOpeningName", ""),
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
            res = await client.post(url, json={"limit": 20, "offset": 0, "searchText": ""}, headers=headers, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                raw_jobs = data.get("jobPostings", [])
                disp_company = company_name.split("|")[0].replace("-", " ").replace("_", " ").title() if "|" in company_name else company_name
                for rj in raw_jobs:
                    ext_path = rj.get("externalPath", "")
                    job_url = f"https://{tenant}.{instance}.myworkdayjobs.com/en-US/{site}{ext_path}" if ext_path else ""
                    jobs.append({
                        "id": f"workday_{rj.get('bulletFields', [ext_path])[0] if rj.get('bulletFields') else ext_path}",
                        "tenant": tenant,
                        "instance": instance,
                        "site": site,
                        "ext_path": ext_path,
                        "title": rj.get("title", ""),
                        "company": disp_company,
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
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            tf_hours = {
                "24h": 24,
                "48h": 48,
                "7d": 7 * 24,
                "14d": 14 * 24,
                "30d": 30 * 24,
            }.get(timeframe, 48)

            if isinstance(posted_at, (int, float)):
                dt = datetime.fromtimestamp(posted_at / 1000.0, timezone.utc)
                return (now - dt).total_seconds() / 3600.0 <= tf_hours

            if isinstance(posted_at, str):
                p_str = posted_at.strip().lower()
                if "today" in p_str or "just now" in p_str:
                    return True
                if "yesterday" in p_str:
                    return tf_hours >= 24

                # Match 'posted X days ago', 'posted X+ days ago', 'Xd ago'
                m_days = re.search(r'(\d+)\+?\s*(?:days?|d)\s*ago', p_str)
                if m_days:
                    days = int(m_days.group(1))
                    return (days * 24) <= tf_hours

                # Match 'Xh ago', 'X hours ago'
                m_hours = re.search(r'(\d+)\s*(?:hours?|h)\s*ago', p_str)
                if m_hours:
                    hours = int(m_hours.group(1))
                    return hours <= tf_hours

                # Reject months/years ago for short timeframes
                if "month" in p_str or "year" in p_str or "mo ago" in p_str:
                    return False

                # Try standard ISO parse
                clean_dt = posted_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_dt)
                return (now - dt).total_seconds() / 3600.0 <= tf_hours

            return False
        except Exception:
            return False

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
        location: Optional[str] = None,
        target_portals: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Scans configured target portals concurrently with keyword, timeframe & location filtering."""
        portals_def = self._get_active_portals_for_scan(target_portals)
        keywords = target_keywords or self.config.get("config", {}).get("roles_keywords", [])
        keywords_lower = [k.lower() for k in keywords]

        filter_portals = [p.strip().lower() for p in (target_portals or []) if p.strip()]
        is_targeted = len(filter_portals) > 0 and "all" not in filter_portals

        all_jobs: List[Dict[str, Any]] = []
        tasks = []
        sem = asyncio.Semaphore(100)
        limits = httpx.Limits(max_keepalive_connections=150, max_connections=300)
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        
        async with httpx.AsyncClient(headers={"User-Agent": ua}, limits=limits, timeout=3.5) as client:
            async def _safe_scan(scanner_func, comp_slug, comp_name):
                try:
                    async with sem:
                        return await asyncio.wait_for(scanner_func(client, comp_slug, comp_name), timeout=3.5)
                except Exception:
                    return []

            # Greenhouse
            if not is_targeted or "greenhouse" in filter_portals:
                for comp in portals_def.get("greenhouse", []):
                    tasks.append(_safe_scan(self.scan_greenhouse_company, comp["company_slug"], comp["name"]))
            # Ashby
            if not is_targeted or "ashby" in filter_portals:
                for comp in portals_def.get("ashby", []):
                    tasks.append(_safe_scan(self.scan_ashby_company, comp["company_slug"], comp["name"]))
            # Lever
            if not is_targeted or "lever" in filter_portals:
                for comp in portals_def.get("lever", []):
                    tasks.append(_safe_scan(self.scan_lever_company, comp["company_slug"], comp["name"]))
            # BambooHR
            if not is_targeted or "bamboohr" in filter_portals or "bamboo" in filter_portals:
                for comp in portals_def.get("bamboohr", []):
                    tasks.append(_safe_scan(self.scan_bamboohr_company, comp["company_slug"], comp["name"]))
            # Workday
            if not is_targeted or "workday" in filter_portals:
                for comp in portals_def.get("workday", []):
                    tasks.append(_safe_scan(self.scan_workday_company, comp["company_slug"], comp["name"]))

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
            # Build regex patterns for exact tokens and phrases
            patterns = []
            for kw in keywords_lower:
                for sub in kw.split(","):
                    sub_clean = sub.strip()
                    if sub_clean:
                        # Full phrase with word boundaries
                        patterns.append(re.compile(r'\b' + re.escape(sub_clean) + r'\b', re.IGNORECASE))
                        # Individual significant words
                        for word in sub_clean.split():
                            w_clean = word.strip().strip(".,/-()[]{}'\"")
                            if len(w_clean) >= 2 and w_clean.lower() not in ("and", "or", "the", "in", "of", "for", "with", "to", "at", "on", "by", "as", "is", "an", "a"):
                                patterns.append(re.compile(r'\b' + re.escape(w_clean) + r'\b', re.IGNORECASE))

            filtered = [
                j for j in all_jobs
                if any(p.search(j["title"]) or p.search(j.get("description", "")) for p in patterns)
            ]
        else:
            filtered = all_jobs

        # Concurrently enrich surviving BambooHR & Workday jobs with full descriptions
        enrich_targets = [
            j for j in filtered
            if (j.get("portal") in ("bamboohr", "workday") and len(j.get("description", "")) < 200)
        ]
        if enrich_targets:
            async with httpx.AsyncClient(timeout=4.0) as enrich_client:
                async def _enrich_one(job_item):
                    try:
                        p = job_item.get("portal")
                        if p == "bamboohr":
                            c_slug = job_item.get("company_slug")
                            jid = job_item.get("job_id")
                            if c_slug and jid:
                                detail_url = f"https://{c_slug}.bamboohr.com/careers/{jid}/detail"
                                r = await enrich_client.get(detail_url)
                                if r.status_code == 200:
                                    raw_d = r.json().get("result", {}).get("jobOpening", {}).get("description", "")
                                    if raw_d:
                                        job_item["description"] = clean_html_to_markdown(raw_d)
                        elif p == "workday":
                            tenant = job_item.get("tenant")
                            instance = job_item.get("instance", "wd1")
                            site = job_item.get("site", "External")
                            ext_path = job_item.get("ext_path")
                            if tenant and ext_path:
                                cxs_url = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{ext_path}"
                                r = await enrich_client.get(cxs_url)
                                if r.status_code == 200:
                                    raw_d = r.json().get("jobPostingInfo", {}).get("jobDescription", "")
                                    if raw_d:
                                        job_item["description"] = clean_html_to_markdown(raw_d)
                    except Exception:
                        pass

                await asyncio.gather(*[_enrich_one(j) for j in enrich_targets], return_exceptions=True)

        return filtered

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
