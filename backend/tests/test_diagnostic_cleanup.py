import fcntl
import json
import os
import time
import uuid
import pytest
from app.diagnostic_cleanup import archive_failed_jobs


def job(root, status, age_days=10):
    job_id = str(uuid.uuid4()); folder = root / job_id; folder.mkdir()
    p = folder / 'manifest.json'; p.write_text(json.dumps({'job_id': job_id, 'status': status}))
    (folder / 'file.mp3').write_bytes(b'preserved')
    old = time.time() - age_days * 86400; os.utime(p, (old, old))
    return job_id


def test_only_explicit_old_failed_jobs_archived_and_preview_is_read_only(tmp_path):
    root = tmp_path / 'api-jobs'; root.mkdir()
    old = job(root, 'failed'); omitted = job(root, 'failed')
    ready = job(root, 'ready'); running = job(root, 'running'); queued = job(root, 'queued'); recent = job(root, 'failed', 0)
    ids = [old, ready, running, queued, recent]
    preview = archive_failed_jobs('api-jobs', ids, diagnostics=tmp_path)
    assert preview[0]['status'] == 'would_archive' and (root / old).exists()
    results = archive_failed_jobs('api-jobs', ids, apply=True, diagnostics=tmp_path)
    assert results[0]['status'] == 'archived' and not (root / old).exists()
    assert (tmp_path / 'archive' / ('api-jobs-' + old) / 'file.mp3').read_bytes() == b'preserved'
    for preserved in [omitted, ready, running, queued, recent]: assert (root / preserved / 'file.mp3').read_bytes() == b'preserved'


def test_live_server_lock_blocks_cleanup(tmp_path):
    root = tmp_path / 'api-jobs'; root.mkdir(); old = job(root, 'failed')
    with (root / '.server.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='仍在运行'): archive_failed_jobs('api-jobs', [old], apply=True, diagnostics=tmp_path)
    assert (root / old).exists()


def test_invalid_roots_ids_and_symlinks_rejected(tmp_path):
    root = tmp_path / 'api-jobs'; root.mkdir(); old = job(root, 'failed')
    for name, ids, days in [('jobs', [old], 7), ('api-jobs', ['../other'], 7), ('api-jobs', [old], 0)]:
        with pytest.raises(ValueError): archive_failed_jobs(name, ids, days, diagnostics=tmp_path)
    linked = str(uuid.uuid4()); (root / linked).symlink_to(root / old, target_is_directory=True)
    result = archive_failed_jobs('api-jobs', [linked], apply=True, diagnostics=tmp_path)
    assert result[0]['status'] == 'skipped' and (root / old).exists()
