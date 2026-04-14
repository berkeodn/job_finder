"""CLI: drain Telegram apply callbacks into jobs.db (apply_status=approved). No browser."""

from __future__ import annotations

import logging
import sys

from src.db.database import get_session, init_db

from .telegram_poll import drain_telegram_callbacks_to_db

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    init_db()
    session = get_session()
    try:
        n = drain_telegram_callbacks_to_db(session)
        logger.info("Telegram ingest finished: %d callback(s) -> DB", n)
    finally:
        session.close()


if __name__ == "__main__":
    main()
