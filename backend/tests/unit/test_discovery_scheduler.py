"""Unit tests for app.services.discovery_scheduler — the previously-missing scheduler.

Root cause under test: nothing polled any source in the background; job search only ran
when a user hit the /jobs endpoint. These tests exercise the fan-out logic in isolation
(mocking search_jobs so nothing hits the network), and the user-selection/tenant-scoping
logic that wraps it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.db.tenant import current_user_id
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.job import JobListResponse
from app.services import discovery_scheduler
from tests.conftest import TEST_USER_ID


def _role_target(title: str, *, active: bool = True) -> dict:
    return {"title": title, "active": active, "fit": 3.0, "why": "", "family": "engineering"}


def _uid(prefix: str) -> str:
    """A 32-char id matching the String(32) PK column, built from a readable prefix."""
    return prefix.ljust(30, "0") + "aa"


class TestQueriesFor:
    def test_no_settings_returns_empty(self) -> None:
        assert discovery_scheduler._queries_for(None) == []

    def test_no_role_targets_returns_empty(self) -> None:
        settings = UserSettings(user_id=TEST_USER_ID, role_targets=None)
        assert discovery_scheduler._queries_for(settings) == []

    def test_returns_active_titles(self) -> None:
        settings = UserSettings(
            user_id=TEST_USER_ID,
            role_targets=[_role_target("Data Scientist"), _role_target("ML Engineer")],
        )
        assert discovery_scheduler._queries_for(settings) == ["Data Scientist", "ML Engineer"]

    def test_excludes_inactive_targets(self) -> None:
        settings = UserSettings(
            user_id=TEST_USER_ID,
            role_targets=[
                _role_target("Data Scientist"),
                _role_target("Retired Title", active=False),
            ],
        )
        assert discovery_scheduler._queries_for(settings) == ["Data Scientist"]

    def test_excludes_blank_titles(self) -> None:
        settings = UserSettings(
            user_id=TEST_USER_ID, role_targets=[_role_target(""), _role_target("Data Analyst")],
        )
        assert discovery_scheduler._queries_for(settings) == ["Data Analyst"]

    def test_caps_at_max_queries_per_user(self) -> None:
        targets = [_role_target(f"Role {i}") for i in range(discovery_scheduler.MAX_QUERIES_PER_USER + 3)]
        settings = UserSettings(user_id=TEST_USER_ID, role_targets=targets)
        result = discovery_scheduler._queries_for(settings)
        assert len(result) == discovery_scheduler.MAX_QUERIES_PER_USER


class TestDiscoverForUser:
    async def test_no_role_targets_skips_search_entirely(self, db_session) -> None:
        db_session.add(UserSettings(user_id=TEST_USER_ID, role_targets=None))
        await db_session.commit()

        with patch.object(discovery_scheduler, "search_jobs", new=AsyncMock()) as mock_search:
            found = await discovery_scheduler._discover_for_user(db_session, TEST_USER_ID)

        assert found == 0
        mock_search.assert_not_awaited()

    async def test_searches_each_active_role_target(self, db_session) -> None:
        db_session.add(
            UserSettings(
                user_id=TEST_USER_ID,
                role_targets=[_role_target("Data Scientist"), _role_target("MLOps Engineer")],
                platforms_enabled=["remotive"],
            )
        )
        await db_session.commit()

        mock_response = JobListResponse(items=[], total=3, page=1, page_size=25, has_next=False)
        with patch.object(
            discovery_scheduler, "search_jobs", new=AsyncMock(return_value=mock_response)
        ) as mock_search, patch.object(
            discovery_scheduler, "usable_keys", return_value=["remotive"]
        ):
            found = await discovery_scheduler._discover_for_user(db_session, TEST_USER_ID)

        assert mock_search.await_count == 2
        assert found == 6  # 3 jobs x 2 queries

    async def test_unset_platforms_enabled_resolves_through_every_usable_source(
        self, db_session,
    ) -> None:
        """Pins the fix for a real bug: an unconfigured account's discovery must consider
        every genuinely usable source, not silently fall back to a hand-maintained list
        that excluded Reed/Adzuna and included two known-dead scrapers."""
        db_session.add(
            UserSettings(
                user_id=TEST_USER_ID,
                role_targets=[_role_target("Data Scientist")],
                platforms_enabled=[],
            )
        )
        await db_session.commit()

        mock_response = JobListResponse(items=[], total=1, page=1, page_size=25, has_next=False)
        with patch.object(
            discovery_scheduler, "search_jobs", new=AsyncMock(return_value=mock_response)
        ), patch.object(
            discovery_scheduler, "usable_keys", return_value=["remotive", "reed", "adzuna"],
        ) as mock_usable_keys:
            found = await discovery_scheduler._discover_for_user(db_session, TEST_USER_ID)

        # None, not a fixed list — this is the actual assertion under test.
        mock_usable_keys.assert_called_once_with(None)
        assert found == 1

    async def test_no_usable_platforms_skips_search(self, db_session) -> None:
        db_session.add(
            UserSettings(
                user_id=TEST_USER_ID,
                role_targets=[_role_target("Data Scientist")],
                platforms_enabled=["some_dead_source"],
            )
        )
        await db_session.commit()

        with patch.object(discovery_scheduler, "search_jobs", new=AsyncMock()) as mock_search, \
                patch.object(discovery_scheduler, "usable_keys", return_value=[]):
            found = await discovery_scheduler._discover_for_user(db_session, TEST_USER_ID)

        assert found == 0
        mock_search.assert_not_awaited()

    async def test_one_failing_query_does_not_stop_the_others(self, db_session) -> None:
        db_session.add(
            UserSettings(
                user_id=TEST_USER_ID,
                role_targets=[_role_target("Broken Query"), _role_target("Good Query")],
                platforms_enabled=["remotive"],
            )
        )
        await db_session.commit()

        good_response = JobListResponse(items=[], total=2, page=1, page_size=25, has_next=False)

        async def _fake_search(db, request, user_id):
            if request.query == "Broken Query":
                raise RuntimeError("adapter blew up")
            return good_response

        with patch.object(discovery_scheduler, "search_jobs", new=_fake_search), patch.object(
            discovery_scheduler, "usable_keys", return_value=["remotive"]
        ):
            found = await discovery_scheduler._discover_for_user(db_session, TEST_USER_ID)

        assert found == 2  # only the surviving query's results are counted


class TestRunDiscoveryForAllUsers:
    async def test_only_active_non_deleted_users_are_processed(self, db_session) -> None:
        from datetime import UTC, datetime

        active = User(id=_uid("active"), email="a@x.com", is_active=True)
        inactive = User(id=_uid("inactive"), email="b@x.com", is_active=False)
        deleted = User(
            id=_uid("deleted"),
            email="c@x.com",
            is_active=True,
            deleted_at=datetime.now(UTC),
        )
        db_session.add_all([active, inactive, deleted])
        await db_session.commit()

        seen_user_ids: list[str] = []

        async def _fake_discover(db, user_id):
            seen_user_ids.append(user_id)
            return 0

        with patch.object(
            discovery_scheduler, "async_session_factory", return_value=_CtxManager(db_session)
        ), patch.object(discovery_scheduler, "_discover_for_user", new=_fake_discover):
            await discovery_scheduler.run_discovery_for_all_users({})

        assert seen_user_ids == [active.id]

    async def test_scopes_and_resets_tenant_context_per_user(self, db_session) -> None:
        user = User(id=_uid("scoped"), email="scoped@x.com", is_active=True)
        db_session.add(user)
        await db_session.commit()

        seen_during_call: list[str | None] = []

        async def _fake_discover(db, user_id):
            seen_during_call.append(current_user_id.get())
            return 0

        outer_token = current_user_id.set("outer-context")
        try:
            with patch.object(
                discovery_scheduler, "async_session_factory", return_value=_CtxManager(db_session)
            ), patch.object(discovery_scheduler, "_discover_for_user", new=_fake_discover):
                await discovery_scheduler.run_discovery_for_all_users({})
            assert seen_during_call == [user.id]
            assert current_user_id.get() == "outer-context"  # restored, not leaked
        finally:
            current_user_id.reset(outer_token)

    async def test_one_user_failing_does_not_stop_the_cycle(self, db_session) -> None:
        u1 = User(id=_uid("failing"), email="f@x.com", is_active=True)
        u2 = User(id=_uid("succeed"), email="s@x.com", is_active=True)
        db_session.add_all([u1, u2])
        await db_session.commit()

        seen: list[str] = []

        async def _fake_discover(db, user_id):
            if user_id == u1.id:
                raise RuntimeError("boom")
            seen.append(user_id)
            return 0

        with patch.object(
            discovery_scheduler, "async_session_factory", return_value=_CtxManager(db_session)
        ), patch.object(discovery_scheduler, "_discover_for_user", new=_fake_discover):
            await discovery_scheduler.run_discovery_for_all_users({})  # must not raise

        assert seen == [u2.id]


class _CtxManager:
    """Async-context-manager stand-in for async_session_factory() in tests.

    ``run_discovery_for_all_users`` opens its own session via ``async with
    async_session_factory() as db``; tests need that to yield the shared ``db_session``
    fixture (already inside a transaction) rather than opening a second, empty connection.
    """

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False
