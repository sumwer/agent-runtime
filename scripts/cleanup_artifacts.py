#!/usr/bin/env python3
"""清理 artifacts/<任务ID> 下超过保留期的产物。

只删文件；数据库行默认保留，加 --prune-db 会一并删除已终止的旧任务
（analyses 及 analysis_events）。

    .venv-runtime/bin/python scripts/cleanup_artifacts.py --days 14
    .venv-runtime/bin/python scripts/cleanup_artifacts.py --days 14 --prune-db
    .venv-runtime/bin/python scripts/cleanup_artifacts.py --days 14 --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402

TERMINAL = ('succeeded', 'failed')


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--prune-db', action='store_true', help='also delete terminal analyses rows')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.days < 1:
        parser.error('--days must be >= 1')
    root = Path(settings.ARTIFACTS_DIR).resolve()
    cutoff = time.time() - args.days * 86400
    if not root.is_dir():
        print(f'nothing to do: {root} does not exist')
        return 0
    freed = removed = 0
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime >= cutoff:
            continue
        freed += _size(child)
        removed += 1
        print(f'{"would remove" if args.dry_run else "remove"} {child.name}')
        if not args.dry_run:
            shutil.rmtree(child, ignore_errors=True)
    if args.prune_db:
        from app.db import get_engine

        where = ('status = ANY(:terminal) AND finished_at IS NOT NULL AND '
                 'finished_at < NOW() - make_interval(days => :days)')
        params = {'terminal': list(TERMINAL), 'days': args.days}
        engine = get_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            # analysis_events 的外键没有级联，先删事件再删任务。
            conn.execute(text(f'DELETE FROM analysis_events WHERE analysis_id IN '
                              f'(SELECT id FROM analyses WHERE {where})'), params)
            result = conn.execute(text(f'DELETE FROM analyses WHERE {where}'), params)
            print(f'{"would delete" if args.dry_run else "deleted"} {result.rowcount} analyses rows')
            conn.rollback() if args.dry_run else conn.commit()
    print(f'{removed} task dirs, {freed / 1e6:.1f} MB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
