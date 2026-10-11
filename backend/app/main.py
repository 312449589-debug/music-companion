from pathlib import Path
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.jobs import JobError, JobService
from app.api import router, job_error_handler


@asynccontextmanager
async def lifespan(app):
    jobs_root = os.environ.get('MUSIC_JOBS_ROOT')
    app.state.jobs = JobService(root=Path(jobs_root) if jobs_root else None,
                               base_url=os.environ.get('MUSIC_PRINT_BASE_URL', 'http://127.0.0.1:8000'))
    try:
        yield
    finally:
        await asyncio.to_thread(app.state.jobs.close)


app = FastAPI(title="Music Companion API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.add_exception_handler(JobError, job_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "music-companion-api"}


# Register API routes before the website so /api/health is never masked by HTML.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/diagnostics/tablature", include_in_schema=False)
@app.get("/diagnostics/print", include_in_schema=False)
def tablature_diagnostic():
    index = frontend_dist / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "请先构建前端诊断页面"}, status_code=503)
    return FileResponse(index)


@app.get("/diagnostics/audio-check.mp3", include_in_schema=False)
def audio_diagnostic():
    audio = frontend_dist.parents[1] / "runtime" / "diagnostics" / "composition-check.mp3"
    if not audio.exists():
        return JSONResponse({"detail": "请先运行MP3诊断生成固定样例"}, status_code=404)
    return FileResponse(audio, media_type="audio/mpeg")


if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="website")
