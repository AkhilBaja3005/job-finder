"""
Obscura Lightweight Scraper Service
-----------------------------------
Integrates h4ckf0r0day/obscura (lightweight rust/V8 headless browser with stealth TLS impersonation).
Serves as an ultra-fast, memory-efficient headless scraper for cloud deployments (Hugging Face Spaces, Docker)
where heavy Chromium/Playwright browsers easily exceed container memory limits (512MB - 1GB RAM).

Provides automatic fallback to Playwright or standard requests if Obscura binary is not found.
"""

import os
import shutil
import asyncio
import json
import logging
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

logger = logging.getLogger("obscura_scraper")

# Detect obscura binary path in priority order:
# 1. Environment variable OBSCURA_PATH
# 2. /usr/local/bin/obscura (Docker / HF Spaces)
# 3. ~/.obscura/bin/obscura (local user install)
# 4. PATH lookup
def get_obscura_binary() -> Optional[str]:
    custom_path = os.getenv("OBSCURA_PATH")
    if custom_path and os.path.exists(custom_path) and os.access(custom_path, os.X_OK):
        return custom_path
    
    standard_paths = [
        "/usr/local/bin/obscura",
        os.path.expanduser("~/.obscura/bin/obscura"),
    ]
    for p in standard_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
            
    which_path = shutil.which("obscura")
    if which_path and os.access(which_path, os.X_OK):
        return which_path
        
    return None

def is_obscura_available() -> bool:
    return get_obscura_binary() is not None

async def fetch_page_with_obscura(url: str, timeout: int = 30, stealth: bool = True) -> Optional[str]:
    """
    Executes obscura fetch to download and execute JavaScript within Obscura's V8 isolate,
    returning the rendered HTML string.
    """
    binary = get_obscura_binary()
    if not binary:
        return None

    cmd = [binary, "fetch"]
    if stealth:
        cmd.append("--stealth")
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0 and stdout:
            return stdout.decode("utf-8", errors="ignore")
        else:
            logger.warning(f"[Obscura] Exit code {proc.returncode} for {url}: {stderr.decode('utf-8', errors='ignore')[:200]}")
            return None
    except asyncio.TimeoutError:
        logger.warning(f"[Obscura] Timeout ({timeout}s) fetching {url}")
        try:
            proc.kill()
        except Exception:
            pass
        return None
    except Exception as e:
        logger.error(f"[Obscura] Execution error: {e}")
        return None

async def scrape_with_obscura(url: str, eval_script: Optional[str] = None, timeout: int = 30) -> Optional[Dict[str, Any]]:
    """
    Executes obscura scrape command returning structured JSON evaluation output.
    """
    binary = get_obscura_binary()
    if not binary:
        return None

    cmd = [binary, "scrape", "--stealth", "--format", "json", "--timeout", str(timeout)]
    if eval_script:
        cmd.extend(["-e", eval_script])
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        if proc.returncode == 0 and stdout:
            raw_out = stdout.decode("utf-8", errors="ignore").strip()
            # Obscura may print a preliminary line before JSON
            json_start = raw_out.find("{")
            if json_start != -1:
                return json.loads(raw_out[json_start:])
        return None
    except Exception as e:
        logger.error(f"[Obscura] Scrape error for {url}: {e}")
        return None

async def scrape_job_with_obscura(url: str) -> Optional[Dict[str, Any]]:
    """
    Scrapes job details using Obscura's stealth browser.
    Extracts title, company, clean text, and html without triggering bot blockers.
    """
    html = await fetch_page_with_obscura(url, timeout=30, stealth=True)
    if not html or len(html) < 200:
        return None

    # Bot block detection check
    lower_html = html.lower()
    blocked_indicators = [
        "cloudflare security verification",
        "verify you are human",
        "just a moment...",
        "access denied",
        "enable javascript and cookies"
    ]
    if any(b in lower_html for b in blocked_indicators) and len(html) < 3000:
        logger.warning(f"[Obscura] Detected challenge page for {url}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    # Clean scripts, styles, meta
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()

    title = ""
    title_tag = soup.select_one("h1") or soup.select_one("h2") or soup.find("title")
    if title_tag:
        title = title_tag.get_text().strip()

    # Search for common job posting container selectors
    desc_elem = (
        soup.select_one("#jobDescriptionText") or # Indeed
        soup.select_one(".jobsearch-JobComponent-description") or # Indeed
        soup.select_one(".show-more-less-html__markup") or # LinkedIn
        soup.select_one(".description__text") or # LinkedIn
        soup.select_one(".content-intro") or # Greenhouse
        soup.select_one("#content") or
        soup.select_one("main") or
        soup.select_one("article") or
        soup.body
    )

    clean_text = desc_elem.get_text(separator="\n").strip() if desc_elem else soup.get_text(separator="\n").strip()
    clean_lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
    description = "\n".join(clean_lines)

    if len(description) < 100:
        return None

    return {
        "title": title or "Job Opportunity",
        "description": description,
        "raw_text": description,
        "company": "",
        "url": url,
        "html": html,
        "engine": "obscura"
    }
