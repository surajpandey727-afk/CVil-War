"""Launcher for the database-as-queue worker (app.workers.db_queue).

``--prod`` points the worker at PROD_DATABASE_URL. That has to happen before any ``app``
module is imported, because the SQLAlchemy engine is built from DATABASE_URL at import time.

    python scripts/db_worker.py --prod --dry-run     # read-only: what would run
    python scripts/db_worker.py --prod               # poll production every 30s
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

if "--prod" in sys.argv[1:]:
    url = os.environ.get("PROD_DATABASE_URL", "").strip()
    if not url:
        print("BLOCKED: --prod needs PROD_DATABASE_URL in the environment.")
        raise SystemExit(2)
    os.environ["DATABASE_URL"] = url

from app.workers.db_queue import main  # noqa: E402

raise SystemExit(main())
