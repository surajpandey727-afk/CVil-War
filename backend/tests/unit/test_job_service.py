"""Unit tests for the job search service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.automation.platforms.base import JobListing
from app.core.exceptions import RecordNotFoundError
from app.models.enums import JobStatus
from app.models.job import Job
from app.schemas.job import JobSearchRequest
from app.services import job_search
from tests.conftest import TEST_USER_ID


def _fix_job_data(sample_job_data: dict) -> dict:
    """Convert skills_required from list to dict for schema compatibility."""
    data = {**sample_job_data}
    if isinstance(data.get("skills_required"), list):
        data["skills_required"] = {"skills": data["skills_required"]}
    return data


class TestSearchJobs:
    async def test_search_jobs_returns_empty_when_no_platforms(
        self, db_session,
    ):
        """Search should return empty results when platforms produce nothing."""
        request = JobSearchRequest(
            query="python developer", platforms=[],
        )
        with patch.object(
            job_search.platform_registry,
            "list_platforms",
            return_value=[],
        ):
            result = await job_search.search_jobs(db_session, request, TEST_USER_ID)
        assert result.items == []
        assert result.total == 0
        assert result.page == 1
        assert result.has_next is False

    async def test_search_jobs_collects_platform_results(self, db_session):
        """Search should collect results from platform scrapers."""
        from app.core.automation.platforms.base import JobListing

        mock_listing = JobListing(
            platform="linkedin",
            platform_job_id="ext-999",
            title="Python Dev",
            company="TestCo",
            location="Remote",
            url="https://example.com/job/999",
            description="A Python role",
        )
        mock_platform = AsyncMock()
        mock_platform.search = AsyncMock(return_value=[mock_listing])

        request = JobSearchRequest(
            query="python developer", platforms=["linkedin"],
        )

        with (
            patch.object(
                job_search.platform_registry, "has", return_value=True,
            ),
            patch.object(
                job_search.platform_registry,
                "create",
                return_value=mock_platform,
            ),
        ):
            result = await job_search.search_jobs(db_session, request, TEST_USER_ID)

        assert result.total == 1
        assert result.items[0].title == "Python Dev"
        assert result.items[0].platform == "linkedin"

    async def test_search_jobs_handles_platform_failure(self, db_session):
        """Search should return empty results when platform raises."""
        mock_platform = AsyncMock()
        mock_platform.search = AsyncMock(
            side_effect=RuntimeError("network error"),
        )

        request = JobSearchRequest(
            query="python developer", platforms=["linkedin"],
        )

        with (
            patch.object(
                job_search.platform_registry, "has", return_value=True,
            ),
            patch.object(
                job_search.platform_registry,
                "create",
                return_value=mock_platform,
            ),
        ):
            result = await job_search.search_jobs(db_session, request, TEST_USER_ID)

        assert result.total == 0
        assert result.items == []

    async def test_no_explicit_platforms_resolves_through_usable_keys(self, db_session):
        """Pins a real bug: an unspecified platform list must resolve through the source
        registry's live health, not a hand-maintained constant. The constant was missing
        Reed and Adzuna despite both being implemented and credentialed — a default search
        never queried either, silently, because they were never added to the list."""
        request = JobSearchRequest(query="python developer", platforms=None)

        with (
            patch.object(
                job_search, "usable_keys", return_value=["reed", "adzuna"],
            ) as mock_usable_keys,
            patch.object(job_search.platform_registry, "has", return_value=False),
        ):
            await job_search.search_jobs(db_session, request, TEST_USER_ID)

        mock_usable_keys.assert_called_once_with()

    async def test_exa_not_configured_logs_at_info_not_silently(self, db_session):
        """Pins a real gap: an unconfigured Exa key produced no log line at all before this
        — indistinguishable from Exa having been checked and found nothing. The platform
        directive is explicit that a source must never silently return an empty result."""
        # A harmless, non-matching platform keeps this test from touching a real registered
        # source while still passing the "search nothing" early-return the empty-list case
        # would otherwise hit before the code under test even runs.
        request = JobSearchRequest(query="python developer", platforms=["does_not_exist"])

        with (
            patch.object(job_search, "logger") as mock_logger,
            patch.object(job_search.platform_registry, "has", return_value=False),
        ):
            await job_search.search_jobs(db_session, request, TEST_USER_ID)

        mock_logger.info.assert_any_call(
            "job_search.exa_not_configured", reason="no EXA_API_KEY",
        )

    async def test_exa_failure_is_logged_loudly_not_at_debug(self, db_session):
        """A configured-but-failing Exa call used to be swallowed at debug level — a real
        defect looked identical to a quiet, healthy no-op."""
        request = JobSearchRequest(query="python developer", platforms=["does_not_exist"])

        with (
            patch.object(job_search, "logger") as mock_logger,
            patch.object(job_search.platform_registry, "has", return_value=False),
            patch.object(
                job_search, "ExaJobSearch",
                return_value=MagicMock(
                    available=True,
                    search_jobs=AsyncMock(side_effect=RuntimeError("exa API down")),
                ),
            ),
        ):
            await job_search.search_jobs(db_session, request, TEST_USER_ID)

        mock_logger.warning.assert_any_call("job_search.exa_failed", error="exa API down")
        mock_logger.debug.assert_not_called()

    async def test_source_fetches_run_concurrently_not_sequentially(self, db_session):
        """Pins a real, measured performance bug: the default fan-out now legitimately
        covers 60+ sources (see the previous test), and a sequential loop turned a search
        that should take about as long as its slowest source into one that takes the SUM
        of every source's latency — well over a minute, measured live."""
        import time

        names = [f"fake_platform_{i}" for i in range(6)]
        delay_s = 0.2

        async def _slow_search(*, query, location, filters):
            await asyncio.sleep(delay_s)
            return []

        mock_platform = AsyncMock()
        mock_platform.search = _slow_search
        request = JobSearchRequest(query="python developer", platforms=names)

        with (
            patch.object(job_search.platform_registry, "has", return_value=True),
            patch.object(job_search.platform_registry, "create", return_value=mock_platform),
        ):
            start = time.monotonic()
            await job_search.search_jobs(db_session, request, TEST_USER_ID)
            elapsed = time.monotonic() - start

        # Sequential would take ~6 * 0.2s = 1.2s; concurrent (well under the 10-fetch cap)
        # should take barely more than one source's own delay.
        assert elapsed < delay_s * 3

    async def test_source_fetch_concurrency_is_bounded(self, db_session):
        """The cap itself matters, not just "some" concurrency: 60+ simultaneous outbound
        connections from one search is its own way to look like an attack to an upstream."""
        names = [f"fake_platform_{i}" for i in range(job_search._MAX_CONCURRENT_SOURCE_FETCHES + 5)]
        in_flight = 0
        max_in_flight = 0

        async def _tracked_search(*, query, location, filters):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return []

        mock_platform = AsyncMock()
        mock_platform.search = _tracked_search
        request = JobSearchRequest(query="python developer", platforms=names)

        with (
            patch.object(job_search.platform_registry, "has", return_value=True),
            patch.object(job_search.platform_registry, "create", return_value=mock_platform),
        ):
            await job_search.search_jobs(db_session, request, TEST_USER_ID)

        assert max_in_flight <= job_search._MAX_CONCURRENT_SOURCE_FETCHES

    async def test_a_source_stuck_past_the_deadline_does_not_block_the_others(
        self, db_session,
    ):
        """Pins the fix for the second half of the same performance bug: bounded
        concurrency alone still let a handful of stuck/rate-limited sources hold the
        whole search open (measured live: ~90s against the real default fan-out). A
        source past the deadline degrades like any other per-source failure — dropped,
        not waited on — while sources that already answered are still used."""
        request = JobSearchRequest(query="python developer", platforms=["slow", "fast"])

        async def _search_for(name):
            if name == "slow":
                await asyncio.sleep(job_search._SEARCH_FETCH_DEADLINE_S + 5)
                return []
            return [
                JobListing(
                    platform="fast", platform_job_id="f1", title="Eng", company="Acme",
                    location="London", url="https://example.com", description="",
                )
            ]

        def _make_platform(name):
            m = MagicMock()

            async def _bound_search(**kwargs):
                return await _search_for(name)

            m.search = _bound_search
            return m

        with (
            patch.object(job_search, "_SEARCH_FETCH_DEADLINE_S", 0.2),
            patch.object(job_search.platform_registry, "has", return_value=True),
            patch.object(
                job_search.platform_registry, "create", side_effect=_make_platform,
            ),
        ):
            result = await job_search.search_jobs(db_session, request, TEST_USER_ID)

        assert result.total == 1
        assert result.items[0].platform == "fast"


