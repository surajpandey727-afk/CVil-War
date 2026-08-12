"""Process-wide cached spaCy pipeline for ATS scoring.

``spacy.load()`` reads the model from disk (~0.5-1s) and is CPU-bound. Loading it on every
resume score / skill-extraction / optimize call both stalls the request and — on the async
request path — blocks the event loop. Load it once here and share it across all call sites.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

_MODEL = "en_core_web_sm"


@lru_cache(maxsize=1)
def get_nlp(model: str = _MODEL) -> Any:
    """Return the cached spaCy ``Language`` pipeline (loaded once per process)."""
    import spacy

    return spacy.load(model)
