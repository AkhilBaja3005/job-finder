import os
import shutil
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from services.session_store import (
    BASE_DIR,
    UPLOAD_DIR,
    OUTPUT_DIR,
    USER_DATA_DIR,
    get_session_data,
    set_session_data,
    LLMClientLogQueue,
    _get_user_storage_dirs,
    _user_output_paths,
    _safe_key
)
from services.cron_scheduler import background_cron_worker
from routes.auth_routes import router as auth_router
from routes.resume_routes import router as resume_router
from routes.job_routes import router as job_router, _extract_company_from_jd
from routes.ai_routes import router as ai_router
from routes.admin_routes import router as admin_router
from utils.latex_utils import compile_and_check_page_metrics, apply_latex_hotfix, generate_latex_from_json
from services.overleaf import upload_zip_to_tmpfiles


def _sync_fallback_resume_cls():
    """Ensure baseline resume.cls is synced to uploads and assets."""
    assets_cls = os.path.join(BASE_DIR, "assets", "resume.cls")
    uploads_cls = os.path.join(UPLOAD_DIR, "resume.cls")
    if os.path.exists(assets_cls) and not os.path.exists(uploads_cls):
        try:
            shutil.copy2(assets_cls, uploads_cls)
            print(f"Synced fallback resume.cls from {assets_cls} to {uploads_cls}")
        except Exception as e:
            print(f"Warning: Failed to sync resume.cls to uploads: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure directory structure and baseline assets
    _sync_fallback_resume_cls()

    # Launch Playwright browser instance if available
    browser = None
    playwright = None
    try:
        from playwright.async_api import async_playwright
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        app.state.browser = browser
        app.state.playwright = playwright
        print("🟢 Headless browser pool initialized successfully.")
    except Exception as e:
        print(f"⚠️ Playwright initialization skipped/failed: {e}")
        app.state.browser = None
        app.state.playwright = None

    # Start background cron worker
    cron_task = asyncio.create_task(background_cron_worker())

    yield

    # Shutdown
    cron_task.cancel()
    if browser:
        try:
            await browser.close()
        except Exception:
            pass
    if playwright:
        try:
            await playwright.stop()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Application & Router Mounts
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Job Finder & ATS Tailor API",
    description="Full-stack automated Job Discovery, ATS Match Scoring, Resume Tailoring, and AI Auto-Apply Backend",
    version="3.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Domain-Specific Routers
app.include_router(auth_router)
app.include_router(resume_router)
app.include_router(job_router)
app.include_router(ai_router)
app.include_router(admin_router)

# Mount Static Asset Directories
if os.path.exists(OUTPUT_DIR):
    app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

if os.path.exists(os.path.join(BASE_DIR, "assets")):
    app.mount("/backend_assets", StaticFiles(directory=os.path.join(BASE_DIR, "assets")), name="backend_assets")

# Mount Frontend Build & SPA Catch-All Route
frontend_dist = os.path.abspath(os.path.join(BASE_DIR, "../frontend/dist"))
if not os.path.exists(frontend_dist):
    frontend_dist = "/app/frontend/dist"
if not os.path.exists(frontend_dist):
    frontend_dist = os.path.abspath(os.path.join(BASE_DIR, "frontend/dist"))

if os.path.exists(frontend_dist):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{rest_of_path:path}", response_class=HTMLResponse)
    async def serve_spa_frontend(rest_of_path: str):
        # 1. Block directory traversal and sensitive environment / key scanners
        forbidden_substrings = ("..", ".env", ".aws", ".git", ".ssh", "passwd", "environ", "actuator", "graphql", "config.json", "credentials", "phpinfo", "swagger", "meta-data")
        if any(bad in rest_of_path.lower() for bad in forbidden_substrings):
            raise HTTPException(status_code=404, detail="Not Found")

        # 2. Block direct access to internal api routes if not handled by routers
        if rest_of_path and not rest_of_path.startswith("api"):
            try:
                # Resolve canonical safe path within frontend_dist
                target = os.path.abspath(os.path.join(frontend_dist, rest_of_path))
                if target.startswith(frontend_dist) and os.path.exists(target) and os.path.isfile(target):
                    return FileResponse(target)
            except Exception:
                pass

        index_file = os.path.join(frontend_dist, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return HTMLResponse("<h1>Job Finder Backend is Running 🟢</h1><p>Frontend assets not found.</p>", status_code=200)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