class TestListJobs:
    async def test_list_jobs_empty_db(self, db_session):
        result = await job_search.list_jobs(db_session)
        assert result.items == []
        assert result.total == 0
        assert result.has_next is False

    async def test_list_jobs_with_data(self, db_session, sample_job_data):
        fixed = _fix_job_data(sample_job_data)
        for i in range(3):
            data = {**fixed, "platform_job_id": f"job-{i}"}
            db_session.add(Job(**data))
        await db_session.commit()

        result = await job_search.list_jobs(db_session, page=1, page_size=2)
        assert len(result.items) == 2
        assert result.total == 3
        assert result.has_next is True

        result2 = await job_search.list_jobs(db_session, page=2, page_size=2)
        assert len(result2.items) == 1
        assert result2.has_next is False

    async def test_list_jobs_filter_by_status(
        self, db_session, sample_job_data,
    ):
        fixed = _fix_job_data(sample_job_data)
        for i, status in enumerate(["new", "new", "saved"]):
            data = {
                **fixed, "platform_job_id": f"job-{i}", "status": status,
            }
            db_session.add(Job(**data))
        await db_session.commit()

        result = await job_search.list_jobs(db_session, status="new")
        assert result.total == 2

        result_saved = await job_search.list_jobs(db_session, status="saved")
        assert result_saved.total == 1


