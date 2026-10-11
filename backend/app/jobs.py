"""Task12: bounded single-process queue, persisted states and trusted artifacts."""
import hashlib
import fcntl
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.music.pipeline import PipelineError, generate_work, write_json
from app.schemas.composition import Composition
from app.providers.control import GenerationControl, JOB_TIMEOUT_SECONDS
from app.providers.errors import ProviderError

ROOT = Path(__file__).resolve().parents[2]


class JobError(ValueError):
    def __init__(self, status, code, message):
        self.status, self.code = status, code
        super().__init__(message)


class JobService:
    def __init__(self, root=None, runner=generate_work, base_url='http://127.0.0.1:8000', capacity=4):
        self.root = root or ROOT / 'runtime' / 'jobs'
        self.runner, self.base_url = runner, base_url
        self.capacity = capacity
        self.slots = threading.BoundedSemaphore(capacity)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='music-job')
        self.closed = False
        self.lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_lock = (self.root / '.server.lock').open('a+')
        try:
            fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.process_lock.close()
            self.executor.shutdown()
            raise RuntimeError('该任务目录已有服务运行，请使用现有服务或独立诊断目录') from None
        # Local demo supports one server process; interrupted requests aren't silently resumed.
        for path in self.root.glob('*/manifest.json'):
            try:
                manifest = self.read(path.parent.name)
                if manifest['status'] in ('queued', 'running'):
                    self.fail(manifest['job_id'], 'restart_interrupted', '服务已重启，未完成任务已停止，请重新提交')
            except JobError:
                continue

    def read(self, job_id):
        try:
            if str(uuid.UUID(job_id)) != job_id:
                raise ValueError('noncanonical')
        except (ValueError, TypeError, AttributeError):
            raise JobError(404, 'job_not_found', '找不到该生成任务') from None
        path = self.root / job_id / 'manifest.json'
        if not path.is_file():
            raise JobError(404, 'job_not_found', '找不到该生成任务')
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if manifest['job_id'] != job_id or manifest['status'] not in ('queued', 'running', 'ready', 'failed'):
                raise ValueError('bad manifest')
            return manifest
        except (OSError, ValueError, KeyError, TypeError):
            raise JobError(500, 'job_record_invalid', '任务记录不可读取，未交付文件') from None

    def fail(self, job_id, code, message):
        manifest = self.read(job_id)
        manifest.update(status='failed', files={}, error={'stage': manifest.get('stage', 'worker'),
                                                        'code': code, 'message': message})
        write_json(self.root / job_id / 'manifest.json', manifest)

    def source(self, composition_id):
        try:
            if str(uuid.UUID(composition_id)) != composition_id:
                raise ValueError('noncanonical')
        except (ValueError, TypeError, AttributeError):
            raise JobError(404, 'source_not_found', '找不到原作品，请先完成首次生成') from None
        matches = []
        for path in self.root.glob('*/manifest.json'):
            try:
                manifest = self.read(path.parent.name)
            except JobError:
                continue
            if manifest.get('composition_id') == composition_id and manifest['status'] == 'ready':
                state = self.public_state(path.parent.name)
                matches.append(Composition.model_validate_json(json.dumps(state['composition'])))
        if len(matches) != 1 or matches[0].origin != 'ai':
            raise JobError(404, 'source_not_found', '找不到唯一且完整的原AI作品，请先完成首次生成')
        return matches[0]

    def submit(self, prompt, source_composition_id=None, request_id=None):
        if request_id is not None:
            try:
                if str(uuid.UUID(request_id)) != request_id: raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise JobError(422, 'request_invalid', '提交编号无效') from None
        identity = hashlib.sha256(json.dumps([prompt, source_composition_id], ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            # A retry must resolve the original job before source lookup or queue admission.
            if request_id and (self.root / request_id / 'manifest.json').exists():
                existing = self.read(request_id)
                if existing.get('error', {}).get('code') == 'generation_cancelled' and not existing.get('request_hash'):
                    return request_id
                if existing.get('request_hash') != identity:
                    raise JobError(409, 'request_conflict', '同一次提交不能更改描述，请先恢复原任务')
                return request_id
            source_piece = self.source(source_composition_id) if source_composition_id is not None else None
            if self.closed:
                raise JobError(503, 'service_stopping', '服务正在停止，请稍后重试')
            if not self.slots.acquire(blocking=False):
                raise JobError(429, 'queue_full', '当前生成队列已满，请稍后再提交')
            job_id = request_id or str(uuid.uuid4())
            folder = self.root / job_id
            try:
                folder.mkdir(exist_ok=False)
                created = time.time()
                write_json(folder / 'manifest.json', {'job_id': job_id, 'status': 'queued', 'stage': 'queued',
                                                     'files': {}, 'attempts': [], 'request_hash': identity,
                                                     'created_at': created, 'deadline_at': created + JOB_TIMEOUT_SECONDS,
                                                     'source_composition_id': source_composition_id})
                self.executor.submit(self.run, job_id, prompt, source_piece)
            except Exception:
                self.slots.release()
                raise
            return job_id

    def control(self, job_id):
        manifest = self.read(job_id)
        return GenerationControl(self.root / job_id, manifest.get('deadline_at', time.time() + JOB_TIMEOUT_SECONDS))

    def cancel(self, job_id):
        # A cancel arriving before a lost POST response creates a tombstone,
        # so a delayed/recovered submission with the same ID can never run.
        with self.lock:
            try:
                control = self.control(job_id)
            except JobError as error:
                if error.status != 404: raise
                try:
                    if str(uuid.UUID(job_id)) != job_id: raise ValueError()
                except (ValueError, TypeError, AttributeError):
                    raise JobError(404, 'job_not_found', '找不到该生成任务') from None
                folder = self.root / job_id
                folder.mkdir(exist_ok=False)
                write_json(folder / 'manifest.json', {'job_id':job_id, 'status':'failed', 'stage':'queued',
                    'files':{}, 'attempts':[], 'error':{'code':'generation_cancelled', 'message':'已取消提交，本次未开始模型生成。'}})
                return {'job_id':job_id, 'cancellation_requested':True}
            requested = control.cancel()
            return {'job_id':job_id, 'cancellation_requested':requested}

    def run(self, job_id, prompt, source_piece=None):
        try:
            control = self.control(job_id)
            control.checkpoint()
            options = {'source_piece': source_piece} if source_piece is not None else {}
            if self.runner is generate_work:
                options['control'] = control
            self.runner(prompt, jobs_root=self.root, base_url=self.base_url, job_id=job_id, **options)
            if self.read(job_id)['status'] not in ('ready', 'failed'):
                self.fail(job_id, 'incomplete_result', '生成流程未完成全部产物，未交付文件')
        except ProviderError as error:
            self.fail(job_id, error.code, str(error))
        except PipelineError:
            # The pipeline already persisted a safe failed state and removed partial files.
            pass
        except Exception:
            self.fail(job_id, 'worker_failed', '后台生成失败，未交付半成品，请重新提交')
        finally:
            self.slots.release()

    def artifact(self, job_id, name):
        manifest = self.read(job_id)
        if manifest['status'] != 'ready':
            raise JobError(409, 'work_not_ready', '作品尚未完整生成，暂时不能获取文件')
        if name not in ('audio.mp3', 'score.pdf', 'composition.json', 'score.alphatex'):
            raise JobError(404, 'file_not_found', '找不到该文件')
        try:
            item = manifest['files'][name]
            if item['path'] != 'artifacts/' + name:
                raise ValueError('untrusted path')
            base = (self.root / job_id / 'artifacts').resolve()
            if base != self.root.resolve() / job_id / 'artifacts':
                raise ValueError('symlink directory')
            path = base / name
            if path.is_symlink() or path.resolve().parent != base or not path.is_file():
                raise ValueError('invalid file')
            if path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('modified file')
            return path
        except (OSError, KeyError, TypeError, ValueError):
            raise JobError(409, 'file_unavailable', '作品文件缺失或检查失败，请重新生成') from None

    def public_state(self, job_id):
        manifest = self.read(job_id)
        result = {'job_id': job_id, 'status': manifest['status'], 'stage': manifest.get('stage', ''),
                  'progress': manifest.get('progress', ''),
                  'cancellation_requested': (self.root / job_id / '.cancel').exists(),
                  'deadline_at': manifest.get('deadline_at')}
        if manifest['status'] == 'queued' and result['cancellation_requested']:
            result.update(status='failed', error={'code':'generation_cancelled', 'message':'已取消排队，未开始模型生成。'})
        if manifest['status'] == 'queued' and manifest.get('deadline_at', float('inf')) <= time.time() and not result['cancellation_requested']:
            result.update(status='failed', error={'code':'generation_timeout', 'message':'排队等待超过10分钟，已停止该任务，请稍后重试。'})
        if manifest['status'] == 'failed':
            result['error'] = manifest.get('error', {'code': 'generation_failed', 'message': '生成失败'})
        if manifest['status'] == 'ready':
            try:
                piece = Composition.model_validate_json(self.artifact(job_id, 'composition.json').read_text(encoding='utf-8'))
                if piece.composition_id != manifest['composition_id']:
                    raise ValueError('identity')
                # Validate both downloadable files before publishing a ready result.
                self.artifact(job_id, 'audio.mp3')
                self.artifact(job_id, 'score.pdf')
                alphatex = self.artifact(job_id, 'score.alphatex').read_text(encoding='utf-8')
            except (ValueError, KeyError, OSError):
                raise JobError(409, 'work_unavailable', '作品内容不可读取，未交付不一致的结果') from None
            result.update(composition_id=piece.composition_id, composition=piece.model_dump(mode='json'),
                          alphatex=alphatex, audio_seconds=manifest['audio']['mp3_seconds'],
                          audio_url='/api/jobs/' + job_id + '/audio', pdf_url='/api/jobs/' + job_id + '/pdf')
        return result

    def close(self):
        with self.lock:
            self.closed = True
        # Give active finite pipeline calls time to persist a terminal state on normal shutdown.
        self.executor.shutdown(wait=True)
        fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_UN)
        self.process_lock.close()
