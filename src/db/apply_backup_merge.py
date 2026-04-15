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

# When merging two apply-status JSON exports (e.g. GHA workspace vs desktop clone), prefer the
# more terminal state so runner-applied rows are not lost when desktop DB is older.
_STATUS_RANK = {
    "applied": 100,
    "closed": 85,
    "captcha": 75,
    "failed": 65,
    "approved": 50,
    "not_applied": 10,
    "": 10,
}


def _rank_status(st: str) -> int:
    s = (st or "").strip() or "not_applied"
    return int(_STATUS_RANK.get(s, 0))


def merge_apply_backup_json_files(paths: list[str], out_path: str) -> str:
    """
    Merge multiple JSON backups (same shape as CI export: list of {jid, st, at}).
    Duplicate job_ids: keep the row with higher _STATUS_RANK; ties on 'applied' prefer non-null at.
    Missing input files are skipped.
    """
    existing = [p for p in paths if os.path.isfile(p)]
    if not existing:
        return "merge: no input files"

    rows_in_order: list[dict] = []
    for p in existing:
        raw = json.loads(open(p, encoding="utf-8").read())
        if isinstance(raw, list):
            rows_in_order.extend(raw)

    by_jid: dict[str, dict] = {}
    for r in rows_in_order:
        jid = r.get("jid")
        if not jid:
            continue
        st = (r.get("st") or "not_applied").strip() or "not_applied"
        prev = by_jid.get(jid)
        if prev is None:
            by_jid[jid] = dict(r)
            continue
        st_old = (prev.get("st") or "not_applied").strip() or "not_applied"
        rn, ro = _rank_status(st), _rank_status(st_old)
        if rn > ro:
            by_jid[jid] = dict(r)
        elif rn == ro == _rank_status("applied"):
            at_new = r.get("at")
            at_old = prev.get("at")
            if at_new and not at_old:
                by_jid[jid] = dict(r)

    out_list = list(by_jid.values())
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(out_list))
    return (
        f"merge: wrote {len(out_list)} job(s) to {out_path} "
        f"from {len(existing)} file(s)"
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

    CI after merge_apply_backup_json_files (merged_backup=True): Conflicts are already
    resolved in the JSON; always apply each row. Otherwise runner failures never reach the DB
    when the artifact row is still 'approved' from desktop/Telegram.
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