class TestListJobsWithCriteria:
    """``user_id`` opts into the operator's hard filters (salary floor, excluded employment
    types) and a sponsor-confidence ranking boost — see services.job_search.list_jobs."""

    async def _seed(self, db_session, fixed: dict, **overrides) -> Job:
        data = {**fixed, "platform_job_id": overrides.pop("platform_job_id"), **overrides}
        job = Job(**data)
        db_session.add(job)
        await db_session.commit()
        return job

    async def test_below_floor_salary_is_excluded(self, db_session, sample_job_data) -> None:
        from app.models.user_settings import UserSettings

        fixed = _fix_job_data(sample_job_data)
        await self._seed(
            db_session, fixed, platform_job_id="low", salary_range="£30,000 - £35,000",
        )
        await self._seed(
            db_session, fixed, platform_job_id="high", salary_range="£60,000 - £70,000",
        )
        db_session.add(
            UserSettings(user_id=TEST_USER_ID, automation={"min_salary_k": 50})
        )
        await db_session.commit()

        result = await job_search.list_jobs(db_session, user_id=TEST_USER_ID)
        assert result.total == 1
        assert result.items[0].platform_job_id == "high"

    async def test_jobs_with_no_published_salary_are_kept(
        self, db_session, sample_job_data
    ) -> None:
        """A below-floor role is excluded; an unpublished band is not the same as a below-
        floor one and must not be discarded — most UK postings omit a salary entirely."""
        from app.models.user_settings import UserSettings

        fixed = _fix_job_data(sample_job_data)
        await self._seed(db_session, fixed, platform_job_id="no-salary", salary_range=None)
        db_session.add(
            UserSettings(user_id=TEST_USER_ID, automation={"min_salary_k": 50})
        )
        await db_session.commit()

        result = await job_search.list_jobs(db_session, user_id=TEST_USER_ID)
        assert result.total == 1

    async def test_excluded_employment_type_is_filtered_out(
        self, db_session, sample_job_data
    ) -> None:
        from app.models.user_settings import UserSettings

        fixed = _fix_job_data(sample_job_data)
        await self._seed(db_session, fixed, platform_job_id="c", job_type="contract")
        await self._seed(db_session, fixed, platform_job_id="p", job_type="permanent")
        db_session.add(
            UserSettings(
                user_id=TEST_USER_ID,
                automation={"exclude_employment_types": ["contract"]},
            )
        )
        await db_session.commit()

        result = await job_search.list_jobs(db_session, user_id=TEST_USER_ID)
        assert result.total == 1
        assert result.items[0].platform_job_id == "p"

    async def test_default_policy_excludes_contract_and_part_time(
        self, db_session, sample_job_data
    ) -> None:
        """No UserSettings row at all still applies the shipped default exclusions —
        the whole point of the field having a real default rather than an empty list."""
        fixed = _fix_job_data(sample_job_data)
        await self._seed(db_session, fixed, platform_job_id="c", job_type="contract")
        await self._seed(db_session, fixed, platform_job_id="pt", job_type="part-time")
        await self._seed(db_session, fixed, platform_job_id="ft", job_type="full-time")
        await db_session.commit()

        result = await job_search.list_jobs(db_session, user_id=TEST_USER_ID)
        assert result.total == 1
        assert result.items[0].platform_job_id == "ft"

    async def test_sponsor_confirmed_roles_rank_above_unknown_ones(
        self, db_session, sample_job_data
    ) -> None:
        """Ranking boost, not a filter: both roles are returned, but the confirmed sponsor
        sorts first regardless of discovery order."""
        from app.models.enums import SponsorConfidence
        from app.models.user_settings import UserSettings

        fixed = _fix_job_data(sample_job_data)
        # Unknown seeded first (would sort first on created_at alone).
        await self._seed(
            db_session, fixed, platform_job_id="unknown-first",
            sponsor_confidence=SponsorConfidence.UNKNOWN,
        )
        await self._seed(
            db_session, fixed, platform_job_id="confirmed-second",
            sponsor_confidence=SponsorConfidence.CONFIRMED_REGISTER,
        )
        db_session.add(UserSettings(user_id=TEST_USER_ID, automation={}))
        await db_session.commit()

        result = await job_search.list_jobs(db_session, user_id=TEST_USER_ID)
        assert result.total == 2
        assert result.items[0].platform_job_id == "confirmed-second"
        assert result.items[1].platform_job_id == "unknown-first"

    async def test_no_user_id_preserves_legacy_unfiltered_behaviour(
        self, db_session, sample_job_data
    ) -> None:
        """Existing callers with no notion of "whose policy" (and the tests above them in
        this file) must see identical behaviour to before this feature existed."""
        fixed = _fix_job_data(sample_job_data)
        await self._seed(db_session, fixed, platform_job_id="contract-role", job_type="contract")
        await db_session.commit()

        result = await job_search.list_jobs(db_session)
        assert result.total == 1  # not excluded — no user_id means no criteria at all


