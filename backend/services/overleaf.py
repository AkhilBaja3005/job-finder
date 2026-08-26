import os
import io
import re
import base64
import zipfile
import urllib.parse
from services.session_store import BASE_DIR, UPLOAD_DIR
from utils.latex_utils import apply_latex_hotfix


def _sanitize_filename_part(part: str) -> str:
    """Sanitize string components for safe inclusion in project titles."""
    if not part:
        return ""
    cleaned = re.sub(r'[\r\n\t]+', ' ', str(part)).strip()
    cleaned = re.sub(r'[\\/:*?"<>|]+', '', cleaned)
    return cleaned.strip()


def upload_zip_to_tmpfiles(latex_code: str, candidate_name: str = "", job_title: str = "", company: str = "") -> str:
    """Pack LaTeX project with resume.cls and latexmkrc, generating an Overleaf direct import URL."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        fixed_code = apply_latex_hotfix(latex_code)
        zip_file.writestr("main.tex", fixed_code)

        latexmkrc_content = '$pdf_mode = 5;\n$postscript_mode = $dvi_mode = 0;\n$xelatex = "xelatex -synctex=1 -interaction=nonstopmode %O %S";\n'
        zip_file.writestr("latexmkrc", latexmkrc_content)

        cls_path = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_path):
            cls_path = os.path.join(BASE_DIR, "assets", "resume.cls")

        if os.path.exists(cls_path):
            with open(cls_path, "r", encoding="utf-8") as f:
                cls_content = f.read()
            zip_file.writestr("resume.cls", cls_content)

    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()

    parts = [_sanitize_filename_part(candidate_name), _sanitize_filename_part(job_title), _sanitize_filename_part(company)]
    parts = [p for p in parts if p]
    project_name = " - ".join(parts) + " Resume" if parts else "Resume"

    base64_zip = base64.b64encode(zip_data).decode('utf-8')
    data_uri = f"data:application/zip;base64,{base64_zip}"
    encoded_name = urllib.parse.quote(project_name)
    return f"https://www.overleaf.com/docs?snip_uri={urllib.parse.quote(data_uri)}&snip_name={encoded_name}"
