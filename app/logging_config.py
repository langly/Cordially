"""Application logging.

One place configures every logger. Two streams share the setup:

* ``events.request`` / the app logger -- operational: each request and any
  unhandled error (the "is it up, what 500'd" log);
* ``events.audit`` -- security-relevant actions (see ``app/audit.py``).

Both land in the same rotating file so the timeline is unified; grep
``events.audit`` to isolate the audit trail. Output also mirrors to stdout so a
container platform still captures it.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask

BASE_DIR = Path(__file__).resolve().parent.parent

_FORMAT = "%(asctime)s %(levelname)-5s %(name)s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def init_logging(app: Flask) -> None:
    """Attach handlers once per process.

    Idempotent: the factory can run several times (tests, some servers) without
    stacking duplicate handlers, and tests get no file handler.
    """
    level_name = (app.config.get("LOG_LEVEL") or os.environ.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Marker so a second create_app() doesn't add the handlers again.
    if any(getattr(h, "_events_handler", False) for h in root.handlers):
        return

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream._events_handler = True
    root.addHandler(stream)

    # Tests exercise logging through caplog; writing rotating files for every
    # create_app() would litter the tree, so the file handler is skipped there.
    if not app.config.get("TESTING"):
        log_dir = Path(app.config.get("LOG_DIR") or os.environ.get("LOG_DIR") or BASE_DIR / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_dir / "events.log",
            maxBytes=int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024)),
            backupCount=int(os.environ.get("LOG_BACKUPS", 5)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._events_handler = True
        root.addHandler(file_handler)

    # The Flask dev server's access log would duplicate our request log, and
    # SQLAlchemy echo is controlled separately -- keep both quiet here.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app.logger.setLevel(level)
