"""Explicit, offline quarantine of old failed diagnostic jobs only."""
import fcntl
import json
import time
import uuid
from pathlib import Path

DIAGNOSTICS = Path(__file__).resolve().parents[2] / 'runtime' / 'diagnostics'
ALLOWED_ROOTS = ('api-jobs', 'creation-page-jobs', 'regeneration-page-jobs')


def archive_failed_jobs(root_name, job_ids, days=7, apply=False, diagnostics=DIAGNOSTICS):
    if root_name not in ALLOWED_ROOTS or days < 1 or not job_ids:
        raise ValueError('请选择已知诊断目录、明确任务编号和至少1天的期限')
    root = diagnostics / root_name
    if diagnostics.is_symlink() or root.is_symlink() or not root.is_dir():
        raise ValueError('诊断目录不可用')
    ids = list(dict.fromkeys(job_ids))
    for job_id in ids:
        try:
            if str(uuid.UUID(job_id)) != job_id: raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('任务编号无效') from None
    result = []
    # The server takes the same exclusive lock: no cleanup while a server is active.
    lock_path = root / '.server.lock'
    if lock_path.is_symlink(): raise ValueError('诊断锁不可用')
    with lock_path.open('a+') as lock:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: raise ValueError('该诊断服务仍在运行，请先关闭对应窗口') from None
        for job_id in ids:
            folder = root / job_id
            manifest_path = folder / 'manifest.json'
            if folder.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
                result.append({'job_id': job_id, 'status': 'skipped', 'reason': '记录不可用'}); continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                # Never remove ready works or unfinished tasks, regardless of age.
                eligible = manifest.get('job_id') == job_id and manifest.get('status') == 'failed' and manifest_path.stat().st_mtime < time.time() - days * 86400
            except (OSError, ValueError, AttributeError):
                eligible = False
            if not eligible:
                result.append({'job_id': job_id, 'status': 'skipped', 'reason': '仅处理超过期限的失败任务'}); continue
            if apply:
                archive = diagnostics / 'archive'
                if archive.is_symlink(): raise ValueError('归档目录不可用')
                archive.mkdir(exist_ok=True)
                destination = archive / (root_name + '-' + job_id)
                if destination.exists():
                    result.append({'job_id': job_id, 'status': 'skipped', 'reason': '归档已存在'}); continue
                folder.rename(destination)
            result.append({'job_id': job_id, 'status': 'archived' if apply else 'would_archive'})
    return result
