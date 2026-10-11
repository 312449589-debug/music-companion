"""Task12 isolated queue/API tests; real artifacts are separately checked live."""
import hashlib
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router, job_error_handler
from app.jobs import JobError, JobService
from app.music.pipeline import write_json


def ready(root, job_id):
    folder = root / job_id
    folder.mkdir(exist_ok=True)
    artifacts = folder / 'artifacts'
    artifacts.mkdir()
    piece = json.loads((Path(__file__).parents[1] / 'fixtures/diagnostic-fingerstyle.json').read_text())
    piece['composition_id'] = str(uuid.uuid4())
    data = {'composition.json': json.dumps(piece).encode(), 'score.alphatex': b'test-only-score',
            'audio.mp3': b'test-only-audio', 'score.pdf': b'test-only-pdf'}
    files = {}
    for name, content in data.items():
        (artifacts / name).write_bytes(content)
        files[name] = {'path': 'artifacts/' + name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    write_json(folder / 'manifest.json', {'job_id': job_id, 'status': 'ready', 'stage': 'complete',
                                        'composition_id': piece['composition_id'], 'files': files,
                                        'audio': {'mp3_seconds': 8.6}})


@contextmanager
def api(service):
    app = FastAPI()
    app.state.jobs = service
    app.include_router(router)
    app.add_exception_handler(JobError, job_error_handler)
    @app.get('/api/health')
    def health():
        return {'status': 'ok'}
    try:
        with TestClient(app) as client:
            yield client
    finally:
        service.close()


def wait_final(client, job_id):
    for _ in range(100):
        value = client.get('/api/jobs/' + job_id).json()
        if value['status'] in ('ready', 'failed'):
            return value
        time.sleep(.01)
    raise AssertionError('test worker did not finish')


def test_async_queue_states_limits_and_independent_results(tmp_path):
    gate, started = threading.Event(), threading.Event()
    def runner(prompt, *, jobs_root, job_id, base_url):
        manifest = json.loads((jobs_root / job_id / 'manifest.json').read_text())
        manifest.update(status='running', stage='test_wait')
        write_json(jobs_root / job_id / 'manifest.json', manifest)
        started.set()
        assert gate.wait(5)
        ready(jobs_root, job_id)
    service = JobService(tmp_path, runner=runner, capacity=2)
    with api(service) as client:
        try:
            first = client.post('/api/generate', json={'prompt': '描述A'})
            assert first.status_code == 202 and first.json()['status'] == 'queued'
            one = first.json()['job_id']
            assert started.wait(2)
            assert client.get('/api/jobs/' + one).json()['status'] == 'running'
            assert client.get('/api/jobs/' + one + '/audio').status_code == 409
            second = client.post('/api/generate', json={'prompt': '描述B'})
            two = second.json()['job_id']
            assert client.get('/api/jobs/' + two).json()['status'] == 'queued'
            assert client.post('/api/generate', json={'prompt': '描述C'}).status_code == 429
            assert client.get('/api/health').json()['status'] == 'ok'
        finally:
            gate.set()
        a, b = wait_final(client, one), wait_final(client, two)
        assert a['status'] == b['status'] == 'ready'
        assert a['composition_id'] != b['composition_id'] and one != two
        assert a['audio_url'] != b['audio_url']
        assert client.post('/api/generate', json={'prompt': '描述C'}).status_code == 202


def test_failed_background_job_does_not_serve_files_or_echo_raw_error(tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError('secret diagnostic body must not reach client')
    with api(JobService(tmp_path, runner=fail)) as client:
        job_id = client.post('/api/generate', json={'prompt': '描述'}).json()['job_id']
        state = wait_final(client, job_id)
        assert state['status'] == 'failed' and state['error']['code'] == 'worker_failed'
        assert 'secret' not in json.dumps(state)
        assert client.get('/api/jobs/' + job_id + '/pdf').status_code == 409


@pytest.mark.parametrize('body', [{'prompt': ''}, {'prompt': '  '}, {'prompt': 123},
                                  {'prompt': 'a' * 1001}, {'prompt': '描述', 'extra': 1}])
def test_bad_input_does_not_start_generation(tmp_path, body):
    calls = []
    with api(JobService(tmp_path, runner=lambda *a, **k: calls.append(1))) as client:
        assert client.post('/api/generate', json=body).status_code == 422
    assert not calls and not list(tmp_path.glob('*/manifest.json'))


def test_file_headers_download_and_byte_ranges(tmp_path):
    job_id = str(uuid.uuid4())
    ready(tmp_path, job_id)
    with api(JobService(tmp_path)) as client:
        audio = client.get('/api/jobs/' + job_id + '/audio')
        assert audio.status_code == 200 and audio.headers['content-type'] == 'audio/mpeg'
        assert audio.headers['content-disposition'].startswith('inline;')
        assert client.get('/api/jobs/' + job_id + '/audio?download=true').headers['content-disposition'].startswith('attachment;')
        partial = client.get('/api/jobs/' + job_id + '/audio', headers={'Range': 'bytes=0-3'})
        assert partial.status_code == 206 and partial.content == b'test'
        pdf = client.get('/api/jobs/' + job_id + '/pdf')
        assert pdf.headers['content-type'] == 'application/pdf' and pdf.headers['content-disposition'].startswith('attachment;')
        assert client.get('/api/jobs/not-a-uuid').status_code == 404
        assert client.get('/api/jobs/' + str(uuid.uuid4())).status_code == 404


def test_restart_marks_only_unfinished_jobs_failed(tmp_path):
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for job_id, status in zip(ids[:2], ['queued', 'running']):
        (tmp_path / job_id).mkdir()
        write_json(tmp_path / job_id / 'manifest.json', {'job_id': job_id, 'status': status, 'files': {}, 'stage': 'model'})
    ready(tmp_path, ids[2])
    with api(JobService(tmp_path)) as client:
        for job_id in ids[:2]:
            result = client.get('/api/jobs/' + job_id).json()
            assert result['status'] == 'failed' and result['error']['code'] == 'restart_interrupted'
        assert client.get('/api/jobs/' + ids[2]).json()['status'] == 'ready'


@pytest.mark.parametrize('mutation', ['path', 'bytes', 'symlink'])
def test_untrusted_or_changed_artifact_never_served(tmp_path, mutation):
    job_id = str(uuid.uuid4())
    ready(tmp_path, job_id)
    path = tmp_path / job_id / 'artifacts/audio.mp3'
    if mutation == 'path':
        manifest = json.loads((tmp_path / job_id / 'manifest.json').read_text())
        manifest['files']['audio.mp3']['path'] = '../../somewhere'
        write_json(tmp_path / job_id / 'manifest.json', manifest)
    elif mutation == 'bytes':
        path.write_bytes(b'corrupt')
    else:
        path.unlink()
        target = tmp_path / 'outside';target.write_bytes(b'test-only-audio')
        path.symlink_to(target)
    with api(JobService(tmp_path)) as client:
        assert client.get('/api/jobs/' + job_id + '/audio').status_code == 409


def test_second_server_cannot_invalidate_first_servers_active_jobs(tmp_path):
    service = JobService(tmp_path)
    try:
        with pytest.raises(RuntimeError, match='已有服务运行'):
            JobService(tmp_path)
    finally:
        service.close()
    restarted = JobService(tmp_path)
    restarted.close()


def test_regeneration_server_loads_source_and_client_cannot_override_tempo(tmp_path):
    old_id = str(uuid.uuid4())
    ready(tmp_path, old_id)
    piece_path = tmp_path / old_id / 'artifacts/composition.json'
    piece = json.loads(piece_path.read_text());piece['origin'] = 'ai';piece_path.write_text(json.dumps(piece))
    manifest_path = tmp_path / old_id / 'manifest.json'
    m = json.loads(manifest_path.read_text());m['files']['composition.json'].update(bytes=piece_path.stat().st_size, sha256=hashlib.sha256(piece_path.read_bytes()).hexdigest());write_json(manifest_path, m)
    old_bytes = manifest_path.read_bytes()
    seen = []
    def runner(prompt, *, jobs_root, job_id, base_url, source_piece):
        seen.append(source_piece)
        ready(jobs_root, job_id)
    with api(JobService(tmp_path, runner=runner)) as client:
        body = {'prompt': '新描述', 'source_composition_id': piece['composition_id']}
        assert client.post('/api/generate', json={**body, 'tempo_bpm': 999}).status_code == 422
        result = client.post('/api/generate', json=body)
        assert result.status_code == 202
        assert wait_final(client, result.json()['job_id'])['status'] == 'ready'
        assert seen[0].tempo_bpm == piece['tempo_bpm'] and seen[0].key_signature == piece['key_signature']
        assert manifest_path.read_bytes() == old_bytes
        assert client.get('/api/jobs/' + old_id + '/audio').status_code == 200


@pytest.mark.parametrize('source', ['not-a-uuid', str(uuid.uuid4())])
def test_regeneration_missing_source_never_calls_model(tmp_path, source):
    calls = []
    with api(JobService(tmp_path, runner=lambda *a, **k: calls.append(1))) as client:
        result = client.post('/api/generate', json={'prompt': '新描述', 'source_composition_id': source})
        assert result.status_code == 404
    assert not calls and not list(tmp_path.glob('*/manifest.json'))
