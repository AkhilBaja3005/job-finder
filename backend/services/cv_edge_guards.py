"""Phase 10: Edge-case guards (not-a-fit check, dedup key, pack lock, legacy flagging)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator


def detect_not_a_fit(
    *,
    candidate_text: str,
    jd_title: str,
    jd_text: str,
) -> Dict[str, Any]:
    """Flag when the JD is in an unrelated field with near-zero overlap."""
    cand_tokens = {t for t in re.findall(r"[a-z0-9]+", (candidate_text or "").lower()) if len(t) >= 3}
    jd_tokens = {t for t in re.findall(r"[a-z0-9]+", f"{jd_title}\n{jd_text}".lower()) if len(t) >= 3}
    stopwords = {"the", "and", "for", "with", "years", "required", "experience", "role", "work", "team"}
    cand_sig = cand_tokens - stopwords
    jd_sig = jd_tokens - stopwords
    overlap = cand_sig & jd_sig
    ratio = len(overlap) / max(1, len(jd_sig))
    not_a_fit = len(overlap) == 0 or ratio < 0.08
    return {
        "not_a_fit": not_a_fit,
        "overlap_count": len(overlap),
        "overlap_ratio": round(ratio, 3),
    }


def dedup_job_pack_key(company: str, title: str, url: str = "") -> str:
    """Canonical key so the same job across two sites maps to one pack."""
    c = re.sub(r"[^a-z0-9]+", " ", (company or "").lower()).strip()
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return hashlib.sha256(f"{c}::{t}".encode("utf-8")).hexdigest()[:16]


@contextmanager
def acquire_pack_lock(pack_folder: Path) -> Iterator[bool]:
    """Exclusive non-blocking file lock preventing concurrent tailoring of one pack."""
    lock_path = pack_folder / ".tailor.lock"
    acquired = False
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        acquired = True
    except FileExistsError:
        acquired = False
    try:
        yield acquired
    finally:
        if acquired:
            lock_path.unlink(missing_ok=True)


def classify_legacy_pack(pack_folder: Path) -> Dict[str, Any]:
    """Detect packs built before the new manifest/ledger schema."""
    manifest_path = pack_folder / "manifest.json"
    if not manifest_path.is_file():
        return {"is_legacy": True, "reason": "missing_manifest"}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {"is_legacy": True, "reason": "invalid_manifest"}
    if not data.get("prompt_version") and not data.get("tailor_model"):
        return {"is_legacy": True, "reason": "pre_v2_schema"}
    return {"is_legacy": False, "reason": ""}
