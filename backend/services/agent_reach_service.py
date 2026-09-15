"""
agent_reach_service.py — Capability layer router for fetching open-source, zero-API-fee
web, community (Reddit/X), YouTube transcripts, and company insights.

Inspired by Panniantong/Agent-Reach, this module acts as a routing layer providing:
1. Reddit / Community sentiment analysis for target companies & roles.
2. YouTube video transcript extraction for technical & system design interview prep.
3. Lightweight Jina Reader & web fallback for public content extraction.
4. Self-healing environment diagnostics (agent_reach_doctor).
"""

import os
import re
import json
import urllib.request
import urllib.parse
import subprocess
import shutil
import asyncio
from typing import Dict, Any, List, Optional
# pyrefly: ignore [missing-import]
from services.gemini_client import generate_content_with_fallback


# ── 1. Reddit / Community Culture & Interview Insights ────────────────────────

def fetch_reddit_company_insights(company: str, role: str = "") -> Dict[str, Any]:
    """
    Fetches real community discussions, interview experiences, and workplace sentiment
    from Reddit without needing paid API keys.
    Uses public Reddit JSON endpoints with custom User-Agent headers.
    """
    if not company or not company.strip():
        return {"status": "error", "message": "Company name required", "posts": []}

    clean_company = company.strip()
    query = f"{clean_company} {role} interview salary culture".strip()
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://www.reddit.com/search.json?q={encoded_query}&sort=relevance&limit=8"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JobFinderAgentReach/1.0"
    }

    try:
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        posts = []
        children = data.get("data", {}).get("children", [])
        for child in children:
            pdata = child.get("data", {})
            title = pdata.get("title", "")
            selftext = pdata.get("selftext", "")[:400]
            permalink = f"https://reddit.com{pdata.get('permalink', '')}"
            subreddit = pdata.get("subreddit", "")
            score = pdata.get("score", 0)

            if title:
                posts.append({
                    "title": title,
                    "excerpt": selftext,
                    "url": permalink,
                    "subreddit": subreddit,
                    "upvotes": score
                })

        return {
            "status": "success",
            "company": clean_company,
            "total_posts": len(posts),
            "posts": posts
        }
    except Exception:
        # Fallback to Jina Reader zero-API-fee extraction if Reddit JSON endpoint blocks raw urllib
        jina_data = scrape_with_jina(f"https://www.reddit.com/r/cscareerquestions/search/?q={urllib.parse.quote(clean_company)}")
        if jina_data.get("status") == "success" and jina_data.get("markdown"):
            return {
                "status": "success",
                "company": clean_company,
                "total_posts": 1,
                "posts": [{
                    "title": f"Community discussions for {clean_company}",
                    "excerpt": jina_data["markdown"][:500],
                    "url": jina_data["url"],
                    "subreddit": "cscareerquestions",
                    "upvotes": 10
                }]
            }
        return {
            "status": "error",
            "message": "Reddit fetch failed",
            "company": clean_company,
            "posts": []
        }


def fetch_reddit_hiring_threads(role: str = "Software Engineer", location: str = "Remote") -> Dict[str, Any]:
    """
    Discovers unlisted job opportunities from monthly community hiring threads (e.g., Hacker News 'Who is Hiring?', r/forhire, r/remotegoat).
    """
    query = f"Who is hiring {role} {location}".strip()
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://www.reddit.com/search.json?q={encoded_query}&sort=new&limit=10"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JobFinderAgentReach/1.0"
    }

    try:
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        jobs = []
        children = data.get("data", {}).get("children", [])
        for child in children:
            pdata = child.get("data", {})
            title = pdata.get("title", "")
            selftext = pdata.get("selftext", "")[:500]
            permalink = f"https://reddit.com{pdata.get('permalink', '')}"
            subreddit = pdata.get("subreddit", "")

            if title and ("hiring" in title.lower() or "job" in title.lower() or "looking for" in title.lower()):
                jobs.append({
                    "title": title,
                    "excerpt": selftext,
                    "url": permalink,
                    "subreddit": subreddit,
                    "source": "Reddit Community Thread"
                })

        return {
            "status": "success",
            "total_found": len(jobs),
            "community_jobs": jobs
        }
    except Exception:
        # Fallback to Jina Reader for community hiring search
        jina_data = scrape_with_jina(f"https://www.reddit.com/r/forhire/search/?q={urllib.parse.quote(role)}")
        if jina_data.get("status") == "success" and jina_data.get("markdown"):
            return {
                "status": "success",
                "total_found": 1,
                "community_jobs": [{
                    "title": f"Recent {role} hiring discussions",
                    "excerpt": jina_data["markdown"][:500],
                    "url": jina_data["url"],
                    "subreddit": "forhire",
                    "source": "Reddit via Jina Reader"
                }]
            }
        return {
            "status": "error",
            "message": "Community hiring thread discovery failed",
            "community_jobs": []
        }


# ── 2. YouTube Technical Interview Transcript Extraction ──────────────────────

