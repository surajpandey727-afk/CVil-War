"""The daily run (Vercel Cron): auth, stage budgets, and the one-email-per-user digest."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.tenant import current_user_id
from app.models.notification import Notification
from app.models.user import User
from app.services import digest
from app.services.gmail_send import NotifyOutcome
from tests.conftest import TEST_USER_ID

CRON = "/api/v1/internal/cron/daily"


@pytest.fixture()
def secret(monkeypatch):
    from app.config.settings import get_settings
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "cron_secret", SecretStr("cron-test-secret"))
    return "cron-test-secret"


class TestCronAuth:
    async def test_rejects_a_missing_or_wrong_secret(self, anon_client, secret) -> None:
        assert (await anon_client.get(CRON)).status_code == 401
        bad = {"Authorization": "Bearer nope"}
        assert (await anon_client.get(CRON, headers=bad)).status_code == 401

    async def test_unset_secret_never_authorises_an_empty_bearer(self, anon_client) -> None:
        assert (await anon_client.get(CRON, headers={"Authorization": "Bearer "})).status_code == 401

    async def test_runs_with_the_right_secret(self, anon_client, secret) -> None:
        with patch(
            "app.services.digest.run_daily", new=AsyncMock(return_value={"digests_sent": 0})
        ) as run:
            resp = await anon_client.get(CRON, headers={"Authorization": f"Bearer {secret}"})
        assert resp.status_code == 200
        run.assert_awaited_once()


class TestStageBudgets:
    async def test_a_slow_stage_is_stopped_and_the_rest_still_run(self) -> None:
        async def slow(ctx):  # noqa: ANN001, ANN202
            await asyncio.sleep(5)

        with (
            patch("app.services.discovery_scheduler.run_discovery_for_all_users", new=slow),
            patch("app.services.inbox_sync.run_inbox_sync_for_all_users", new=AsyncMock()),
            patch.object(digest, "send_daily_digests", new=AsyncMock(return_value=1)),
        ):
            out = await digest.run_daily(discovery_budget=0.05)
        assert out["discovery"].startswith("stopped at")
        assert out["inbox_sync"] == "ok"
        assert out["digests_sent"] == 1


class TestDigest:
    @pytest.fixture()
    async def seeded(self, async_engine, monkeypatch):
        factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(digest, "async_session_factory", factory)
        token = current_user_id.set(None)
        now = datetime.now(UTC)
        async with factory() as db:
            db.add(User(id=TEST_USER_ID, email="t@example.com", hashed_password="x"))
            db.add_all(
                [
                    Notification(user_id=TEST_USER_ID, kind="best_match", title="Strong match: PM",
                                 dedup_key="a", link="/jobs", created_at=now - timedelta(hours=2)),
                    Notification(user_id=TEST_USER_ID, kind="application_submitted",
                                 title="Applied: PM", dedup_key="b", created_at=now - timedelta(hours=1)),
                    # Already emailed on its own — not repeated in the digest.
                    Notification(user_id=TEST_USER_ID, kind="action_required", title="Needs you",
                                 dedup_key="c", emailed_at=now, created_at=now),
                    # Older than the window.
                    Notification(user_id=TEST_USER_ID, kind="new_jobs", title="Old",
                                 dedup_key="d", created_at=now - timedelta(days=3)),
                ]
            )
            await db.commit()
        current_user_id.reset(token)
        return factory

    async def test_one_email_with_the_days_unsent_items_then_stamped(self, seeded) -> None:
        with patch(
            "app.services.gmail_send.send_notification_email",
            new=AsyncMock(return_value=NotifyOutcome.SENT),
        ) as send:
            assert await digest.send_daily_digests() == 1
        kw = send.await_args.kwargs
        assert kw["subject"] == "CVil-War daily: 1 strong match, 1 application update"
        assert "Strong match: PM" in kw["body"] and "Applied: PM" in kw["body"]
        assert "Needs you" not in kw["body"] and "Old" not in kw["body"]
        token = current_user_id.set(None)
        try:
            async with seeded() as db:
                rows = (await db.execute(select(Notification))).scalars().all()
        finally:
            current_user_id.reset(token)
        assert {r.dedup_key for r in rows if r.emailed_at} == {"a", "b", "c"}

    async def test_gmail_not_connected_sends_nothing_and_stamps_nothing(self, seeded) -> None:
        with patch(
            "app.services.gmail_send.send_notification_email",
            new=AsyncMock(return_value=NotifyOutcome.NOT_CONNECTED),
        ):
            assert await digest.send_daily_digests() == 0
        token = current_user_id.set(None)
        try:
            async with seeded() as db:
                stamped = (
                    await db.execute(select(Notification).where(Notification.emailed_at.is_not(None)))
                ).scalars().all()
        finally:
            current_user_id.reset(token)
        assert {r.dedup_key for r in stamped} == {"c"}
