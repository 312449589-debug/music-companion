"""Task15 isolated acceptance. Reuse verified real A, inject one failure, then generate real B."""
import asyncio
import hashlib
import json
import shutil
import socket
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from app.main import app, frontend_dist
from app.jobs import JobService
from app.music.pipeline import PipelineError, generate_work, write_json

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / 'runtime' / 'diagnostics' / 'regeneration-page-jobs'
first_regeneration = True
seed_id = None


def acceptance_runner(prompt, **kwargs):
    global first_regeneration
    if kwargs.get('source_piece') is not None and first_regeneration:
        first_regeneration = False
        path = kwargs['jobs_root'] / kwargs['job_id'] / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest.update(status='running', stage='model');write_json(path, manifest)
        time.sleep(3)
        manifest.update(status='failed', files={}, error={'stage': 'model', 'code': 'diagnostic_model_failure',
                                                         'message': '新作品生成失败，请保留上次作品并重试。'})
        write_json(path, manifest)
        raise PipelineError(kwargs['job_id'], 'model', 'diagnostic_model_failure', '诊断：新作品失败')
    return generate_work(prompt, **kwargs)


def prepare_source():
    global seed_id
    report = json.loads((ROOT / 'runtime/diagnostics/creation-page-check.json').read_text())
    seed_id = report['job_id']
    source = ROOT / 'runtime/diagnostics/creation-page-jobs' / seed_id
    manifest = json.loads((source / 'manifest.json').read_text())
    assert manifest['status'] == 'ready' and manifest['composition_id'] == report['composition_id']
    for item in manifest['files'].values():
        file = source / item['path']
        assert file.stat().st_size == item['bytes'] and hashlib.sha256(file.read_bytes()).hexdigest() == item['sha256']
    JOBS.mkdir(parents=True, exist_ok=True)
    destination = JOBS / seed_id
    if not destination.exists():
        shutil.copytree(source, destination)
    else:
        assert (destination / 'manifest.json').read_bytes() == (source / 'manifest.json').read_bytes(), '原作品副本已改变'


@asynccontextmanager
async def acceptance_lifespan(application):
    prepare_source()
    application.state.jobs = JobService(root=JOBS, runner=acceptance_runner, base_url='http://127.0.0.1:8003')
    try:
        yield
    finally:
        await asyncio.to_thread(application.state.jobs.close)


def source_state(request: Request):
    return request.app.state.jobs.public_state(seed_id)


def page():
    return FileResponse(frontend_dist / 'index.html')


app.router.lifespan_context = acceptance_lifespan
app.router.routes.insert(0, APIRoute('/diagnostics/regeneration-source', source_state, methods=['GET']))
app.router.routes.insert(0, APIRoute('/diagnostics/regeneration', page, methods=['GET']))

if __name__ == '__main__':
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', 8003))
        except OSError: raise SystemExit('8003端口已被使用，请关闭旧整段诊断窗口。')
    print('打开 http://127.0.0.1:8003/diagnostics/regeneration 。页面加载任务14的原真实作品，不使用模板。', flush=True)
    print('首次重新生成故意失败且不收费；重试使用真实AI和既定预算。请保持窗口打开。', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8003, access_log=False)
