"""Consistent SQLite backup; destination must be a new private file."""
import argparse
import os
from pathlib import Path
import sqlite3


def backup(source, destination):
    source = Path(source).resolve()
    if not source.is_file(): raise ValueError('Source database does not exist.')
    destination = Path(destination)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        try:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity check failed.')
            finally: dst.close()
        finally: src.close()
    except Exception:
        destination.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', help='New private backup file outside the public directory')
    parser.add_argument('--source', default=str(Path(os.environ.get('ACADEMY_DATA_DIR', '.academy-data')) / 'academy.sqlite3'))
    args = parser.parse_args()
    backup(args.source, args.destination)
    print('Private database backup completed and verified. Copy it to secure off-host storage.')
