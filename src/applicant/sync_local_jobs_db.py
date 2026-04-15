"""Replace local jobs.db with a scrape-artifact DB while preserving apply_status rows.

Same merge rules as CI (apply.yml) via restore_apply_statuses_from_backup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from src.db.apply_backup_merge import restore_apply_statuses_from_backup
from src.db.database import init_db, get_session
from src.db.models import Job


def _export_apply_backup(db_path: Path, out_path: Path) -> int:
    """Write apply statuses to JSON (same shape as apply.yml backup step)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        rows = (
            session.query(Job.job_id, Job.apply_status, Job.applied_at)
            .filter(Job.apply_status.notin_(["not_applied", ""]))
            .all()
        )
        data = [
            {"jid": r[0], "st": r[1], "at": str(r[2]) if r[2] else None} for r in rows
        ]
        out_path.write_text(json.dumps(data), encoding="utf-8")
        return len(data)
    finally:
        session.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Copy scrape artifact jobs.db over local jobs.db, then merge prior apply_status "
            "from a backup JSON (export current DB first)."
        )
    )
    p.add_argument(
        "artifact",
        type=Path,
        help="Path to downloaded jobs.db (e.g. jobs.db.scrape-artifact)",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Directory containing jobs.db (default: cwd)",
    )
    args = p.parse_args()

    repo = args.repo_root.resolve()
    local_db = repo / "jobs.db"
    backup_path = repo / "_local_sync_apply_backup.json"

    artifact = args.artifact.resolve()
    if not artifact.is_file():
        print(f"Artifact not found: {artifact}", file=sys.stderr)
        sys.exit(2)

    n = 0
    if local_db.is_file():
        n = _export_apply_backup(local_db, backup_path)
        print(f"Exported apply statuses from current jobs.db: {n} row(s) -> {backup_path.name}")
    else:
        if backup_path.exists():
            backup_path.unlink()
        print("No existing jobs.db; starting from artifact only.")

    shutil.copyfile(artifact, local_db)
    print(f"Copied artifact -> {local_db}")

    # Replace file on disk; drop pooled connections so we read the new SQLite file.
    from src.db.database import engine as _engine

    _engine.dispose()

    init_db()
    session = get_session()
    try:
        if backup_path.is_file():
            msg = restore_apply_statuses_from_backup(session, str(backup_path))
            print(msg)
        else:
            print("restore: no backup to merge")
    finally:
        session.close()


if __name__ == "__main__":
    main()
