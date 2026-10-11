"""Task14 isolated page acceptance server; first request fails, later requests use real AI.
Only this diagnostic replaces the runner. Production has no fault switch.
"""
import asyncio
import json
import socket
import time
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from app.main import app
from app.jobs import JobService
from app.music.pipeline import PipelineError, generate_work, write_json

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / 'runtime' / 'diagnostics' / 'creation-page-jobs'
first_request = True


def acceptance_runner(prompt, **kwargs):
    global first_request
    if first_request:
        first_request = False
        path = kwargs['jobs_root'] / kwargs['job_id'] / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest.update(status='running', stage='model')
        write_json(path, manifest)
        time.sleep(3)  # Give the page time to verify the disabled submit state.
        manifest.update(status='failed', files={}, error={'stage': 'model', 'code': 'diagnostic_model_failure',
                                                         'message': '模型暂时不可用，请保留描述后重试。'})
        write_json(path, manifest)
        raise PipelineError(kwargs['job_id'], 'model', 'diagnostic_model_failure', '诊断：模型失败')
    return generate_work(prompt, **kwargs)


@asynccontextmanager
async def acceptance_lifespan(application):
    application.state.jobs = JobService(root=JOBS, runner=acceptance_runner, base_url='http://127.0.0.1:8002')
    try:
        yield
    finally:
        await asyncio.to_thread(application.state.jobs.close)


app.router.lifespan_context = acceptance_lifespan

if __name__ == '__main__':
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 8002))
        except OSError:
            raise SystemExit('8002端口已被使用，请先关闭旧首页诊断窗口。')
    print('打开 http://127.0.0.1:8002/ 验证首页。', flush=True)
    print('首次提交只验证模型失败，不收费；点击重试后使用真实AI及已配置预算。', flush=True)
    print('成功应显示作品标题、BPM、调性、完整六线谱及两个可用下载链接。', flush=True)
    print('验证完毕关闭本窗口，只停止本诊断服务，不影响主服务。', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8002)
