"""One real LLM call through the app's own client, to prove the configured route works.

    ANTHROPIC_API_KEY=... python scripts/llm_smoke.py            # default route (Sonnet)
    ANTHROPIC_API_KEY=... python scripts/llm_smoke.py classify   # classification route (Haiku)

Prints the model that answered, token counts and the validated JSON — never the key. Exits 2
(BLOCKED) when ANTHROPIC_API_KEY is unset, 1 on a failed call, 0 on success.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from pydantic import BaseModel  # noqa: E402

from app.core.llm.client import LLMClient, anthropic_key_configured  # noqa: E402


class _Smoke(BaseModel):
    verdict: str
    uk_city: str


async def main() -> int:
    if not anthropic_key_configured():
        print("BLOCKED: ANTHROPIC_API_KEY is not set in this environment.")
        return 2
    purpose = "classify" if "classify" in sys.argv[1:] else "general"
    client = LLMClient()
    try:
        out = await client.complete_with_structured_output(
            prompt='Reply with verdict "ok" and the UK city where the Houses of Parliament are.',
            output_schema=_Smoke,
            purpose=purpose,
        )
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    print(f"PASS: purpose={purpose} validated={out.model_dump()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
