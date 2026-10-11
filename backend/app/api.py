"""Task12 request validation, state and MP3/PDF responses. No product UI."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, field_validator
from typing import Optional

from app.jobs import JobError
from app.schemas.composition import ContractModel

router = APIRouter(prefix='/api')


class GenerateRequest(ContractModel):
    prompt: str = Field(min_length=1, max_length=1000)
    source_composition_id: Optional[str] = None
    request_id: Optional[str] = Field(default=None, pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

    @field_validator('prompt')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('请输入创作描述')
        return value.strip()


async def job_error_handler(request, error: JobError):
    return JSONResponse({'error': {'code': error.code, 'message': str(error)}}, status_code=error.status)


@router.post('/generate', status_code=202)
def generate(body: GenerateRequest, request: Request):
    job_id = request.app.state.jobs.submit(body.prompt, body.source_composition_id, body.request_id)
    return {'job_id': job_id, 'status': 'queued', 'status_url': '/api/jobs/' + job_id}


@router.get('/jobs/{job_id}')
def state(job_id: str, request: Request):
    return request.app.state.jobs.public_state(job_id)


@router.post('/jobs/{job_id}/cancel', status_code=202)
def cancel(job_id: str, request: Request):
    return request.app.state.jobs.cancel(job_id)


@router.get('/jobs/{job_id}/audio')
def audio(job_id: str, request: Request, download: bool = False):
    path = request.app.state.jobs.artifact(job_id, 'audio.mp3')
    return FileResponse(path, media_type='audio/mpeg', filename='music-' + job_id + '.mp3',
                        content_disposition_type='attachment' if download else 'inline')


@router.get('/jobs/{job_id}/pdf')
def pdf(job_id: str, request: Request, download: bool = True):
    path = request.app.state.jobs.artifact(job_id, 'score.pdf')
    return FileResponse(path, media_type='application/pdf', filename='music-' + job_id + '.pdf',
                        content_disposition_type='attachment' if download else 'inline')
