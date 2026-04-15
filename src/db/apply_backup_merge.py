"""Merge _apply_backup.json into jobs.db after artifact download (CI apply / ingest).

Without this, a local backup from a previous run (e.g. apply_status=failed after Retry)
overwrites apply_status=approved coming from the telegram-ingest artifact.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.models import Job

# Do not clobber a fresh Telegram approval with stale *failure* states from the same machine.
# "applied" must NOT be here: after artifact overlay the row is often approved (from ingest) while
# the backup still has applied from the last runner — we must merge to applied or the runner retries.
_SKIP_WHEN_CURRENT_APPROVED = frozenset(
    {"failed", "captcha", "closed", "not_applied", ""}
)


def restore_apply_statuses_from_backup(
    session: Session,
    backup_path: str = "_apply_backup.json",
    *,
    merged_backup: bool = False,
) -> str:
    """
    Apply backed-up rows onto the current DB (post-artifact).

    Local sync (merged_backup=False): If the DB already has apply_status='approved' and the
    backup would replace it with failed/captcha/closed/not_applied, skip — so a fresh Telegram
    approval is not overwritten by an older failure from the same machine.

    CI apply workflow (merged_backup=True): always apply each backup row — runner outcomes
    must not be skipped when the DB row is still 'approved' from Telegram/desktop.
    """
    if not os.path.exists(backup_path):
        return "restore: no _apply_backup.json"

    rows = json.loads(open(backup_path, encoding="utf-8").read())
    merged = 0
    skipped = 0

    for r in rows:
        jid = r.get("jid")
        if not jid:
            continue
        j = session.query(Job).filter(Job.job_id == jid).first()
        if not j:
            continue

        st = r.get("st") or "not_applied"
        cur = (j.apply_status or "").strip() or "not_applied"

        if (
            not merged_backup
            and cur == "approved"
            and st in _SKIP_WHEN_CURRENT_APPROVED
        ):
            skipped += 1
            continue

        j.apply_status = st
        at = r.get("at")
        if at and str(at) not in ("None", ""):
            try:
                j.applied_at = datetime.fromisoformat(str(at))
            except (TypeError, ValueError):
                pass
        merged += 1

    fixed = (
        session.query(Job)
        .filter((Job.apply_status == "") | (Job.apply_status.is_(None)))
        .update({Job.apply_status: "not_applied"})
    )
    session.commit()
    tail = f"merged={merged} skipped_keep_approved={skipped} fixed_empty={fixed}"
    if merged_backup:
        tail += " (merged_backup=True)"
    return f"restore: {tail}"
