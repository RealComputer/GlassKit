from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", Path(__file__).with_name("uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_MODE_TO_EXT = {
    "video": ".mp4",
    "audio": ".m4a",
}
_ALLOWED_EXTENSIONS = frozenset(_ALLOWED_MODE_TO_EXT.values())
_CHUNK_SIZE = 1024 * 1024

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload")
async def upload_segment(
    file: UploadFile = File(...),
    mode: str = Form(...),
    start_unix: int = Form(...),
    end_unix: int = Form(...),
) -> dict[str, str]:
    normalized_mode = mode.strip().lower()
    default_ext = _ALLOWED_MODE_TO_EXT.get(normalized_mode)
    if default_ext is None:
        raise HTTPException(status_code=400, detail="mode must be 'video' or 'audio'")

    if end_unix <= start_unix:
        raise HTTPException(
            status_code=400, detail="end_unix must be greater than start_unix"
        )

    incoming_ext = Path(file.filename or "").suffix.lower()
    ext = incoming_ext if incoming_ext in _ALLOWED_EXTENSIONS else default_ext

    target = UPLOAD_DIR / f"{start_unix}-{end_unix}{ext}"
    temp_target = target.with_suffix(f"{target.suffix}.part")

    try:
        with temp_target.open("wb") as output:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
        temp_target.replace(target)
    finally:
        await file.close()

    return {
        "status": "ok",
        "filename": target.name,
    }
