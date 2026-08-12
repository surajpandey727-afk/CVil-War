"""Per-user LLM client factory (BYO-key resolution)."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.client import LLMClient, ResolvedLLMCredentials
from app.core.secrets import CredentialStore
from app.models.user_llm_config import UserLLMConfig

logger = structlog.get_logger(__name__)


async def build_llm_client_for_user(
    db: AsyncSession, user_id: str, credential_store: CredentialStore | None = None
) -> LLMClient:
    """Build an LLMClient bound to the user's BYO key + preferred provider/model.

    Falls back to the global-key client if the user has not stored a key.
    """
    config = (
        await db.execute(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))
    ).scalar_one_or_none()
    provider = config.preferred_provider if config else "openai"
    default_model = config.default_model if config else "gpt-4o"

    store = credential_store or CredentialStore()
    api_key = await store.get_llm_key(db, user_id, provider)
    if not api_key:
        logger.info("llm_client.no_user_key", user_id=user_id, provider=provider)
        return LLMClient(user_id=user_id)
    return LLMClient(
        credentials=ResolvedLLMCredentials(
            provider=provider, api_key=api_key, default_model=default_model
        ),
        user_id=user_id,
    )
