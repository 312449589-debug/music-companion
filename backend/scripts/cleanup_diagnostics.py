"""Preview by default; --apply moves explicitly selected failed jobs to archive."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.diagnostic_cleanup import ALLOWED_ROOTS, archive_failed_jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', choices=ALLOWED_ROOTS, required=True)
    parser.add_argument('--job', action='append', required=True)
    parser.add_argument('--older-than-days', type=int, default=7)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(archive_failed_jobs(args.root, args.job, args.older_than_days, args.apply), ensure_ascii=False, indent=2))
        return 0
    except ValueError as error:
        print(str(error)); return 1
    except OSError:
        print('文件操作未完成，请检查诊断目录权限；没有永久删除文件。'); return 1


if __name__ == '__main__':
    raise SystemExit(main())
