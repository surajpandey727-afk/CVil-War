"""Vercel serverless entrypoint for the CVil-War API.

Vercel's Python runtime serves an ASGI application exported as ``app`` from this module, so
this file is a thin adapter over the real application in :mod:`app.main` rather than a second
copy of it — there is one API, deployed two ways.

What this deployment deliberately does not carry: Chromium (live browser apply), spaCy
(ATS keyword scoring) and WeasyPrint (PDF rendering). All three need either a native system
library or a multi-hundred-megabyte download that a serverless bundle cannot hold, and all
three are already imported lazily, so their absence degrades the features that use them
instead of preventing the API from starting. The container images under ``docker/`` remain
the full-fat deployment and are unchanged.
"""

import os
import sys
from pathlib import Path

# The function bundle's working directory is not guaranteed to be this file's parent, and
# ``app`` is a sibling package rather than an installed distribution.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The only writable location in a serverless filesystem. Set before the settings module is
# imported, because storage roots are resolved at import time and a read-only default would
# fail on the first upload rather than at boot.
os.environ.setdefault("STORAGE__LOCAL_ROOT", "/tmp/cvilwar-storage")

from app.main import app  # noqa: E402  - path setup must precede the import

__all__ = ["app"]