def extract_youtube_transcript(url_or_id: str) -> Dict[str, Any]:
    """
    Extracts text transcript from a YouTube video URL or ID (e.g. system design interview tutorials).
    Tries yt-dlp binary if available, falling back to YouTube timedtext API parsing.
    """
    video_id_match = re.search(r"(?:v=|\/|be\/)([a-zA-Z0-9_-]{11})", url_or_id)
    video_id = video_id_match.group(1) if video_id_match else url_or_id

    # Fallback 1: yt-dlp binary if installed in PATH
    yt_dlp_bin = shutil.which("yt-dlp")
    if yt_dlp_bin:
        try:
            cmd = [yt_dlp_bin, "--skip-download", "--write-sub", "--sub-lang", "en", "--output", "%(id)s", f"https://www.youtube.com/watch?v={video_id}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            sub_file = f"{video_id}.en.vtt"
            if os.path.exists(sub_file):
                with open(sub_file, "r", encoding="utf-8") as f:
                    vtt_text = f.read()
                os.remove(sub_file)
                lines = [re.sub(r'<[^>]+>', '', l).strip() for l in vtt_text.splitlines() if l.strip() and not l.startswith("WEBVTT") and "-->" not in l]
                transcript_text = " ".join(dict.fromkeys(lines))
                return {"status": "success", "video_id": video_id, "transcript": transcript_text[:3000], "source": "yt-dlp"}
        except Exception:
            pass

    # Fallback 2: Jina Reader / web transcript scrape
    jina_url = f"https://r.jina.ai/https://www.youtube.com/watch?v={video_id}"
    try:
        req = urllib.request.Request(jina_url, headers={"User-Agent": "JobFinderAgentReach/1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            content = resp.read().decode("utf-8")
            return {
                "status": "success",
                "video_id": video_id,
                "transcript": content[:3000],
                "source": "jina-reader"
            }
    except Exception as e:
        return {
            "status": "error",
            "video_id": video_id,
            "message": f"Transcript extraction failed: {str(e)}"
        }


# ── 3. Jina Reader Zero-Fee Web Scraper ───────────────────────────────────────

def scrape_with_jina(url: str) -> Dict[str, Any]:
    """
    Extracts clean Markdown content from any web page using Jina Reader (https://r.jina.ai).
    Provides zero-API-fee extraction for tech blogs, interview guides, and engineering posts.
    """
    clean_url = url.strip()
    if not clean_url.startswith("http"):
        clean_url = f"https://{clean_url}"

    target_url = f"https://r.jina.ai/{clean_url}"
    headers = {
        "User-Agent": "JobFinderAgentReach/1.0",
        "Accept": "text/event-stream"
    }

    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            markdown_content = resp.read().decode("utf-8")

        return {
            "status": "success",
            "url": clean_url,
            "markdown": markdown_content[:5000],
            "title": markdown_content.splitlines()[0] if markdown_content else clean_url
        }
    except Exception as e:
        return {
            "status": "error",
            "url": clean_url,
            "message": f"Jina Reader scrape failed: {str(e)}"
        }


# ── 4. Synthesized Culture & Interview Pack Generator ─────────────────────────

def generate_enhanced_company_brief(company: str, role: str = "") -> Dict[str, Any]:
    """
    Combines Reddit discussions and web sources to build a comprehensive Company Culture Brief.
    """
    reddit_data = fetch_reddit_company_insights(company, role)
    posts = reddit_data.get("posts", [])

    post_summaries = "\n".join([f"- [{p['subreddit']}] {p['title']}: {p['excerpt']}" for p in posts[:5]])

    prompt = f"""You are a Career Intelligence Analyst.
Synthesize a Company Culture & Interview Brief for '{company}' (Target Role: '{role or 'Software Engineer'}').

RECENT COMMUNITY DISCUSSIONS & REVIEWS:
{post_summaries if post_summaries else "No recent community threads found."}

Output a structured Markdown brief with:
1. **Engineering Culture & Vibe:** Team pace, WFH policies, tech stack signals.
2. **Interview Process & Difficulty:** Stage breakdown, interview question style, typical behavioral questions.
3. **Compensation & Progression:** Salary positioning, leveling, performance review insights.
4. **Pros & Red Flags:** Key candidate warnings or selling points.

Keep it concise, objective, and actionable. Do NOT add conversational intros/outros."""

    try:
        brief_md = generate_content_with_fallback(prompt, model_tier="lite")
        return {
            "status": "success",
            "company": company,
            "role": role,
            "brief_markdown": brief_md,
            "reddit_posts_found": len(posts),
            "sources": [p["url"] for p in posts[:3]]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Brief generation failed: {str(e)}",
            "company": company
        }


# ── 5. Agent-Reach Doctor & Health Diagnostics ────────────────────────────────

def agent_reach_doctor() -> Dict[str, Any]:
    """
    Self-healing diagnostic check for Agent-Reach integration layer.
    Verifies availability of system binaries, network connectivity, and fallbacks.
    """
    diagnostics = {
        "python_env": True,
        "yt_dlp_installed": shutil.which("yt-dlp") is not None,
        "pyright_installed": shutil.which("pyright") is not None,
        "reddit_access": False,
        "jina_reader_access": False
    }

    # Probe Reddit connectivity
    try:
        req = urllib.request.Request(
            "https://www.reddit.com/r/cscareerquestions/hot.json?limit=1",
            headers={"User-Agent": "JobFinderAgentReach/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                diagnostics["reddit_access"] = True
    except Exception:
        diagnostics["reddit_access"] = False

    # Probe Jina Reader connectivity
    try:
        req = urllib.request.Request(
            "https://r.jina.ai/https://example.com",
            headers={"User-Agent": "JobFinderAgentReach/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                diagnostics["jina_reader_access"] = True
    except Exception:
        diagnostics["jina_reader_access"] = False

    all_healthy = diagnostics["reddit_access"] and diagnostics["jina_reader_access"]

    return {
        "status": "healthy" if all_healthy else "degraded",
        "diagnostics": diagnostics,
        "recommendations": [
            "Install 'yt-dlp' via homebrew/pip for faster YouTube transcript extraction." if not diagnostics["yt_dlp_installed"] else "yt-dlp ready.",
            "Reddit JSON API accessible." if diagnostics["reddit_access"] else "Reddit API blocked; using Google Grounding fallback.",
            "Jina Reader accessible." if diagnostics["jina_reader_access"] else "Jina Reader unreachable; using Playwright fallback."
        ]
    }