class TestGetJob:
    async def test_get_job_found(self, db_session, sample_job_data):
        job = Job(**sample_job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        found = await job_search.get_job(db_session, job.id)
        assert found.id == job.id
        assert found.title == sample_job_data["title"]

    async def test_get_job_not_found_raises(self, db_session):
        with pytest.raises(RecordNotFoundError):
            await job_search.get_job(db_session, "nonexistent_id")


class TestUpdateJobStatus:
    """There was previously no way to save or hide a job at all — a job only ever moved to
    APPLIED as a side effect of creating an application."""

    async def test_saves_a_job(self, db_session, sample_job_data):
        job = Job(**sample_job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)
        assert job.status == JobStatus.NEW

        updated = await job_search.update_job_status(db_session, job.id, JobStatus.SAVED)
        assert updated.status == JobStatus.SAVED

    async def test_hides_a_job(self, db_session, sample_job_data):
        job = Job(**sample_job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        updated = await job_search.update_job_status(db_session, job.id, JobStatus.HIDDEN)
        assert updated.status == JobStatus.HIDDEN

    async def test_not_found_raises(self, db_session):
        with pytest.raises(RecordNotFoundError):
            await job_search.update_job_status(db_session, "nonexistent_id", JobStatus.SAVED)


class TestDeleteJob:
    async def test_delete_job_success(self, db_session, sample_job_data):
        job = Job(**sample_job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        await job_search.delete_job(db_session, job.id)

        with pytest.raises(RecordNotFoundError):
            await job_search.get_job(db_session, job.id)

    async def test_delete_job_not_found_raises(self, db_session):
        with pytest.raises(RecordNotFoundError):
            await job_search.delete_job(db_session, "nonexistent_id")


class TestAnalyzeJob:
    async def test_analyze_job_no_resume_returns_placeholder(
        self, db_session, sample_job_data,
    ):
        """Without a resume_id, analyze_job returns zero scores."""
        job = Job(**sample_job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        result = await job_search.analyze_job(db_session, job.id)
        assert result.job_id == job.id
        assert result.match_score == 0.0
        assert result.skill_match == 0.0
        assert result.keyword_match == 0.0
        assert len(result.suggestions) > 0

    async def test_analyze_job_not_found_raises(self, db_session):
        with pytest.raises(RecordNotFoundError):
            await job_search.analyze_job(db_session, "nonexistent_id")
