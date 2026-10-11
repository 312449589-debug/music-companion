"""Task12 live HTTP acceptance, optionally with an isolated ordinary-host server."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
DIAGNOSTICS = BACKEND.parent / 'runtime' / 'diagnostics'


@contextmanager
def local_server():
    # Only stop the child owned by this diagnostic; don't touch the user's main service.
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 8001))
        except OSError:
            raise ValueError('8001端口已被使用，请关闭之前的接口诊断窗口再测试') from None
    environment = dict(os.environ)
    environment['MUSIC_JOBS_ROOT'] = str(DIAGNOSTICS / 'api-jobs')
    environment['MUSIC_PRINT_BASE_URL'] = 'http://127.0.0.1:8001'
    with (DIAGNOSTICS / 'api-server.log').open('w') as log:
        child = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001'],
                                 cwd=BACKEND, env=environment, stdout=log, stderr=log)
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                for _ in range(30):
                    if child.poll() is not None:
                        raise ValueError('独立诊断服务启动失败，请查看api-server.log，可能8001端口已被使用')
                    try:
                        if client.get('http://127.0.0.1:8001/api/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.2)
                else:
                    raise ValueError('独立诊断服务未就绪')
            yield 'http://127.0.0.1:8001'
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def inspect_http(client, job_id, root):
    state = client.get('/api/jobs/' + job_id)
    assert state.status_code == 200 and state.json()['status'] == 'ready', '任务未ready'
    state = state.json()
    folder = root / job_id
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['composition_id'] == state['composition_id'], '作品编号不同'
    assert state['composition'] == json.loads((folder / 'artifacts/composition.json').read_text()), '主数据不一致'
    assert state['alphatex'] == (folder / 'artifacts/score.alphatex').read_text(), '谱面不一致'
    for endpoint, name, mime in [('audio', 'audio.mp3', 'audio/mpeg'), ('pdf', 'score.pdf', 'application/pdf')]:
        file = client.get('/api/jobs/' + job_id + '/' + endpoint + '?download=true')
        assert file.status_code == 200 and file.headers['content-type'] == mime, '下载响应失败'
        assert file.headers['content-disposition'].startswith('attachment;'), '下载文件名/类型失败'
        assert hashlib.sha256(file.content).hexdigest() == manifest['files'][name]['sha256'], 'HTTP文件内容不一致'
    ranged = client.get('/api/jobs/' + job_id + '/audio', headers={'Range': 'bytes=0-31'})
    assert ranged.status_code == 206 and len(ranged.content) == 32, '音频Range检查失败'
    print('ready作品、谱面、MP3/PDF下载与音频Range均通过：' + job_id, flush=True)
    return {'job_id': job_id, 'composition_id': state['composition_id'], 'status': 'ready', 'folder': str(folder)}


def run(base_url, root, existing=None):
    with httpx.Client(base_url=base_url, trust_env=False, timeout=10) as client:
        assert client.get('/api/health').status_code == 200
        assert client.post('/api/generate', json={'prompt': '  '}).status_code == 422
        assert client.get('/api/jobs/invalid').status_code == 404
        if existing:
            return [inspect_http(client, existing, root)]
        print('通过POST接口提交两首真实AI创作，计入已配置预算…', flush=True)
        ids = []
        for prompt in ['温暖安静，适合夜晚弹奏', '轻快明亮，简单和声加旋律']:
            response = client.post('/api/generate', json={'prompt': prompt})
            assert response.status_code == 202, '提交未被接收'
            job_id = response.json()['job_id']
            ids.append(job_id)
            print('已提交，任务编号：' + job_id, flush=True)
            value = client.get('/api/jobs/' + job_id).json()
            if value['status'] in ('queued', 'running'):
                assert client.get('/api/jobs/' + job_id + '/audio').status_code == 409
                assert client.get('/api/jobs/' + job_id + '/pdf').status_code == 409
        remaining, previous = set(ids), {}
        deadline = time.monotonic() + 600
        while remaining and time.monotonic() < deadline:
            assert client.get('/api/health').status_code == 200, '后台处理阻塞了网页服务'
            for job_id in list(remaining):
                state = client.get('/api/jobs/' + job_id)
                assert state.status_code == 200, '状态查询失败'
                value = state.json()
                stage = (value['status'], value['stage'])
                if previous.get(job_id) != stage:
                    print(job_id + '：' + '/'.join(stage), flush=True)
                    previous[job_id] = stage
                if value['status'] == 'failed':
                    raise ValueError('生成失败：' + job_id + '，' + json.dumps(value.get('error'), ensure_ascii=False))
                if value['status'] == 'ready':
                    remaining.remove(job_id)
            if remaining:
                time.sleep(1)
        if remaining:
            raise ValueError('诊断等待超时，不能把仍未完成的任务作为成功')
        reports = [inspect_http(client, job_id, root) for job_id in ids]
        assert reports[0]['composition_id'] != reports[1]['composition_id'], '两任务覆盖同一作品'
        return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-local-server', action='store_true')
    parser.add_argument('--existing', help='只核对8000服务的已有任务，不调用模型')
    args = parser.parse_args()
    try:
        if args.start_local_server:
            with local_server() as base_url:
                reports = run(base_url, DIAGNOSTICS / 'api-jobs')
        else:
            reports = run('http://127.0.0.1:8000', BACKEND.parent / 'runtime/jobs', args.existing)
        DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
        name = 'jobs-api-check.json' if not args.existing else 'jobs-api-existing-check.json'
        (DIAGNOSTICS / name).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        print('任务12真实异步接口验证通过。' if not args.existing else '已有成品接口验证通过；未调用模型。')
        return 0
    except (OSError, ValueError, AssertionError, httpx.HTTPError) as error:
        print('接口诊断未通过：' + str(error), flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
