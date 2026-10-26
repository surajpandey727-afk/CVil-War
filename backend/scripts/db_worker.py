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

#: Production storage and LLM, applied over the local .env so the worker reads the same résumé
#: files and uses the same model as the live site. A local .env pointing at a dev gateway
#: or an old Supabase project otherwise made every production apply fail to load the CV.
_PROD_OVERRIDES = {
    "PROD_SUPABASE_URL": "SUPABASE_URL",
    "PROD_SUPABASE_SECRET_KEY": "SUPABASE_SECRET_KEY",
}


def _prod_environment() -> list[str]:
    """Point this process at production. Returns what is still missing (names only)."""
    missing: list[str] = []
    url = os.environ.get("PROD_DATABASE_URL", "").strip()
    if not url:
        return ["PROD_DATABASE_URL"]
    os.environ["DATABASE_URL"] = url
    for source, target in _PROD_OVERRIDES.items():
        value = os.environ.get(source, "").strip()
        if value:
            os.environ[target] = value
        else:
            missing.append(source)
    if not missing:
        os.environ["STORAGE__PROVIDER"] = "supabase"
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        # Same model as production unless the operator chose one for this shell.
        os.environ.setdefault("LLM__DEFAULT_MODEL", "anthropic/claude-sonnet-5-5")
        os.environ.setdefault("LLM__PREFERRED_PROVIDER", "anthropic")
    else:
        missing.append("ANTHROPIC_API_KEY")
    return missing


if "--prod" in sys.argv[1:]:
    gaps = _prod_environment()
    if "PROD_DATABASE_URL" in gaps:
        print("BLOCKED: --prod needs PROD_DATABASE_URL in the environment.")
        raise SystemExit(2)
    if gaps and "--dry-run" not in sys.argv[1:]:
        # A dry run only reads the queue; a real run must load CVs and call the model.
        print(
            "BLOCKED: set "
            + ", ".join(gaps)
            + " (see docs/LOCAL_SETUP.md). Without them the worker cannot read your CVs "
            "from production storage or reach the production model."
        )
        raise SystemExit(2)

from app.workers.db_queue import main  # noqa: E402

raise SystemExit(main())
