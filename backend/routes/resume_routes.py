import os
import re
import json
import uuid
import shutil
import asyncio
import subprocess
import traceback
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Response, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from services.session_store import (
    BASE_DIR,
    UPLOAD_DIR,
    OUTPUT_DIR,
    _safe_key,
    _get_user_storage_dirs,
    _user_output_paths,
    get_session_data,
    set_session_data
)
from services.auth import async_get_user_by_token
from services.resume_parser import parse_resume
from utils.latex_utils import generate_latex_from_json, apply_latex_hotfix, compile_and_check_page_metrics
from services.overleaf import upload_zip_to_tmpfiles
from services.ats_scorer import evaluate_master_resume

router = APIRouter(tags=["Resume Management"])

MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB limit


def _get_guest_state_file(token: Optional[str] = None) -> str:
    key = _safe_key(token)
    _, user_out_dir = _get_user_storage_dirs(key)
    return os.path.join(user_out_dir, f"resume_state_{key}.json")


def _build_original_latex(resume_data: dict, master_path: Optional[str] = None) -> str:
    if master_path and master_path.endswith(".tex") and os.path.exists(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            return f.read()
    return apply_latex_hotfix(generate_latex_from_json(resume_data))


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────
class LatexDownloadRequest(BaseModel):
    latex_code: str


class CoverLetterDownloadRequest(BaseModel):
    cover_letter: str


class CompileLatexRequest(BaseModel):
    latex_code: str


class OverleafRequest(BaseModel):
    latex_code: str
    candidate_name: Optional[str] = ""
    job_title: Optional[str] = ""
    company: Optional[str] = ""


class OriginalOverleafRequest(BaseModel):
    resume_data: dict
    job_title: Optional[str] = ""
    company: Optional[str] = ""


class GeneratePromptQueryRequest(BaseModel):
    suggestion: str


class ApplySuggestionRequest(BaseModel):
    suggestion: str
    user_input: Optional[str] = None


class UpdateMasterFromTailoredRequest(BaseModel):
    latex_code: str


# ─────────────────────────────────────────────────────────────────────────────
# Resume Routes
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

    try:
        raw_filename = os.path.basename(file.filename or "resume_upload")
        safe_filename = re.sub(r'[^A-Za-z0-9._-]', '_', raw_filename).lstrip('.')
        if not safe_filename:
            safe_filename = f"resume_upload_{uuid.uuid4().hex[:8]}"
        user_up_dir, user_out_dir = _get_user_storage_dirs(token or "guest")
        file_path = os.path.join(user_up_dir, safe_filename)

        total_written = 0
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_written += len(chunk)
                if total_written > MAX_RESUME_UPLOAD_BYTES:
                    buffer.close()
                    os.remove(file_path)
                    raise HTTPException(status_code=413, detail=f"Resume file exceeds {MAX_RESUME_UPLOAD_BYTES // (1024*1024)}MB upload limit.")
                buffer.write(chunk)

        structured_data = await asyncio.to_thread(parse_resume, file_path)
        data = structured_data.model_dump()
        path = file_path

        if not file_path.endswith(".tex"):
            canonical_tex_path = os.path.join(user_up_dir, f"{uuid.uuid4().hex}_master.tex")
            canonical_tex = generate_latex_from_json(data)
            with open(canonical_tex_path, "w", encoding="utf-8") as f:
                f.write(canonical_tex)
            path = canonical_tex_path

        # Baseline PDF Compilation
        try:
            cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
            if not os.path.exists(cls_source):
                cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
            if os.path.exists(cls_source):
                shutil.copy2(cls_source, os.path.join(user_up_dir, "resume.cls"))
                shutil.copy2(cls_source, os.path.join(user_out_dir, "resume.cls"))

            with open(path, "r", encoding="utf-8") as _f:
                canonical_tex_content = _f.read()

            if file_path.endswith(".tex"):
                await asyncio.to_thread(
                    subprocess.run,
                    ["tectonic", path, "--outdir", user_out_dir],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
            else:
                pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex_content, 1.0, 1.0, None)
                opt_scale = 1.0
                opt_ls = 1.0
                if pages > 1:
                    for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                        p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex_content, 1.0, ls, None)
                        if p == 1:
                            opt_ls = ls
                            pages = 1
                            break
                if pages > 1:
                    for scale in [0.85, 0.75, 0.65]:
                        p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex_content, scale, opt_ls, None)
                        if p == 1:
                            opt_scale = scale
                            break

                fixed_baseline_tex = apply_latex_hotfix(canonical_tex_content, opt_scale, opt_ls, None)
                with open(path, "w", encoding="utf-8") as _f:
                    _f.write(fixed_baseline_tex)

                await asyncio.to_thread(
                    subprocess.run,
                    ["tectonic", path, "--outdir", user_out_dir],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
        except Exception as baseline_err:
            print(f"[upload_resume] Baseline PDF compilation warning: {baseline_err}")

        evaluation = evaluate_master_resume(data)
        set_session_data(token, data, path)

        guest_file = _get_guest_state_file(token)
        try:
            with open(guest_file, "w") as f:
                json.dump({"data": data, "path": path, "evaluation": evaluation}, f, indent=2)
        except Exception as file_err:
            print(f"[upload_resume] Could not save guest state file {guest_file}: {file_err}")

        return {
            "message": "Resume uploaded and parsed successfully",
            "data": data,
            "evaluation": evaluation
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_session_resume")
async def get_session_resume(authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

    session_info = get_session_data(token)
    data = session_info.get("data", {})
    if not data or not data.get("education"):
        guest_file = _get_guest_state_file(token)
        if not os.path.exists(guest_file):
            guest_file = _get_guest_state_file("guest")
        if os.path.exists(guest_file):
            try:
                with open(guest_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    data = saved.get("data", {})
                    set_session_data(token or "guest", data, saved.get("path", ""))
            except Exception as e:
                print(f"[get_session_resume] Error reading state file: {e}")

    return {
        "status": "success",
        "data": data,
        "path": session_info.get("path", "")
    }


@router.get("/user/resume")
async def user_resume(authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    data = session.get("data")
    eval_res = evaluate_master_resume(data) if data else None
    return {"data": data, "path": session.get("path"), "evaluation": eval_res}


@router.post("/download_latex")
async def download_latex(request: LatexDownloadRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    try:
        tex_path, _ = _user_output_paths(token)
        fixed_code = apply_latex_hotfix(request.latex_code)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
        return FileResponse(tex_path, media_type="text/plain", filename="resume.tex")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download_application_pdf/{filepath:path}")
async def download_application_pdf(filepath: str):
    clean_rel = os.path.normpath(filepath).lstrip("/")
    pdf_path = os.path.abspath(os.path.join(OUTPUT_DIR, clean_rel))
    out_dir_abs = os.path.abspath(OUTPUT_DIR)

    if not pdf_path.startswith(out_dir_abs) or not os.path.exists(pdf_path):
        flat_path = os.path.join(OUTPUT_DIR, os.path.basename(filepath))
        if os.path.exists(flat_path):
            pdf_path = flat_path
        else:
            raise HTTPException(status_code=404, detail="PDF file not found")

    filename = os.path.basename(pdf_path)
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )


@router.post("/download_cover_letter")
async def download_cover_letter(request: CoverLetterDownloadRequest):
    return Response(
        content=request.cover_letter,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=cover_letter.txt"}
    )


@router.post("/compile_latex")
async def compile_latex(request: CompileLatexRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    try:
        tex_path, pdf_path = _user_output_paths(token)
        fixed_code = apply_latex_hotfix(request.latex_code)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)

        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
        if os.path.exists(cls_source):
            shutil.copy2(cls_source, os.path.join(OUTPUT_DIR, "resume.cls"))

        result = await asyncio.to_thread(
            subprocess.run,
            ["tectonic", tex_path, "--outdir", OUTPUT_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"LaTeX compilation failed: {result.stderr}")

        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=resume.pdf"}
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/open_in_overleaf")
async def open_in_overleaf(request: OverleafRequest):
    try:
        url = await asyncio.to_thread(
            upload_zip_to_tmpfiles,
            request.latex_code,
            request.candidate_name or "",
            request.job_title or "",
            request.company or ""
        )
        return {"url": url}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/open_original_in_overleaf")
async def open_original_in_overleaf(request: OriginalOverleafRequest):
    try:
        session = get_session_data(None)
        master_path = session.get("path") if session else None
        latex_code = _build_original_latex(request.resume_data, master_path)
        candidate_name = request.resume_data.get("name", "") or ""
        url = await asyncio.to_thread(
            upload_zip_to_tmpfiles,
            latex_code,
            candidate_name,
            request.job_title or "",
            request.company or ""
        )
        return {"url": url}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compile_master_pdf")
async def compile_master_pdf(request: OriginalOverleafRequest):
    try:
        session = get_session_data(None)
        master_path = session.get("path") if session else None
        latex_code = _build_original_latex(request.resume_data, master_path)
        candidate_name = request.resume_data.get("name", "Master")
        safe_name = _safe_key(candidate_name)
        user_out_dir = os.path.join(OUTPUT_DIR, safe_name)
        os.makedirs(user_out_dir, exist_ok=True)

        cls_src = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_src):
            cls_src = os.path.join(BASE_DIR, "assets", "resume.cls")
        if os.path.exists(cls_src):
            shutil.copy2(cls_src, os.path.join(user_out_dir, "resume.cls"))

        pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, latex_code, 1.0, 1.0, None)
        opt_scale = 1.0
        opt_ls = 1.0
        if pages > 1:
            for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, latex_code, 1.0, ls, None)
                if p == 1:
                    opt_ls = ls
                    pages = 1
                    break
        if pages > 1:
            for scale in [0.85, 0.75, 0.65]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, latex_code, scale, opt_ls, None)
                if p == 1:
                    opt_scale = scale
                    break

        final_latex = apply_latex_hotfix(latex_code, opt_scale, opt_ls, None)
        tex_path = os.path.join(user_out_dir, "master_resume.tex")
        pdf_path = os.path.join(user_out_dir, "master_resume.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(final_latex)

        comp_res = await asyncio.to_thread(
            subprocess.run,
            ["tectonic", tex_path, "--outdir", user_out_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if comp_res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Tectonic compilation failed: {comp_res.stderr}")

        download_url = f"/download_application_pdf/{safe_name}/master_resume.pdf"
        return {"status": "success", "pdf_url": download_url, "latex": final_latex}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/user/apply_suggestion")
async def apply_suggestion(request: ApplySuggestionRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    data = session.get("data")
    if not data:
        raise HTTPException(status_code=400, detail="No master resume uploaded.")

    from services.gemini_client import generate_content_with_fallback
    user_context = f"\nUser provided metric / context: {request.user_input}\n" if request.user_input else ""
    prompt = (
        "Update the master resume JSON by integrating this specific recommendation:\n"
        f"Recommendation: {request.suggestion}{user_context}\n\n"
        "CRITICAL RULE: Do NOT hallucinate metrics, financial numbers, or percentages. "
        "Use ONLY exact numbers provided by the user context above or refine the wording accurately.\n\n"
        f"Master Resume JSON:\n{json.dumps(data, indent=2)}\n\n"
        "Return ONLY the updated valid JSON object representing StructuredResume."
    )
    res_text = generate_content_with_fallback(prompt=prompt, system_instruction="Output ONLY raw JSON.")
    try:
        cleaned = res_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        updated_data = json.loads(cleaned)

        user_up_dir, user_out_dir = _get_user_storage_dirs(token or "guest")
        canonical_tex_path = os.path.join(user_up_dir, f"{uuid.uuid4().hex}_master.tex")
        canonical_tex = generate_latex_from_json(updated_data)
        with open(canonical_tex_path, "w", encoding="utf-8") as f:
            f.write(canonical_tex)

        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
        if os.path.exists(cls_source):
            shutil.copy2(cls_source, os.path.join(user_up_dir, "resume.cls"))
            shutil.copy2(cls_source, os.path.join(user_out_dir, "resume.cls"))

        after_pdf_filename = f"master_after_{uuid.uuid4().hex[:8]}.pdf"
        after_pdf_path = os.path.join(user_out_dir, after_pdf_filename)

        pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex, 1.0, 1.0, None)
        optimal_scale = 1.0
        optimal_linespread = 1.0
        if pages > 1:
            for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex, 1.0, ls, None)
                if p == 1:
                    pages = 1
                    optimal_linespread = ls
                    break

        if pages > 1:
            for scale in [0.85, 0.75, 0.65]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex, scale, optimal_linespread, None)
                if p == 1:
                    pages = 1
                    optimal_scale = scale
                    break

        final_fixed_tex = apply_latex_hotfix(canonical_tex, optimal_scale, optimal_linespread, None)
        with open(canonical_tex_path, "w", encoding="utf-8") as f:
            f.write(final_fixed_tex)

        await asyncio.to_thread(
            subprocess.run,
            ["tectonic", canonical_tex_path, "--outdir", user_out_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        default_after_pdf = os.path.join(user_out_dir, os.path.basename(canonical_tex_path).replace(".tex", ".pdf"))
        if os.path.exists(default_after_pdf):
            os.replace(default_after_pdf, after_pdf_path)

        after_pdf_url = f"/download_application_pdf/{_safe_key(token or 'guest')}/{after_pdf_filename}" if os.path.exists(after_pdf_path) else None

        set_session_data(token, updated_data, canonical_tex_path)
        guest_file = _get_guest_state_file(token)
        new_eval = evaluate_master_resume(updated_data)
        try:
            with open(guest_file, "w") as f:
                json.dump({"data": updated_data, "path": canonical_tex_path, "evaluation": new_eval}, f, indent=2)
        except Exception:
            pass

        return {
            "status": "success",
            "data": updated_data,
            "evaluation": new_eval,
            "latex": canonical_tex,
            "after_pdf_url": after_pdf_url
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to apply suggestion: {str(e)}")


@router.post("/user/update_master_from_tailored")
async def update_master_from_tailored(request: UpdateMasterFromTailoredRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    if not request.latex_code or not request.latex_code.strip():
        raise HTTPException(status_code=400, detail="Invalid LaTeX content.")

    try:
        user_up_dir, _ = _get_user_storage_dirs(token or "guest")
        temp_tex = os.path.join(user_up_dir, f"temp_promoted_{uuid.uuid4().hex[:8]}.tex")
        with open(temp_tex, "w", encoding="utf-8") as f:
            f.write(request.latex_code)

        structured = await asyncio.to_thread(parse_resume, temp_tex)
        updated_data = structured.model_dump()

        canonical_tex_path = os.path.join(user_up_dir, f"{uuid.uuid4().hex}_master.tex")
        with open(canonical_tex_path, "w", encoding="utf-8") as f:
            f.write(request.latex_code)

        set_session_data(token, updated_data, canonical_tex_path)
        guest_file = _get_guest_state_file(token)
        new_eval = evaluate_master_resume(updated_data)
        try:
            with open(guest_file, "w") as f:
                json.dump({"data": updated_data, "path": canonical_tex_path, "evaluation": new_eval}, f, indent=2)
        except Exception:
            pass

        return {"status": "success", "message": "Master resume updated from tailored version!", "data": updated_data, "evaluation": new_eval}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update master resume: {str(e)}")


@router.get("/render_html_resume")
async def render_html_resume_endpoint(authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    session_resume = session.get("data") or {}

    from services.html_resume_renderer import render_html_resume
    html_content = render_html_resume(session_resume)
    return HTMLResponse(content=html_content, status_code=200)


@router.get("/download_extension")
async def download_extension(
    request: Request,
    token: Optional[str] = None,
    key: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    import io
    import zipfile
    auth_token = key or token or (authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None)
    user = await async_get_user_by_token(auth_token) if auth_token else None

    sync_code = "GABY48"
    if user and user.get("sync_code"):
        sync_code = str(user["sync_code"]).strip().upper()
    elif auth_token and len(auth_token.strip()) == 6 and auth_token.strip().isalnum():
        sync_code = auth_token.strip().upper()

    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "www.job-finder.space")
    server_url = f"{proto}://{host}" if host else "https://www.job-finder.space"

    ext_dir = os.path.abspath(os.path.join(BASE_DIR, "../extension"))
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(ext_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["__pycache__", "node_modules"]]
            for file in files:
                if not file.startswith("."):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, ext_dir)
                    if file == "popup.js":
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        content = content.replace(
                            'const DEFAULT_API_BASE_URL = "https://www.job-finder.space";',
                            f'const DEFAULT_API_BASE_URL = "{server_url}";'
                        ).replace(
                            'const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";',
                            f'const DEFAULT_API_BASE_URL = "{server_url}";'
                        )
                        content = content.replace(
                            'const DEFAULT_SYNC_KEY = "";',
                            f'const DEFAULT_SYNC_KEY = "{sync_code}";'
                        ).replace(
                            'const DEFAULT_SYNC_KEY = "GABY48";',
                            f'const DEFAULT_SYNC_KEY = "{sync_code}";'
                        )
                        zipf.writestr(rel_path, content)
                    else:
                        zipf.write(full_path, rel_path)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="job_finder_extension.zip"'}
    )
