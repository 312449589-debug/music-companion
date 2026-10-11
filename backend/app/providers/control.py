"""Cooperative cancellation/deadline; serialize cancellation against publication."""
import fcntl
import json
import time
from contextlib import contextmanager

from .errors import ProviderError

JOB_TIMEOUT_SECONDS = 600


class GenerationControl:
    def __init__(self, folder, deadline):
        self.folder, self.deadline = folder, deadline

    def checkpoint(self):
        if (self.folder / '.cancel').exists():
            raise ProviderError('generation_cancelled', '已取消生成，未交付新作品；已发生的模型费用仍会计入预算。')
        if time.time() >= self.deadline:
            raise ProviderError('generation_timeout', '生成等待超过10分钟，已停止后续步骤；请简化描述后重试。')

    @contextmanager
    def publication(self):
        with (self.folder / '.control.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self.checkpoint()
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def cancel(self):
        with (self.folder / '.control.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                state = json.loads((self.folder / 'manifest.json').read_text())
                if state['status'] in ('ready', 'failed'):
                    return False
                (self.folder / '.cancel').touch()
                return True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
